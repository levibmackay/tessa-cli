import pytest

from lydia.automations.model import (
    ALLOWED_STEP_TOOLS, Automation, AutomationError, Notify, Step, Trigger,
    describe, validate,
)


def _valid_automation() -> Automation:
    return Automation(
        name="morning-briefing",
        description="every morning at 8 check email and canvas",
        trigger=Trigger(type="schedule", time="08:00"),
        steps=[
            Step(kind="connector", tool="check_email", args={"account": "personal"}),
            Step(kind="model", instructions="Summarize into a short briefing."),
        ],
        notify=Notify(channel="ntfy", when="always"),
    )


def test_round_trips_through_dict():
    auto = _valid_automation()
    again = Automation.from_dict(auto.to_dict())
    assert again == auto


def test_from_dict_rejects_malformed():
    with pytest.raises(AutomationError):
        Automation.from_dict({"name": "x"})  # missing trigger/steps


def test_valid_automation_has_no_errors():
    assert validate(_valid_automation()) == []


def test_validate_rejects_bad_name():
    auto = _valid_automation()
    auto.name = "Bad Name!"
    assert any("name" in e for e in validate(auto))


def test_validate_rejects_bad_schedule_time():
    auto = _valid_automation()
    auto.trigger = Trigger(type="schedule", time="25:99")
    assert any("time" in e for e in validate(auto))


def test_validate_rejects_unknown_step_tool():
    auto = _valid_automation()
    auto.steps[0] = Step(kind="connector", tool="delete_file")
    assert any("delete_file" in e for e in validate(auto))


def test_validate_rejects_if_important_without_model_step():
    auto = _valid_automation()
    auto.steps = [Step(kind="connector", tool="check_news")]
    auto.notify = Notify(channel="ntfy", when="if_important")
    assert any("if_important" in e for e in validate(auto))


def test_validate_event_trigger_requirements():
    auto = _valid_automation()
    auto.trigger = Trigger(type="event", source="email", account="school",
                           condition="from my professor")
    assert validate(auto) == []
    auto.trigger = Trigger(type="event", source="email")  # no account/condition
    assert validate(auto) != []


def test_describe_mentions_trigger_and_notify():
    text = describe(_valid_automation())
    assert "08:00" in text and "phone" in text.lower()
