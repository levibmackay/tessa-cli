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
    speech_wait: float = 6.0,
    preroll_seconds: float = 0.4,
) -> np.ndarray:
    """Wait for speech (up to `speech_wait`), then collect until quiet.

    Silence only counts once speech has begun: a pause after the wake chime
    must not end the capture before the user says anything. If speech never
    starts, returns empty audio so the caller can miss-chime without running
    Whisper on silence (which hallucinates text). The last `preroll_seconds`
    before speech onset are kept so a soft first syllable isn't clipped.
    """
    preroll: list[np.ndarray] = []
    keep = max(1, int(preroll_seconds / frame_seconds))
    waited = 0.0
    while True:
        frame = read_frame()
        if _rms(frame) >= threshold:
            break
        preroll = (preroll + [frame])[-keep:]
        waited += frame_seconds
        if waited >= speech_wait:
            return np.zeros(0, dtype=np.int16)
    frames = [*preroll, frame]
    quiet = 0.0
    while (len(frames) - len(preroll)) * frame_seconds < max_seconds:
        frame = read_frame()
        frames.append(frame)
        quiet = 0.0 if _rms(frame) >= threshold else quiet + frame_seconds
        if quiet >= silence_after:
            break
    return np.concatenate(frames)


class Microphone:
    """Owns the input stream so the loop can flush stale audio. Real hardware.

    `say`/`afplay` block the loop while the stream keeps buffering — without a
    flush those frames get replayed into the wake detector afterwards,
    including Lydia's own voice.
    """

    def __init__(self):
        self._stream = None

    def _ensure(self):
        if self._stream is None:
            import sounddevice as sd

            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                          dtype="int16", blocksize=FRAME_SAMPLES)
            self._stream.start()
        return self._stream

    def frames(self):
        """Yield int16 mono FRAME_SAMPLES frames from the default mic."""
        while True:
            data, _overflowed = self._ensure().read(FRAME_SAMPLES)
            yield data[:, 0].copy()

    def flush(self) -> None:
        """Discard whatever audio accumulated while the loop wasn't reading."""
        stream = self._ensure()
        while stream.read_available >= FRAME_SAMPLES:
            stream.read(FRAME_SAMPLES)
