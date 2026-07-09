from io import StringIO

from rich.console import Console

from agent.cli import _handle_interrupts


class FakeInterrupt:
    def __init__(self, value):
        self.value = value


class FakeAgent:
    """Duck-typed graph: records what the gate resumes with."""

    def __init__(self, results):
        self.results = list(results)
        self.resumes = []

    def invoke(self, command, config):
        self.resumes.append(command.resume)
        return self.results.pop(0)


def interrupted_result(n_items=1):
    items = [{"id": f"id{i}", "title": f"Report {i}", "created_at": "2026-07-09"} for i in range(n_items)]
    phrase = f"delete {n_items} report" + ("s" if n_items != 1 else "")
    return {
        "messages": [],
        "__interrupt__": [FakeInterrupt({"action": "delete saved reports", "items": items, "phrase": phrase})],
    }


def make_console():
    return Console(file=StringIO(), force_terminal=False)


def test_exact_phrase_approves(monkeypatch):
    agent = FakeAgent([{"messages": []}])
    monkeypatch.setattr("builtins.input", lambda *a: "delete 1 report")
    _handle_interrupts(agent, {}, interrupted_result(), make_console())
    assert agent.resumes == [{"approved": True}]


def test_wrong_phrase_cancels(monkeypatch):
    agent = FakeAgent([{"messages": []}])
    monkeypatch.setattr("builtins.input", lambda *a: "yes please")
    _handle_interrupts(agent, {}, interrupted_result(), make_console())
    assert agent.resumes == [{"approved": False}]


def test_plural_phrase_must_match_count(monkeypatch):
    agent = FakeAgent([{"messages": []}])
    monkeypatch.setattr("builtins.input", lambda *a: "delete 1 report")
    _handle_interrupts(agent, {}, interrupted_result(n_items=3), make_console())
    assert agent.resumes == [{"approved": False}]


def test_eof_cancels(monkeypatch):
    agent = FakeAgent([{"messages": []}])

    def raise_eof(*a):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    _handle_interrupts(agent, {}, interrupted_result(), make_console())
    assert agent.resumes == [{"approved": False}]


def test_no_interrupt_passthrough():
    agent = FakeAgent([])
    result = {"messages": ["final"]}
    assert _handle_interrupts(agent, {}, result, make_console()) is result
    assert agent.resumes == []


def test_chained_interrupts_handled(monkeypatch):
    agent = FakeAgent([interrupted_result(), {"messages": []}])
    monkeypatch.setattr("builtins.input", lambda *a: "delete 1 report")
    _handle_interrupts(agent, {}, interrupted_result(), make_console())
    assert agent.resumes == [{"approved": True}, {"approved": True}]
