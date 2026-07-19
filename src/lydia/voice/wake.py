"""src/lydia/voice/wake.py — openWakeWord wrapper with one-shot activation."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def wake_label(name: str) -> str:
    """Human-readable wake phrase ("/…/hey_lydia.onnx" → "hey lydia")."""
    path = Path(name)
    stem = path.stem if path.suffix == ".onnx" else name
    return stem.replace("_", " ")


class WakeDetector:
    """True exactly once per wake-word activation.

    `model` is injectable for tests; the real openWakeWord model is built
    lazily so importing this module never downloads anything.

    `model_name` is either a pre-trained openWakeWord name ("hey_jarvis") or
    a path to a custom-trained .onnx model file ("~/.lydia/hey_lydia.onnx");
    openWakeWord keys predictions by the file's stem either way.
    """

    def __init__(self, model_name: str, model=None, threshold: float = 0.5):
        self.model_name = str(Path(model_name).expanduser())
        self._key = Path(model_name).stem
        self.threshold = threshold
        self._model = model
        self._armed = True

    def _ensure_model(self):
        if self._model is None:
            import openwakeword
            from openwakeword.model import Model

            # tflite-runtime doesn't exist for Python 3.14/Apple Silicon; the
            # ONNX runtime does. download_models is a no-op once cached.
            openwakeword.utils.download_models()
            self._model = Model(wakeword_models=[self.model_name],
                                inference_framework="onnx")
        return self._model

    def process(self, frame: np.ndarray) -> bool:
        score = self._ensure_model().predict(frame).get(self._key, 0.0)
        if score >= self.threshold:
            if self._armed:
                self._armed = False
                return True
            return False
        self._armed = True
        return False
