import cv2
import numpy as np

from shadowafk.match import Match, recognize


def test_squads_elimination_is_not_completion():
    match = Match()
    for tick, state in enumerate(["IN_MATCH", "ELIMINATED", "SPECTATING"]):
        assert not match.observe(state, tick)
        assert not match.observe(state, tick)
        assert match.observe(state, tick)
    assert match.detected == 1
    assert match.completed == 0
    assert not match.observe("RESULTS", 4)
    assert not match.observe("", 5)
    assert not match.observe("RESULTS", 6)
    assert not match.observe("RESULTS", 7)
    assert match.observe("RESULTS", 8)
    assert match.completed == 1
    assert match.match_seconds == 8
    assert match.spectating_seconds == 6
    assert not match.observe("IN_MATCH", 9, 1)


def test_match_template_moves_and_scales():
    random = np.random.default_rng(42)
    pattern = random.integers(0, 255, (24, 35), dtype=np.uint8)
    frame = random.integers(0, 80, (300, 600), dtype=np.uint8)
    frame[140:176, 208:260] = cv2.resize(pattern, (52, 36))
    state, confidence, box = recognize(frame, [("RESULTS", pattern, 400)], 0.85)
    assert (state, box) == ("RESULTS", (208, 140, 52, 36))
    assert confidence > 0.95
    assert recognize(frame, [("RESULTS", pattern, 400), ("SPECTATING", pattern, 400)], 0.85)[0] == ""
