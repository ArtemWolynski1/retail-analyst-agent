import hashlib
from pathlib import Path

from agent.runtime import Trio

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_instructions() -> str:
    """The single adapter seam for prompt storage: a file today, a prompt
    management service (Langfuse / LangSmith hub) would replace only this
    function. Read per call so instruction edits hot-reload like personas do."""
    return (PROMPTS_DIR / "analyst-agent-instructions.prompt").read_text().strip()


def prompt_version(instructions: str) -> str:
    """Content hash stamped into traces so evals and incidents can be
    correlated with the exact prompt that produced them."""
    return hashlib.sha256(instructions.encode()).hexdigest()[:12]


def build_system_prompt(
    schema_summary: str,
    examples: list[Trio],
    persona_text: str | None = None,
    preference_notes: tuple[str, ...] = (),
    today: str = "",
    instructions: str | None = None,
) -> str:
    """Pure assembly — every input is injectable, which is what makes the same
    function servable to production, unit tests, and eval fixtures.

    One structural language throughout: XML tags delimit every section, code
    fences hold SQL. Variable content lives strictly inside its tags, so
    dynamic text can never masquerade as prompt structure — the instructions'
    <untrusted_content_rule> refers to these tags by name.
    """
    parts = [instructions if instructions is not None else load_instructions()]
    if today:
        parts.append(f"<current_date>{today}</current_date>")
    parts.append(f"<dataset_schema>\n{schema_summary}\n</dataset_schema>")
    if examples:
        rendered = "\n\n".join(
            f"<example>\nQuestion: {t.question}\nSQL:\n```sql\n{t.sql}\n```\n"
            f"Analyst notes: {t.analyst_notes}\n</example>"
            for t in examples
        )
        parts.append(f"<analyst_examples>\n{rendered}\n</analyst_examples>")
    if persona_text:
        parts.append(f"<persona_style>\n{persona_text}\n</persona_style>")
    if preference_notes:
        notes = "\n".join(f"- {n}" for n in preference_notes)
        parts.append(f"<user_preferences>\n{notes}\n</user_preferences>")
    return "\n\n".join(parts)
