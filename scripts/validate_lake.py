"""Validate every trio in the lake against the live dataset.

The nightly-maintenance primitive from the design doc: each trio's SQL must
pass the same guard the agent uses and dry-run clean on BigQuery (free).
Failures are quarantined in place — a quarantined trio never reaches the
serving index. Schema drift is the silent killer of exemplar corpora; this
is the tripwire.

    python scripts/validate_lake.py [--fix-status]

Without --fix-status the run is read-only (report only). With it, passing
drafts stay drafts (promotion to verified is a human call), but failures
of any status flip to quarantined.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.bq import dry_run, make_client  # noqa: E402
from agent.config import load_settings  # noqa: E402
from agent.safety import sql_guard  # noqa: E402

LAKE = ROOT / "data" / "lake"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-status", action="store_true", help="quarantine failing trios in place")
    args = ap.parse_args()

    settings = load_settings()
    client = make_client(settings)
    failures = 0

    for path in sorted(LAKE.glob("*.json")):
        trio = json.loads(path.read_text())
        problem = None
        guarded = sql_guard.validate(trio["sql"], settings)
        if not guarded.ok:
            problem = f"guard: {guarded.error}"
        else:
            try:
                estimated = dry_run(client, guarded.sql)
            except Exception as e:
                problem = f"dry-run: {str(e)[:160]}"

        if problem:
            failures += 1
            print(f"✗ {trio['id']}: {problem}")
            if args.fix_status and trio.get("status") != "quarantined":
                trio["status"] = "quarantined"
                path.write_text(json.dumps(trio, indent=2, ensure_ascii=False) + "\n")
        else:
            print(f"✓ {trio['id']} ({trio['status']}, ~{estimated / 1e6:.1f} MB)")

    total = len(list(LAKE.glob("*.json")))
    print(f"\n{total - failures}/{total} valid")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
