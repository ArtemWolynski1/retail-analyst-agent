"""Golden-bucket retrieval: embeddings + hybrid search over the pgvector index.

Query path (design doc §3.1): embed the question (query task type) → dense ANN
top-K and lexical FTS top-K in one round trip → reciprocal-rank-fusion merge →
top-k trios for the context assembler. The serving index is disposable: rows
are keyed by (trio_id, embedding_version) and reads always filter on the
*active* version from index_meta, so a re-embed is hydrate-then-flip with no
downtime and instant rollback.
"""

import json
import math
import re
from dataclasses import dataclass

from google import genai
from google.genai.types import EmbedContentConfig
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import connect
from psycopg.rows import dict_row

from agent.config import Settings
from agent.runtime import Trio

# Rank-based fusion is robust to the two legs' incomparable score scales
# (cosine distance vs ts_rank); 60 is the standard RRF damping constant.
RRF_K = 60


def embedding_version(settings: Settings) -> str:
    return f"{settings.embedding_model}@{settings.embedding_dims}"


def parse_version(version: str) -> tuple[str, int]:
    """A version string IS the (model, dims) pair — queries against an index
    version must embed with that exact pair. Deriving it from anywhere else
    (ambient settings) mixes vector spaces and silently destroys retrieval."""
    model, _, dims = version.rpartition("@")
    return model, int(dims)


def _embed(
    settings: Settings, texts: list[str], task_type: str, model: str | None = None, dims: int | None = None
) -> list[list[float]]:
    """Asymmetric embeddings: documents and queries use different task types so
    a short question lands near a long trio. Vectors are L2-normalized — at
    truncated (Matryoshka) dimensionalities the raw vectors are not unit-norm,
    and normalizing keeps them correct under any distance op, not just cosine."""
    if not settings.google_api_key:
        raise ValueError("embeddings require GOOGLE_API_KEY")
    model = model or settings.embedding_model
    dims = dims or settings.embedding_dims
    client = genai.Client(api_key=settings.google_api_key)
    out: list[list[float]] = []
    config = EmbedContentConfig(task_type=task_type, output_dimensionality=dims)
    for start in range(0, len(texts), 50):
        batch = texts[start : start + 50]
        result = client.models.embed_content(model=model, contents=batch, config=config)
        embs = list(result.embeddings or [])
        if len(embs) != len(batch):
            # Batch semantics differ across model generations: gemini-embedding-2
            # treats a contents list as ONE multi-part document and returns a
            # single vector. Fall back to per-text requests — correctness over
            # throughput; the mismatch would otherwise mis-assign every vector.
            embs = []
            for text in batch:
                single = client.models.embed_content(model=model, contents=text, config=config)
                embs.extend(single.embeddings or [])
        for emb in embs:
            values = list(emb.values or [])
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            out.append([v / norm for v in values])
    if len(out) != len(texts):
        raise RuntimeError(f"embedding API returned {len(out)} vectors for {len(texts)} texts")
    return out


def embed_documents(settings: Settings, texts: list[str]) -> list[list[float]]:
    return _embed(settings, texts, "RETRIEVAL_DOCUMENT")


def embed_query(settings: Settings, text: str) -> list[float]:
    return _embed(settings, [text], "RETRIEVAL_QUERY")[0]


@dataclass(frozen=True)
class RetrievedTrio:
    trio: Trio
    score: float
    dense_rank: int | None
    lexical_rank: int | None
    # Raw cosine distance of the dense hit (None for lexical-only hits). RRF
    # scores are rank-derived and carry no confidence; this is the retrieval-
    # certainty signal (low similarity on the top hit = the corpus has a gap).
    distance: float | None = None


