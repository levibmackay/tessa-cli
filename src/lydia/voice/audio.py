"""src/lydia/voice/audio.py — microphone frames and silence-bounded recording.

`record_until_silence` is pure logic over an injected `read_frame` callable so
tests never open a device; `mic_frames` is the one real-hardware function and
is exercised only by the manual checklist.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms — the frame size openWakeWord expects


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def record_until_silence(
    read_frame: Callable[[], np.ndarray],
    *,
    silence_after: float = 1.2,
    max_seconds: float = 15.0,
    frame_seconds: float = 0.08,
    threshold: float = 500.0,
) -> np.ndarray:
    """Collect frames until `silence_after` seconds of quiet (or the hard cap)."""
    frames: list[np.ndarray] = []
    quiet = 0.0
    while len(frames) * frame_seconds < max_seconds:
        frame = read_frame()
        frames.append(frame)
        quiet = 0.0 if _rms(frame) >= threshold else quiet + frame_seconds
        if quiet >= silence_after:
            break
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)


def mic_frames():
    """Yield int16 mono FRAME_SAMPLES frames from the default mic. Real hardware."""
    import sounddevice as sd

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=FRAME_SAMPLES) as stream:
        while True:
            data, _overflowed = stream.read(FRAME_SAMPLES)
            yield data[:, 0].copy()
