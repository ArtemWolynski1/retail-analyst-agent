from datetime import date

from agent.store import Store
from agent.tools.reports import resolve_delete_targets


def make_store(tmp_path) -> Store:
    store = Store(str(tmp_path / "t.sqlite"))
    store.save_report("alice", "Client X churn", "why churn?", "SELECT", "churn analysis for Client X")
    store.save_report("alice", "June revenue", "revenue?", "SELECT", "monthly numbers")
    return store


def test_no_criteria_means_none(tmp_path):
    assert resolve_delete_targets(make_store(tmp_path), "alice", None, "", "") is None


def test_search_filter_resolves(tmp_path):
    matched = resolve_delete_targets(make_store(tmp_path), "alice", None, "Client X", "")
    assert [r["title"] for r in matched] == ["Client X churn"]


def test_created_on_resolves_todays_reports(tmp_path):
    matched = resolve_delete_targets(make_store(tmp_path), "alice", None, "", date.today().isoformat())
    assert len(matched) == 2


def test_explicit_ids_win_over_filters(tmp_path):
    store = make_store(tmp_path)
    target = store.list_reports("alice", search="June")[0]["id"]
    matched = resolve_delete_targets(store, "alice", [target], "Client X", "")
    assert [r["id"] for r in matched] == [target]


def test_filters_respect_ownership(tmp_path):
    matched = resolve_delete_targets(make_store(tmp_path), "bob", None, "Client X", "")
    assert matched == []
