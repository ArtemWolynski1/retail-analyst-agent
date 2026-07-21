"""Retrieval evals: hit@1, hit@3, MRR@3 over the golden set, ablated.

Ablation matrix = every embedding version present in the index × every mode
(dense / lexical / hybrid). A hit is any acceptable trio id appearing at the
rank; MRR@3 credits 1/rank of the first acceptable id (0 beyond top-3).
Writes evals/retrieval-report.md.

    DATABASE_URL=... python evals/retrieval_eval.py
"""

import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from psycopg import connect  # noqa: E402

from agent.config import load_settings  # noqa: E402
from agent.retrieval import TrioRetriever, llm_rerank  # noqa: E402

MODES = ("dense", "lexical", "hybrid", "hybrid+rerank")
K = 3
RERANK_CANDIDATES = 10


def evaluate(retriever: TrioRetriever, cases: list[dict], version: str, mode: str) -> dict:
    per_class: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        started = time.monotonic()
        if mode == "hybrid+rerank":
            candidates = retriever.retrieve(case["question"], k=RERANK_CANDIDATES, mode="hybrid", version=version)
            hits = llm_rerank(retriever.settings, case["question"], candidates, k=K)
        else:
            hits = retriever.retrieve(case["question"], k=K, mode=mode, version=version)
        latency_ms = (time.monotonic() - started) * 1000
        got = [h.trio.id for h in hits]
        expected = set(case["expected"])
        rank = next((i + 1 for i, tid in enumerate(got) if tid in expected), None)
        per_class[case["query_class"]].append(
            {
                "id": case["id"],
                "question": case["question"],
                "got": got,
                "rank": rank,
                "latency_ms": latency_ms,
                "top_distance": hits[0].distance if hits else None,
            }
        )
    return per_class


def summarize(results: list[dict]) -> dict:
    n = len(results)
    return {
        "n": n,
        "hit1": sum(1 for r in results if r["rank"] == 1) / n,
        "hit3": sum(1 for r in results if r["rank"] is not None) / n,
        "mrr": sum(1 / r["rank"] for r in results if r["rank"]) / n,
        "ms": sum(r["latency_ms"] for r in results) / n,
    }


def main() -> int:
    settings = load_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set.")
        return 1
    retriever = TrioRetriever(settings)
    cases = yaml.safe_load((ROOT / "evals" / "retrieval_questions.yaml").read_text())

    with connect(settings.database_url) as conn:
        versions = [
            v for (v,) in conn.execute("SELECT DISTINCT embedding_version FROM trio_index ORDER BY 1").fetchall()
        ]
    active = retriever.active_version()

    lines = [
        "# Retrieval eval report",
        "",
        f"Golden set: {len(cases)} questions "
        f"({sum(1 for c in cases if c['query_class'] == 'paraphrase')} paraphrase, "
        f"{sum(1 for c in cases if c['query_class'] == 'lexical')} lexical, "
        f"{sum(1 for c in cases if c['query_class'] == 'ambiguous')} ambiguous). "
        f"A hit is any acceptable trio id in the top-{K}; MRR@{K} credits 1/rank of the first. "
        "Latency is end-to-end per query (dense/hybrid include the query-embedding API call, "
        "which dominates; lexical is pure Postgres).",
        "",
        "| version | mode | hit@1 | hit@3 | MRR@3 | avg ms |",
        "|---|---|---|---|---|---|",
    ]
    detail_lines: list[str] = []
    all_results = {}

    for version in versions:
        for mode in MODES:
            per_class = evaluate(retriever, cases, version, mode)
            flat = [r for rs in per_class.values() for r in rs]
            s = summarize(flat)
            marker = " (active)" if version == active else ""
            lines.append(
                f"| {version}{marker} | {mode} | {s['hit1']:.0%} | {s['hit3']:.0%} | {s['mrr']:.3f} | {s['ms']:.0f} |"
            )
            all_results[(version, mode)] = per_class
            print(
                f"{version} {mode:8s} hit@1={s['hit1']:.0%} hit@3={s['hit3']:.0%} "
                f"mrr={s['mrr']:.3f} avg={s['ms']:.0f}ms",
                flush=True,
            )

    lines += ["", "## Per-class breakdown (hybrid)", ""]
    lines.append("| version | class | hit@1 | hit@3 | MRR@3 |")
    lines.append("|---|---|---|---|---|")
    for version in versions:
        for cls, results in sorted(all_results[(version, "hybrid")].items()):
            s = summarize(results)
            lines.append(f"| {version} | {cls} ({s['n']}) | {s['hit1']:.0%} | {s['hit3']:.0%} | {s['mrr']:.3f} |")

    detail_lines.append("\n## Misses (any config)\n")
    seen_misses = set()
    for (version, mode), per_class in all_results.items():
        for results in per_class.values():
            for r in results:
                if r["rank"] is None:
                    detail_lines.append(f"- `{r['id']}` [{version} / {mode}]: got {r['got']}")
                    seen_misses.add(r["id"])
    if not seen_misses:
        detail_lines.append("- none — every question found an acceptable trio in the top-3 in every config")

    report = ROOT / "evals" / "retrieval-report.md"
    report.write_text("\n".join(lines + detail_lines) + "\n")
    print(f"\nreport: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
