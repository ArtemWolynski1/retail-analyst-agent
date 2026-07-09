from datetime import date

from agent.store import Store


def make_store(tmp_path) -> Store:
    return Store(str(tmp_path / "test.sqlite"))


def test_ownership_isolation(tmp_path):
    store = make_store(tmp_path)
    report_id = store.save_report("alice", "Revenue", "how much?", "SELECT 1", "big numbers")

    assert store.list_reports("bob") == []
    assert store.get_reports_by_ids("bob", [report_id]) == []
    assert store.delete_by_ids("bob", [report_id]) == 0

    assert len(store.list_reports("alice")) == 1
    assert store.delete_by_ids("alice", [report_id]) == 1
    assert store.list_reports("alice") == []


def test_delete_only_matched_ids(tmp_path):
    store = make_store(tmp_path)
    keep = store.save_report("alice", "Keep", "q", "s", "r")
    drop = store.save_report("alice", "Drop", "q", "s", "r")
    assert store.delete_by_ids("alice", [drop, "nonexistent"]) == 1
    remaining = store.list_reports("alice")
    assert [r["id"] for r in remaining] == [keep]


def test_search_filter(tmp_path):
    store = make_store(tmp_path)
    store.save_report("a", "June revenue", "revenue?", "SELECT", "report about Client X launch")
    store.save_report("a", "Margins", "margins?", "SELECT", "unrelated")
    assert len(store.list_reports("a", search="Client X")) == 1
    assert len(store.list_reports("a", search="revenue")) == 1
    assert len(store.list_reports("a")) == 2


def test_created_on_filter(tmp_path):
    store = make_store(tmp_path)
    store.save_report("a", "T", "q", "s", "r")
    assert len(store.list_reports("a", created_on=date.today().isoformat())) == 1
    assert store.list_reports("a", created_on="1999-01-01") == []
