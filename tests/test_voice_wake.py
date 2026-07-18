"""tests/test_voice_wake.py"""
import numpy as np

from lydia.voice.wake import WakeDetector


class FakeOww:
    def __init__(self, scores):
        self.scores = list(scores)

    def predict(self, frame):
        return {"hey_jarvis": self.scores.pop(0)}

    def reset(self):
        pass


FRAME = np.zeros(1280, dtype=np.int16)


def test_fires_once_when_score_crosses_threshold():
    det = WakeDetector("hey_jarvis", model=FakeOww([0.1, 0.7, 0.8, 0.2, 0.9]))
    fired = [det.process(FRAME) for _ in range(5)]
    # fires on first crossing, NOT on the still-high next frame, refires after dropping
    assert fired == [False, True, False, False, True]


def test_ignores_other_models_scores():
    class Multi(FakeOww):
        def predict(self, frame):
            return {"alexa": 0.99, "hey_jarvis": self.scores.pop(0)}

    det = WakeDetector("hey_jarvis", model=Multi([0.1, 0.1]))
    assert det.process(FRAME) is False and det.process(FRAME) is False
