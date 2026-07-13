from agent.context import build_system_prompt, load_instructions, prompt_version
from agent.runtime import Trio

TRIO = Trio(id="t", question="Q?", sql="SELECT 1", analyst_notes="notes", tables_used=("orders",))


def test_instructions_load_from_file_and_lead_the_prompt():
    prompt = build_system_prompt("schema", [])
    assert prompt.startswith(load_instructions()[:60])
    assert prompt.startswith("<role>")


def test_all_sections_present_and_ordered():
    prompt = build_system_prompt(
        "orders(...)",
        [TRIO],
        persona_text="Be upbeat.",
        preference_notes=("prefers bullet points",),
        today="2026-07-10",
    )
    # closing tags only exist where sections actually render — the
    # instructions body legitimately *mentions* opening tag names
    positions = [
        prompt.index("</current_date>"),
        prompt.index("</dataset_schema>"),
        prompt.index("</analyst_examples>"),
        prompt.index("</persona_style>"),
        prompt.index("</user_preferences>"),
    ]
    assert positions == sorted(positions)


def test_variable_content_is_tag_delimited_and_sql_fenced():
    prompt = build_system_prompt(
        "schema",
        [TRIO],
        persona_text="Be upbeat.",
        preference_notes=("prefers bullet points",),
    )
    assert "<persona_style>\nBe upbeat.\n</persona_style>" in prompt
    assert "<user_preferences>\n- prefers bullet points\n</user_preferences>" in prompt
    assert "```sql\nSELECT 1\n```" in prompt


def test_optional_sections_absent_when_empty():
    prompt = build_system_prompt("schema", [])
    assert "</persona_style>" not in prompt
    assert "</user_preferences>" not in prompt
    assert "</analyst_examples>" not in prompt


def test_instructions_override_is_injectable():
    prompt = build_system_prompt("schema", [], instructions="CUSTOM INSTRUCTIONS")
    assert prompt.startswith("CUSTOM INSTRUCTIONS")
    assert load_instructions() not in prompt


def test_prompt_version_tracks_content():
    assert prompt_version("a") == prompt_version("a")
    assert prompt_version("a") != prompt_version("b")
    assert len(prompt_version(load_instructions())) == 12
