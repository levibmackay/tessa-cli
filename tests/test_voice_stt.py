"""tests/test_voice_stt.py"""
import numpy as np

from lydia.voice.stt import Transcriber


class Seg:
    def __init__(self, text):
        self.text = text


class FakeWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.seen = None

    def transcribe(self, pcm, **kwargs):
        self.seen = pcm
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
