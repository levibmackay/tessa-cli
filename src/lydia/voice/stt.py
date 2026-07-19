"""src/lydia/voice/stt.py — faster-whisper transcription behind one seam."""

from __future__ import annotations

import numpy as np


class Transcriber:
    def __init__(self, model_name: str, model=None):
        self.model_name = model_name
        self._model = model

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # int8 keeps memory/CPU sane on the Air; downloads once to ~/.cache.
            self._model = WhisperModel(self.model_name, compute_type="int8")
        return self._model

    # Whisper hallucinates on non-speech ("You", "Thank you."); measured
    # no_speech_prob was 0.80 on a silent capture vs ~0 for real speech.
    NO_SPEECH_MAX = 0.6

    def transcribe(self, pcm: np.ndarray) -> str:
        if pcm.size == 0:
            return ""
        audio = (pcm.astype(np.float32) / 32768.0)
        segments, _info = self._ensure_model().transcribe(
            audio, language="en", vad_filter=True)
        parts = (seg.text.strip() for seg in segments
                 if getattr(seg, "no_speech_prob", 0.0) <= self.NO_SPEECH_MAX)
        return " ".join(p for p in parts if p).strip()
