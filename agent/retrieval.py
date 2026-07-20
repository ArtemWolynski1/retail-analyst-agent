"""Golden-bucket retrieval: embeddings + hybrid search over the pgvector index.

Query path (design doc §3.1): embed the question (query task type) → dense ANN
top-K and lexical FTS top-K in one round trip → reciprocal-rank-fusion merge →
top-k trios for the context assembler. The serving index is disposable: rows
are keyed by (trio_id, embedding_version) and reads always filter on the
*active* version from index_meta, so a re-embed is hydrate-then-flip with no
downtime and instant rollback.
"""

import math
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


def _embed(settings: Settings, texts: list[str], task_type: str) -> list[list[float]]:
    """Asymmetric embeddings: documents and queries use different task types so
    a short question lands near a long trio. Vectors are L2-normalized — at
    truncated (Matryoshka) dimensionalities the raw vectors are not unit-norm,
    and normalizing keeps them correct under any distance op, not just cosine."""
    if not settings.google_api_key:
        raise ValueError("embeddings require GOOGLE_API_KEY")
    client = genai.Client(api_key=settings.google_api_key)
    out: list[list[float]] = []
    for start in range(0, len(texts), 50):
        batch = texts[start : start + 50]
        result = client.models.embed_content(
            model=settings.embedding_model,
            contents=batch,
            config=EmbedContentConfig(task_type=task_type, output_dimensionality=settings.embedding_dims),
        )
        for emb in result.embeddings or []:
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

    def retrieve(self, question: str, k: int = 3, candidates: int = 20) -> list[RetrievedTrio]:
        """Hybrid top-k. Returns [] when no index version is active — callers
        fall back to the static few-shots, so an unhydrated index degrades the
        agent instead of breaking it."""
        version = self.active_version()
        if version is None:
            return []
        qvec = Vector(embed_query(self.settings, question))

        with self._conn() as conn:
            dense = conn.execute(
                "SELECT trio_id, question, sql, analyst_notes, tables_used, metric_domain"
                " FROM trio_index WHERE embedding_version = %s"
                " ORDER BY embedding <=> %s LIMIT %s",
                (version, qvec, candidates),
            ).fetchall()
            lexical = conn.execute(
                "SELECT trio_id, question, sql, analyst_notes, tables_used, metric_domain"
                " FROM trio_index, websearch_to_tsquery('english', %s) query"
                " WHERE embedding_version = %s AND fts @@ query"
                " ORDER BY ts_rank(fts, query) DESC LIMIT %s",
                (question, version, candidates),
            ).fetchall()

        dense_rank = {row["trio_id"]: i + 1 for i, row in enumerate(dense)}
        lexical_rank = {row["trio_id"]: i + 1 for i, row in enumerate(lexical)}
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
                )
            )
        return results
