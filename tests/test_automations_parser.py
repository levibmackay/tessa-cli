import json

import pytest

from lydia.automations.parser import AutomationParseError, complete, parse_automation
from lydia.config.settings import LydiaConfig
from lydia.llm.types import ChatChunk

VALID = {
    "name": "morning-briefing",
    "description": "every morning at 8 check email",
    "enabled": True,
    "trigger": {"type": "schedule", "time": "08:00"},
    "steps": [
        {"kind": "connector", "tool": "check_email", "args": {"account": "personal"}},
        {"kind": "model", "instructions": "Summarize."},
    ],
    "notify": {"channel": "ntfy", "when": "always"},
}


class FakeClient:
    """Yields one canned reply per chat_stream call, recording each call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield ChatChunk(content=self.replies.pop(0), done=True)


def test_complete_concatenates_content():
    client = FakeClient(["hello"])
    assert complete(client, "m", LydiaConfig(), []) == "hello"
    assert client.calls[0]["keep_alive"] == LydiaConfig().keep_alive


def test_parse_valid_json_first_try():
    client = FakeClient([json.dumps(VALID)])
    auto = parse_automation("whatever", client, "m", LydiaConfig())
    assert auto.name == "morning-briefing"
    assert len(client.calls) == 1


def test_parse_strips_code_fences():
    client = FakeClient(["```json\n" + json.dumps(VALID) + "\n```"])
    assert parse_automation("x", client, "m", LydiaConfig()).name == "morning-briefing"


def test_parse_retries_once_with_error_feedback():
    bad = dict(VALID, trigger={"type": "schedule"})  # missing time
    client = FakeClient([json.dumps(bad), json.dumps(VALID)])
    auto = parse_automation("x", client, "m", LydiaConfig())
    assert auto.name == "morning-briefing"
    assert len(client.calls) == 2
    retry_user_msg = client.calls[1]["messages"][-1].content
    assert "HH:MM" in retry_user_msg  # the validation error was fed back


def test_parse_fails_after_retry():
    client = FakeClient(["not json at all", "still not json"])
    with pytest.raises(AutomationParseError):
        parse_automation("x", client, "m", LydiaConfig())
