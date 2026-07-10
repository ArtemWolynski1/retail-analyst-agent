"""promptfoo prompt function.

Renders the production system prompt through the exact same assembly code the
agent uses (agent.context.build_system_prompt) — never a copy of the prompt —
so what gets evaluated is what ships. Schema comes from a checked-in snapshot
so rendering needs no BigQuery access.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.context import build_system_prompt  # noqa: E402
from agent.runtime import load_examples  # noqa: E402

SCHEMA_SNAPSHOT = (ROOT / "data" / "schema_snapshot.txt").read_text()
EXAMPLES = load_examples(ROOT / "data" / "golden_examples.json")


def analyst_prompt(context: dict) -> list[dict]:
    variables = context.get("vars", {})
    system = build_system_prompt(
        SCHEMA_SNAPSHOT,
        EXAMPLES,
        persona_text=variables.get("persona"),
        preference_notes=tuple(variables.get("preferences", ())),
        today=variables.get("today", "2026-07-10"),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": variables["question"]},
    ]
