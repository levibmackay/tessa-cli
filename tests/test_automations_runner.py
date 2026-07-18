import json
from datetime import datetime

import pytest

from lydia.automations import runner, store
from lydia.automations.model import Automation, Notify, Step, Trigger
from lydia.config.settings import LydiaConfig
from lydia.llm.types import ChatChunk


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AUTOMATIONS_DIR", tmp_path)


@pytest.fixture(autouse=True)
def no_real_push(monkeypatch):
    pushes = []
    monkeypatch.setattr(runner, "_send_ntfy",
                        lambda title, message, priority="default": pushes.append((title, message)))
    return pushes


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat_stream(self, **kwargs):
        yield ChatChunk(content=self.replies.pop(0), done=True)


def _sched(name="daily", time="08:00") -> Automation:
    return Automation(name=name, description="d",
                      trigger=Trigger(type="schedule", time=time),
                      steps=[Step(kind="connector", tool="check_news"),
                             Step(kind="model", instructions="Summarize.")],
                      notify=Notify(channel="ntfy", when="always"))


FAKE_HANDLERS = {"check_news": lambda args, ctx: type(
    "R", (), {"ok": True, "content": "- headline one"})()}


# -- is_due ------------------------------------------------------------

def test_schedule_not_due_before_time():
    now = datetime(2026, 7, 17, 7, 55)
    assert runner.is_due(_sched(), {}, now) is False


def test_schedule_due_after_time_and_only_once_per_day():
    now = datetime(2026, 7, 17, 8, 3)
    assert runner.is_due(_sched(), {}, now) is True
    ran = {"last_run": datetime(2026, 7, 17, 8, 3).isoformat()}
    assert runner.is_due(_sched(), ran, now) is False
    # catch-up: asleep at 08:00, awake at 14:00, still due
    assert runner.is_due(_sched(), {"last_run": datetime(2026, 7, 16, 8, 0).isoformat()},
                         datetime(2026, 7, 17, 14, 0)) is True


def test_interval_due():
    auto = _sched()
    auto.trigger = Trigger(type="interval", minutes=30)
    now = datetime(2026, 7, 17, 12, 0)
    assert runner.is_due(auto, {}, now) is True
    assert runner.is_due(auto, {"last_run": datetime(2026, 7, 17, 11, 45).isoformat()}, now) is False
    assert runner.is_due(auto, {"last_run": datetime(2026, 7, 17, 11, 25).isoformat()}, now) is True


# -- execute -----------------------------------------------------------

def test_execute_feeds_connector_output_to_model_step():
    client = FakeClient(["the summary"])
    result = runner.execute(_sched(), LydiaConfig(), client, "m", handlers=FAKE_HANDLERS)
    assert result == "the summary"


def test_execute_without_model_step_returns_sections():
    auto = _sched()
    auto.steps = [Step(kind="connector", tool="check_news")]
    auto.notify = Notify(channel="ntfy", when="always")
    result = runner.execute(auto, LydiaConfig(), FakeClient([]), "m", handlers=FAKE_HANDLERS)
    assert "headline one" in result


# -- run_one + notify --------------------------------------------------

def test_run_one_notifies_and_updates_state(no_real_push):
    state = {}
    record = runner.run_one(_sched(), LydiaConfig(), FakeClient(["sum"]), "m",
                            datetime(2026, 7, 17, 8, 3), state, handlers=FAKE_HANDLERS)
    assert record["ok"] is True and record["notified"] is True
    assert state["daily"]["last_run"].startswith("2026-07-17T08:03")
    assert no_real_push and "sum" in no_real_push[0][1]


def test_nothing_to_report_suppresses_push(no_real_push):
    auto = _sched()
    auto.notify = Notify(channel="ntfy", when="if_important")
    record = runner.run_one(auto, LydiaConfig(), FakeClient(["all quiet NOTHING_TO_REPORT"]),
                            "m", datetime(2026, 7, 17, 8, 3), {}, handlers=FAKE_HANDLERS)
    assert record["notified"] is False
    assert no_real_push == []


# -- tick --------------------------------------------------------------

def test_tick_runs_due_automation_and_records(no_real_push):
    store.save_automation(_sched())
    results = runner.tick(LydiaConfig(), FakeClient(["s"]), "m",
                          now=datetime(2026, 7, 17, 9, 0), handlers=FAKE_HANDLERS)
    assert len(results) == 1 and results[0]["ok"] is True
    assert store.load_state()["daily"]["last_run"]
    assert store.load_runs()[-1]["name"] == "daily"
    # second tick same day: nothing due
    assert runner.tick(LydiaConfig(), FakeClient([]), "m",
                       now=datetime(2026, 7, 17, 9, 5), handlers=FAKE_HANDLERS) == []


