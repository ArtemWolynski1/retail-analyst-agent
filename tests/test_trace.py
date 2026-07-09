import json

from agent.trace import Trace


def test_events_written_as_json_lines(tmp_path):
    trace = Trace(str(tmp_path / "logs"))
    trace.event("turn_start", turn_id="abc123", question="revenue?")
    trace.event("sql_attempt", turn_id="abc123", attempt=1, outcome="ok", rows=6)

    lines = trace.path.read_text().strip().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["event"] == "turn_start"
    assert first["turn_id"] == "abc123"
    assert "timestamp" in first
    assert second["outcome"] == "ok"
    assert second["rows"] == 6


def test_null_trace_is_silent_noop():
    trace = Trace(None)
    trace.event("anything", foo="bar")
    assert trace.path is None
