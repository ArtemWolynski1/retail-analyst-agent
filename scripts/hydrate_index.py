"""Hydrate the pgvector serving index from the lake (blue/green).

The lake (data/lake/*.json) is the system of record; the index is disposable.
Rows are keyed by (trio_id, embedding_version), and retrieval reads only the
version index_meta marks active — so hydrating a new embedding version builds
alongside the live one, --activate flips serving atomically, and rollback is
re-pointing at the old version, not a rebuild.

    python scripts/hydrate_index.py              # embed + load verified trios
    python scripts/hydrate_index.py --activate   # ...and flip serving to this version
    python scripts/hydrate_index.py --prune      # drop rows of non-active versions
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pgvector import Vector  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402
from psycopg import connect  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent.config import load_settings  # noqa: E402
from agent.retrieval import embed_documents, embedding_version  # noqa: E402

LAKE = ROOT / "data" / "lake"

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS trio_index (
    trio_id TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    analyst_notes TEXT NOT NULL,
    tables_used TEXT[] NOT NULL DEFAULT '{{}}',
    metric_domain TEXT NOT NULL DEFAULT '',
    embedding vector({dims}) NOT NULL,
    fts tsvector GENERATED ALWAYS AS (
        to_tsvector('english', question || ' ' || analyst_notes || ' ' || sql)
    ) STORED,
    hydrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trio_id, embedding_version)
);
CREATE INDEX IF NOT EXISTS idx_trio_hnsw ON trio_index USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_trio_fts ON trio_index USING gin (fts);
CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activate", action="store_true", help="flip serving to this embedding version after load")
    ap.add_argument("--prune", action="store_true", help="delete rows of non-active embedding versions")
    args = ap.parse_args()

    settings = load_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set — start the db (docker compose up -d db) and set it.")
        return 1
    version = embedding_version(settings)

    trios = [json.loads(p.read_text()) for p in sorted(LAKE.glob("*.json"))]
    verified = [t for t in trios if t.get("status") == "verified"]
    skipped = len(trios) - len(verified)

    # The embedded text mirrors what retrieval matches against: the question
    # carries the semantics, the notes carry the interpretation vocabulary.
    texts = [f"{t['question']}\n{t['analyst_notes']}" for t in verified]
    print(f"embedding {len(verified)} verified trios ({skipped} skipped) as {version}…")
    vectors = embed_documents(settings, texts)

    with connect(settings.database_url, row_factory=dict_row) as conn:
        conn.execute(DDL.format(dims=settings.embedding_dims))
        register_vector(conn)
        for trio, vec in zip(verified, vectors, strict=True):
            conn.execute(
                """INSERT INTO trio_index
                   (trio_id, embedding_version, question, sql, analyst_notes, tables_used, metric_domain, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (trio_id, embedding_version) DO UPDATE SET
                     question = EXCLUDED.question, sql = EXCLUDED.sql,
                     analyst_notes = EXCLUDED.analyst_notes, tables_used = EXCLUDED.tables_used,
                     metric_domain = EXCLUDED.metric_domain, embedding = EXCLUDED.embedding,
                     hydrated_at = now()""",
                (
                    trio["id"],
                    version,
                    trio["question"],
                    trio["sql"],
                    trio["analyst_notes"],
                    trio.get("tables_used", []),
                    trio.get("metric_domain", ""),
                    Vector(vec),
                ),
            )
        if args.activate:
            conn.execute(
                "INSERT INTO index_meta (key, value) VALUES ('active_embedding_version', %s)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (version,),
            )
        active = conn.execute("SELECT value FROM index_meta WHERE key = 'active_embedding_version'").fetchone()
        active = active["value"] if active else None
        if args.prune and active:
            pruned = conn.execute("DELETE FROM trio_index WHERE embedding_version != %s", (active,)).rowcount
            print(f"pruned {pruned} rows of inactive versions")
        counts = conn.execute(
            "SELECT embedding_version, COUNT(*) AS n FROM trio_index GROUP BY 1 ORDER BY 1"
        ).fetchall()

    print(f"hydrated {len(verified)} trios as {version}")
    for c in counts:
        marker = " (active)" if c["embedding_version"] == active else ""
        print(f"  {c['embedding_version']}: {c['n']} rows{marker}")
    if not active:
        print("no active version yet — run with --activate to start serving")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