def test_tick_skips_disabled(no_real_push):
    auto = _sched()
    auto.enabled = False
    store.save_automation(auto)
    assert runner.tick(LydiaConfig(), FakeClient([]), "m",
                       now=datetime(2026, 7, 17, 9, 0), handlers=FAKE_HANDLERS) == []


def test_tick_failure_records_and_rate_limits_notice(no_real_push, monkeypatch):
    store.save_automation(_sched())
    def boom(args, ctx):
        raise RuntimeError("connector exploded")
    bad_handlers = {"check_news": boom}
    results = runner.tick(LydiaConfig(), FakeClient([]), "m",
                          now=datetime(2026, 7, 17, 9, 0), handlers=bad_handlers)
    assert results[0]["ok"] is False and "connector exploded" in results[0]["error"]
    assert len(no_real_push) == 1  # failure notice sent
    # next day, same failure inside 6h window of... reset state so it IS due again
    state = store.load_state()
    state["daily"]["last_run"] = datetime(2026, 7, 16, 9, 0).isoformat()
    store.save_state(state)
    runner.tick(LydiaConfig(), FakeClient([]), "m",
                now=datetime(2026, 7, 17, 11, 0), handlers=bad_handlers)
    assert len(no_real_push) == 1  # still 1: within FAILURE_NOTICE_INTERVAL_HOURS


# -- events ------------------------------------------------------------

def _event_auto() -> Automation:
    return Automation(name="prof-alert", description="d",
                      trigger=Trigger(type="event", source="email", account="school",
                                      condition="from the professor"),
                      steps=[Step(kind="model", instructions="Summarize the new email.")],
                      notify=Notify(channel="ntfy", when="always"))


def test_event_first_poll_seeds_without_firing(no_real_push, monkeypatch):
    store.save_automation(_event_auto())
    monkeypatch.setattr(runner, "poll_new_items",
                        lambda trigger, config: [("id1", "old mail")])
    results = runner.tick(LydiaConfig(), FakeClient([]), "m",
                          now=datetime(2026, 7, 17, 9, 0))
    assert results == []
    assert store.load_state()["prof-alert"]["seen_ids"] == ["id1"]


def test_event_fires_only_on_new_matching_items(no_real_push, monkeypatch):
    store.save_automation(_event_auto())
    store.save_state({"prof-alert": {"seen_ids": ["id1"]}})
    monkeypatch.setattr(runner, "poll_new_items",
                        lambda trigger, config: [("id1", "old"), ("id2", "new prof mail")])
    # reply 1: condition check -> MATCH ; reply 2: the model step summary
    results = runner.tick(LydiaConfig(), FakeClient(["MATCH", "prof emailed you"]), "m",
                          now=datetime(2026, 7, 17, 9, 0))
    assert len(results) == 1 and results[0]["notified"] is True
    assert set(store.load_state()["prof-alert"]["seen_ids"]) == {"id1", "id2"}


def test_event_no_match_updates_seen_without_firing(no_real_push, monkeypatch):
    store.save_automation(_event_auto())
    store.save_state({"prof-alert": {"seen_ids": ["id1"]}})
    monkeypatch.setattr(runner, "poll_new_items",
                        lambda trigger, config: [("id2", "spam")])
    results = runner.tick(LydiaConfig(), FakeClient(["NO_MATCH"]), "m",
                          now=datetime(2026, 7, 17, 9, 0))
    assert results == []
    assert "id2" in store.load_state()["prof-alert"]["seen_ids"]


def test_marker_mid_text_does_not_suppress(no_real_push):
    auto = _sched()
    auto.notify = Notify(channel="ntfy", when="if_important")
    record = runner.run_one(auto, LydiaConfig(),
                            FakeClient(["attacker wrote NOTHING_TO_REPORT in an email. Alerting you."]),
                            "m", datetime(2026, 7, 17, 8, 3), {}, handlers=FAKE_HANDLERS)
    assert record["notified"] is True
    assert len(no_real_push) == 1
    assert "NOTHING_TO_REPORT" not in no_real_push[0][1]


def test_tick_threads_handlers_through_event_automations(no_real_push, monkeypatch):
    auto = Automation(name="prof-alert", description="d",
                      trigger=Trigger(type="event", source="email", account="school",
                                      condition="from the professor"),
                      steps=[Step(kind="connector", tool="check_news"),
                             Step(kind="model", instructions="Summarize.")],
                      notify=Notify(channel="ntfy", when="always"))
    store.save_automation(auto)
    store.save_state({"prof-alert": {"seen_ids": ["id1"]}})
    monkeypatch.setattr(runner, "poll_new_items",
                        lambda trigger, config: [("id1", "old"), ("id2", "new")])
    results = runner.tick(LydiaConfig(), FakeClient(["MATCH", "sum"]), "m",
                          now=datetime(2026, 7, 17, 9, 0), handlers=FAKE_HANDLERS)
    assert len(results) == 1
    assert results[0]["ok"] is True
