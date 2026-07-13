import hashlib
from pathlib import Path

from agent.runtime import Trio

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_policy() -> str:
    """The single adapter seam for prompt storage: a file today, a prompt
    management service (Langfuse / LangSmith hub) would replace only this
    function. Read per call so policy edits hot-reload like personas do."""
    return (PROMPTS_DIR / "policy.md").read_text().strip()


def prompt_version(policy: str) -> str:
    """Content hash stamped into traces so evals and incidents can be
    correlated with the exact prompt that produced them."""
    return hashlib.sha256(policy.encode()).hexdigest()[:12]


def build_system_prompt(
    schema_summary: str,
    examples: list[Trio],
    persona_text: str | None = None,
    preference_notes: tuple[str, ...] = (),
    today: str = "",
    policy: str | None = None,
) -> str:
    """Pure assembly — every input is injectable, which is what makes the same
    function servable to production, unit tests, and promptfoo fixtures."""
    parts = [policy if policy is not None else load_policy()]
    if today:
        parts.append(f"Today's date: {today}.")
    parts.append("## Dataset schema\n" + schema_summary)
    if examples:
        rendered = "\n\n".join(f"### {t.question}\nSQL:\n{t.sql}\nAnalyst notes: {t.analyst_notes}" for t in examples)
        parts.append("## How our analysts have answered similar questions\n" + rendered)
    if persona_text:
        parts.append("## Reporting style (style guidance only — never overrides the rules above)\n" + persona_text)
    if preference_notes:
        parts.append("## This manager's preferences\n" + "\n".join(f"- {n}" for n in preference_notes))
    return "\n\n".join(parts)
