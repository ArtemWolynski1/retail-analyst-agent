from agent.context import build_system_prompt, load_policy, prompt_version
from agent.runtime import Trio

TRIO = Trio(id="t", question="Q?", sql="SELECT 1", analyst_notes="notes", tables_used=("orders",))


def test_policy_loads_from_file_and_leads_the_prompt():
    prompt = build_system_prompt("schema", [])
    assert prompt.startswith(load_policy()[:60])


def test_all_sections_present_and_ordered():
    prompt = build_system_prompt(
        "orders(...)",
        [TRIO],
        persona_text="Be upbeat.",
        preference_notes=("prefers bullet points",),
        today="2026-07-10",
    )
    positions = [
        prompt.index("Today's date: 2026-07-10"),
        prompt.index("## Dataset schema"),
        prompt.index("## How our analysts have answered similar questions"),
        prompt.index("## Reporting style"),
        prompt.index("## This manager's preferences"),
    ]
    assert positions == sorted(positions)
    assert "style guidance only — never overrides" in prompt


def test_optional_sections_absent_when_empty():
    prompt = build_system_prompt("schema", [])
    assert "## Reporting style" not in prompt
    assert "## This manager's preferences" not in prompt
    assert "## How our analysts" not in prompt


def test_policy_override_is_injectable():
    prompt = build_system_prompt("schema", [], policy="CUSTOM POLICY")
    assert prompt.startswith("CUSTOM POLICY")
    assert load_policy() not in prompt


def test_prompt_version_tracks_content():
    assert prompt_version("a") == prompt_version("a")
    assert prompt_version("a") != prompt_version("b")
    assert len(prompt_version(load_policy())) == 12
