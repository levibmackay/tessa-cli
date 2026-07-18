"""tests/test_voice_audio.py"""
import numpy as np

from lydia.config.settings import LydiaConfig
from lydia.voice import audio


def _frames(seq):
    """read_frame() stub yielding int16 frames of given absolute amplitude."""
    frames = [np.full(audio.FRAME_SAMPLES, amp, dtype=np.int16) for amp in seq]
    it = iter(frames)
    return lambda: next(it)


def test_records_speech_then_stops_on_silence():
    # 3 loud frames, then plenty of silence: stops after `silence_after` quiet time
    read = _frames([3000, 3000, 3000] + [0] * 100)
    out = audio.record_until_silence(read, silence_after=0.16, frame_seconds=0.08)
    assert out.dtype == np.int16
    # 3 loud + 2 silent frames (0.16s / 0.08s) = 5 frames
    assert len(out) == 5 * audio.FRAME_SAMPLES


def test_hard_cap_max_seconds():
    read = _frames([3000] * 1000)  # never goes silent
    out = audio.record_until_silence(read, max_seconds=0.4, frame_seconds=0.08)
    assert len(out) == 5 * audio.FRAME_SAMPLES  # 0.4 / 0.08


def test_config_voice_defaults():
    cfg = LydiaConfig()
    assert cfg.voice_wake_word == "hey_jarvis"
    assert cfg.voice_stt_model == "base.en"
    assert cfg.voice_tts_voice is None
