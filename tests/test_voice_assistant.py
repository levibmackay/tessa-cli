"""tests/test_voice_assistant.py"""
import itertools

import numpy as np
import pytest

from lydia.config.settings import LydiaConfig
from lydia.llm.client import OllamaError
from lydia.llm.types import ChatChunk
from lydia.voice import assistant

FRAME = np.full(1280, 3000, dtype=np.int16)
SILENT = np.zeros(1280, dtype=np.int16)


class OneShotWake:
    """Fires on the first frame only."""

    def __init__(self):
        self.fired = False

    def process(self, frame):
        if not self.fired:
            self.fired = True
            return True
        return False


class FakeTranscriber:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm):
        return self.text


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat_stream(self, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        yield ChatChunk(content=reply, done=True)


def _run(client, transcriber_text, spoken, chimes):
    frames = itertools.chain([FRAME], itertools.repeat(SILENT))
    assistant.run_loop(
        LydiaConfig(), client, "m",
        frames=frames, wake=OneShotWake(),
        transcriber=FakeTranscriber(transcriber_text),
        speak_fn=lambda text: spoken.append(text),
        chime_fn=lambda kind: chimes.append(kind),
        max_turns=1,
    )


def test_wake_transcribe_answer_speak():
    spoken, chimes = [], []
    _run(FakeClient(["It is sunny."]), "what's the weather", spoken, chimes)
    assert chimes == ["wake"]
    assert spoken == ["It is sunny."]


def test_empty_transcription_chimes_miss_and_skips_model():
    spoken, chimes = [], []
    _run(FakeClient([]), "   ", spoken, chimes)  # client never called: no replies needed
    assert chimes == ["wake", "miss"]
    assert spoken == []


def test_ollama_down_speaks_apology_and_survives():
    spoken, chimes = [], []
    _run(FakeClient([OllamaError("connection refused")]), "hello", spoken, chimes)
    assert any("reach my brain" in s for s in spoken)


def test_voice_registry_is_safe_tools_only():
    names = {spec.name for spec in assistant.voice_registry()}
    assert names == assistant.VOICE_TOOLS
    assert "write_file" not in names and "run_command" not in names


def test_voice_registry_includes_new_tools():
    names = {spec.name for spec in assistant.voice_registry()}
    for expected in ("check_weather", "check_calendar", "open_app", "find_files", "read_file"):
        assert expected in names
    assert "write_file" not in names and "run_command" not in names


class AlwaysWake:
    def process(self, frame):
        return True


def _loop(monkeypatch, client, transcriber, events=None, max_turns=1, now_fn=None, wake=None):
    monkeypatch.setattr(assistant.audio, "record_until_silence", lambda rf, **kw: FRAME)
    seen = []
    real = assistant.run_agent_turn

    def spy(**kw):
        seen.append([(m.role, m.content) for m in kw["messages"]])
        return real(**kw)

    monkeypatch.setattr(assistant, "run_agent_turn", spy)
    events = events if events is not None else []
    kwargs = {"now_fn": now_fn} if now_fn else {}
    assistant.run_loop(
        LydiaConfig(), client, "m",
        frames=itertools.repeat(SILENT), wake=wake or AlwaysWake(),
        transcriber=transcriber,
        speak_fn=lambda t: events.append("speak"),
        chime_fn=lambda k: events.append(k),
        flush_fn=lambda: events.append("flush"),
        max_turns=max_turns, **kwargs,
    )
    return seen, events


class SeqTranscriber:
    def __init__(self, texts):
        self.texts = iter(texts)

    def transcribe(self, pcm):
        return next(self.texts)


def test_flush_after_wake_chime_and_after_speech(monkeypatch):
    _, events = _loop(monkeypatch, FakeClient(["Hi."]), FakeTranscriber("hello"))
    assert events == ["wake", "flush", "speak", "flush"]


def test_flush_after_miss_chime(monkeypatch):
    _, events = _loop(monkeypatch, FakeClient([]), FakeTranscriber("  "))
    assert events == ["wake", "flush", "miss", "flush"]


def test_history_carries_between_turns(monkeypatch):
    seen, _ = _loop(monkeypatch, FakeClient(["Sunny.", "Rainy."]),
                    SeqTranscriber(["weather today", "and tomorrow"]), max_turns=2)
    assert seen[1] == [("user", "weather today"), ("assistant", "Sunny."),
                       ("user", "and tomorrow")]


def test_history_resets_after_long_gap(monkeypatch):
    clock = iter([0.0, 1000.0])  # second turn 1000s later > 300s ttl
    seen, _ = _loop(monkeypatch, FakeClient(["Sunny.", "Rainy."]),
                    SeqTranscriber(["weather today", "and tomorrow"]),
                    max_turns=2, now_fn=lambda: next(clock))
    assert seen[1] == [("user", "and tomorrow")]


@pytest.fixture
def no_real_push(monkeypatch):
    """Prevent actual push notification setup."""
    monkeypatch.setenv("NTFY_TOPIC", "")


def test_voice_turn_disables_thinking(no_real_push, monkeypatch):
    seen = {}
    real = assistant.run_agent_turn
    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(assistant, "run_agent_turn", spy)
    spoken, chimes = [], []
    _run(FakeClient(["ok"]), "hello", spoken, chimes)
    assert seen["think"] is False
