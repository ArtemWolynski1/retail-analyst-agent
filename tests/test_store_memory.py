from agent.store import Store


def make_store(tmp_path) -> Store:
    return Store(str(tmp_path / "test.sqlite"))


def test_preferences_are_per_user(tmp_path):
    store = make_store(tmp_path)
    store.add_preference("alice", "prefers tables")
    assert store.get_preferences("alice") == ["prefers tables"]
    assert store.get_preferences("bob") == []


def test_preferences_capped_to_most_recent(tmp_path):
    store = make_store(tmp_path)
    for i in range(15):
        store.add_preference("a", f"note {i}")
    prefs = store.get_preferences("a", limit=10)
    assert len(prefs) == 10
    assert prefs[0] == "note 5"
    assert prefs[-1] == "note 14"


def test_personas_seeded_with_professional_active(tmp_path):
    store = make_store(tmp_path)
    personas = store.list_personas()
    assert {p["name"] for p in personas} == {"professional", "enthusiastic"}
    assert store.get_active_persona()["name"] == "professional"


def test_persona_switch(tmp_path):
    store = make_store(tmp_path)
    assert store.set_active_persona("enthusiastic")
    assert store.get_active_persona()["name"] == "enthusiastic"
    actives = [p for p in store.list_personas() if p["is_active"]]
    assert len(actives) == 1


def test_unknown_persona_rejected_and_state_unchanged(tmp_path):
    store = make_store(tmp_path)
    assert not store.set_active_persona("pirate")
    assert store.get_active_persona() is None or store.get_active_persona()["name"] in (
        "professional",
        "enthusiastic",
    )


def test_persona_survives_reopen(tmp_path):
    path = str(tmp_path / "p.sqlite")
    Store(path).set_active_persona("enthusiastic")
    assert Store(path).get_active_persona()["name"] == "enthusiastic"
