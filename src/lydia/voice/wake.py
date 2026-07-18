"""src/lydia/voice/wake.py — openWakeWord wrapper with one-shot activation."""

from __future__ import annotations

import numpy as np


class WakeDetector:
    """True exactly once per wake-word activation.

    `model` is injectable for tests; the real openWakeWord model is built
    lazily so importing this module never downloads anything.
    """

    def __init__(self, model_name: str, model=None, threshold: float = 0.5):
        self.model_name = model_name
        self.threshold = threshold
        self._model = model
        self._armed = True

    def _ensure_model(self):
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(wakeword_models=[self.model_name])
        return self._model

    def process(self, frame: np.ndarray) -> bool:
        score = self._ensure_model().predict(frame).get(self.model_name, 0.0)
        if score >= self.threshold:
            if self._armed:
                self._armed = False
                return True
            return False
        self._armed = True
        return False
