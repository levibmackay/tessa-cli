import pytest

from lydia.automations import store
from lydia.automations.model import Automation, AutomationError, Notify, Step, Trigger


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AUTOMATIONS_DIR", tmp_path)


def _auto(name="test-auto") -> Automation:
    return Automation(
        name=name, description="d",
        trigger=Trigger(type="interval", minutes=30),
        steps=[Step(kind="connector", tool="check_news")],
        notify=Notify(),
    )


def test_save_load_round_trip():
    store.save_automation(_auto())
    assert store.load_automation("test-auto") == _auto()


def test_save_rejects_invalid():
    bad = _auto()
    bad.steps = []
    with pytest.raises(AutomationError):
        store.save_automation(bad)


def test_list_sorted_and_skips_garbage(tmp_path):
    store.save_automation(_auto("bbb"))
    store.save_automation(_auto("aaa"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    names = [a.name for a in store.list_automations()]
    assert names == ["aaa", "bbb"]


def test_delete():
    store.save_automation(_auto())
    assert store.delete_automation("test-auto") is True
    assert store.delete_automation("test-auto") is False
    with pytest.raises(AutomationError):
        store.load_automation("test-auto")


def test_state_round_trip():
    assert store.load_state() == {}
    store.save_state({"x": {"last_run": "2026-07-17T08:00:00"}})
    assert store.load_state()["x"]["last_run"] == "2026-07-17T08:00:00"


def test_runs_capped():
    for i in range(store.MAX_RUNS + 10):
        store.append_run({"name": "x", "ok": True, "i": i})
    runs = store.load_runs()
    assert len(runs) == store.MAX_RUNS
    assert runs[-1]["i"] == store.MAX_RUNS + 9  # newest kept


def test_lock_blocks_then_goes_stale():
    assert store.try_acquire_lock(now_fn=lambda: 1000.0) is True
    assert store.try_acquire_lock(now_fn=lambda: 1000.0) is False
    # a lock older than LOCK_STALE_SECONDS is broken and re-acquired
    assert store.try_acquire_lock(now_fn=lambda: 1000.0 + store.LOCK_STALE_SECONDS + 1) is True
    store.release_lock()
    assert store.try_acquire_lock(now_fn=lambda: 2000.0) is True
