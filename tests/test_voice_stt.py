"""tests/test_voice_stt.py"""
import numpy as np

from lydia.voice.stt import Transcriber


class Seg:
    def __init__(self, text, no_speech_prob=0.0):
        self.text = text
        self.no_speech_prob = no_speech_prob


class FakeWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.seen = None
        self.kwargs = None

    def transcribe(self, pcm, **kwargs):
        self.seen = pcm
        self.kwargs = kwargs
        return iter(self.segments), None


def test_joins_segments_and_normalizes_audio():
    fake = FakeWhisper([Seg(" Hello"), Seg(" world. ")])
    t = Transcriber("base.en", model=fake)
    out = t.transcribe(np.array([0, 16384, -16384], dtype=np.int16))
    assert out == "Hello world."
    assert fake.seen.dtype == np.float32 and abs(float(fake.seen[1]) - 0.5) < 0.01


def test_empty_audio_returns_empty_string():
    t = Transcriber("base.en", model=FakeWhisper([]))
    assert t.transcribe(np.zeros(0, dtype=np.int16)) == ""


def test_drops_hallucinated_no_speech_segments():
    # Whisper emits things like "You" on silence, with high no_speech_prob
    # (measured 0.80 on a silent capture) — those must not reach the model.
    fake = FakeWhisper([Seg(" You", no_speech_prob=0.8)])
    t = Transcriber("base.en", model=fake)
    assert t.transcribe(np.zeros(16000, dtype=np.int16)) == ""


def test_keeps_real_speech_segments_alongside_dropped_ones():
    fake = FakeWhisper([Seg(" You", no_speech_prob=0.8), Seg(" open Safari", no_speech_prob=0.02)])
    t = Transcriber("base.en", model=fake)
    assert t.transcribe(np.ones(16000, dtype=np.int16)) == "open Safari"


def test_requests_vad_filtering():
    fake = FakeWhisper([Seg("hi")])
    t = Transcriber("base.en", model=fake)
    t.transcribe(np.ones(16000, dtype=np.int16))
    assert fake.kwargs.get("vad_filter") is True