class TrioRetriever:
    def __init__(self, settings: Settings):
        if not settings.database_url:
            raise ValueError("retrieval requires DATABASE_URL (the pgvector serving index)")
        self.settings = settings
        self.dsn: str = settings.database_url

    def _conn(self):
        conn = connect(self.dsn, row_factory=dict_row)
        register_vector(conn)
        return conn

    def active_version(self) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM index_meta WHERE key = 'active_embedding_version'").fetchone()
        return row["value"] if row else None

    def retrieve(
        self,
        question: str,
        k: int = 3,
        candidates: int = 20,
        mode: str = "hybrid",
        version: str | None = None,
    ) -> list[RetrievedTrio]:
        """Top-k for the question. mode: 'hybrid' (default), 'dense', or
        'lexical' — the single-leg modes exist for ablation evals. version
        overrides the active index version (eval compares embedding models
        without flipping serving). Returns [] when no version is active —
        callers fall back to the static few-shots, so an unhydrated index
        degrades the agent instead of breaking it."""
        version = version or self.active_version()
        if version is None:
            return []

        dense, lexical = [], []
        with self._conn() as conn:
            if mode != "lexical":
                # The query must live in the same vector space as the index
                # version it searches — model and dims come FROM the version.
                q_model, q_dims = parse_version(version)
                qvec = Vector(_embed(self.settings, [question], "RETRIEVAL_QUERY", model=q_model, dims=q_dims)[0])
                dense = conn.execute(
                    "SELECT trio_id, question, sql, analyst_notes, tables_used, metric_domain,"
                    " (embedding <=> %s) AS distance"
                    " FROM trio_index WHERE embedding_version = %s"
                    " ORDER BY embedding <=> %s LIMIT %s",
                    (qvec, version, qvec, candidates),
                ).fetchall()
            if mode != "dense":
                lexical = conn.execute(
                    "SELECT trio_id, question, sql, analyst_notes, tables_used, metric_domain"
                    " FROM trio_index, websearch_to_tsquery('english', %s) query"
                    " WHERE embedding_version = %s AND fts @@ query"
                    " ORDER BY ts_rank(fts, query) DESC LIMIT %s",
                    (question, version, candidates),
                ).fetchall()

        dense_rank = {row["trio_id"]: i + 1 for i, row in enumerate(dense)}
        lexical_rank = {row["trio_id"]: i + 1 for i, row in enumerate(lexical)}
        distances = {row["trio_id"]: row["distance"] for row in dense}
        rows = {row["trio_id"]: row for row in [*dense, *lexical]}

        fused = sorted(
            rows,
            key=lambda tid: sum(1.0 / (RRF_K + r) for r in (dense_rank.get(tid), lexical_rank.get(tid)) if r),
            reverse=True,
        )
        results = []
        for tid in fused[:k]:
            row = rows[tid]
            score = sum(1.0 / (RRF_K + r) for r in (dense_rank.get(tid), lexical_rank.get(tid)) if r)
            results.append(
                RetrievedTrio(
                    trio=Trio(
                        id=row["trio_id"],
                        question=row["question"],
                        sql=row["sql"],
                        analyst_notes=row["analyst_notes"],
                        tables_used=tuple(row["tables_used"] or ()),
                    ),
                    score=round(score, 5),
                    dense_rank=dense_rank.get(tid),
                    lexical_rank=lexical_rank.get(tid),
                    distance=round(distances[tid], 4) if tid in distances else None,
                )
            )
        return results


RERANK_PROMPT = """You are reranking retrieved analyst exemplars for relevance to a manager's question.
An exemplar is relevant if its INTERPRETATION LOGIC (metric definition, decomposition, pitfall)
would help answer the question — not merely if it shares words with it.

Question: {question}

Candidates:
{candidates}

Respond with ONLY a JSON object mapping candidate number to a 0-10 relevance score, e.g. {{"1": 9, "2": 3}}.
Score every candidate."""


def llm_rerank(settings: Settings, question: str, hits: list[RetrievedTrio], k: int = 3) -> list[RetrievedTrio]:
    """Listwise cross-attention rerank: one cheap-model call reads the question
    together with every candidate — the precision stage a bi-encoder can't
    provide, at the cost of one extra model call. In production this would be
    a dedicated cross-encoder; the pattern (recall stage → rerank stage) is
    identical. Falls back to the fused order on any parse failure."""
    if len(hits) <= k:
        return hits[:k]
    from agent.llm import build_chat_model

    lines = [
        f"{i + 1}. [{h.trio.id}] Q: {h.trio.question} — Notes: {h.trio.analyst_notes[:200]}" for i, h in enumerate(hits)
    ]
    prompt = RERANK_PROMPT.format(question=question, candidates="\n".join(lines))
    try:
        # The fallback role is the cheapest configured model (flash-lite) —
        # reranking is a scoring task, not a reasoning task.
        raw = build_chat_model(settings, role="fallback").invoke(prompt).content
        text = raw if isinstance(raw, str) else str(raw)
        match = re.search(r"\{[^{}]*\}", text)
        scores = {int(num) - 1: float(s) for num, s in json.loads(match.group()).items()} if match else {}
    except Exception:
        return hits[:k]
    if not scores:
        return hits[:k]
    # Stable sort: fused (RRF) order breaks score ties.
    order = sorted(range(len(hits)), key=lambda i: scores.get(i, -1.0), reverse=True)
    return [hits[i] for i in order[:k]]
