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


def test_match_survives_capture_interruption_and_duplicate_results():
    match = Match()
    assert match.observe("IN_MATCH", 1, 1)
    match_id = match.match_id
    assert match.observe("ELIMINATED", 2, 1)
    assert match.observe("SPECTATING", 3, 1)
    match.interrupt(5)
    assert match.spectating_total(20) == 2
    for missing in ("", "ERROR", "GAME_NOT_FOUND"):
        assert not match.observe(missing, 20, 1)
        assert match.match_id == match_id
    assert match.observe("IN_MATCH", 21, 1)
    assert match.detected == 1
    assert match.observe("RESULTS", 22, 1)
    assert not match.observe("RESULTS", 23, 1)
    assert match.observe("LOBBY", 24, 1)
    assert not match.observe("RESULTS", 25, 1)
    assert match.completed == 1
    assert match.observe("IN_MATCH", 26, 1)
    assert match.match_id != match_id


def test_roi_threshold_and_ambiguous_templates():
    from shadowafk.match import Pattern, detect

    random = np.random.default_rng(100)
    frame = random.integers(0, 255, (120, 200), dtype=np.uint8)
    pattern = frame[12:30, 16:39].copy()
    good = Pattern("LOBBY", pattern, 200, "Лобби", (0, 0, .5, .5))
    wrong_roi = Pattern("LOBBY", pattern, 200, "Вне зоны", (.5, .5, 1, 1))
    flat = Pattern("LOADING", np.zeros((20, 30), dtype=np.uint8), 200)
    result = detect(frame, [flat, wrong_roi, good], .85)
    assert (result.state, result.template, result.box) == ("LOBBY", "Лобби", (16, 12, 23, 18))
    assert not detect(frame, [wrong_roi], .85).state
    assert not detect(frame, [flat], .85).candidate
    assert not detect(frame, [], .85).state
    duplicate = Pattern("LOADING", pattern, 200)
    assert detect(frame, [good, duplicate], .85).reason == "Неоднозначное совпадение"
    noisy = frame.copy()
    noisy[12:30, 16:39] = np.clip(pattern.astype(float) + random.normal(0, 25, pattern.shape), 0, 255)
    assert detect(noisy, [good], .85).state == "LOBBY"
    assert not detect(noisy, [good], .85, {"LOBBY": .99}).state
