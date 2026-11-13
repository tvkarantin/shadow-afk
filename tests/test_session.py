import csv

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from shadowafk.app import Controller
from shadowafk.match import STAGES


def test_simulation_persistence_and_export(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    controller.saveSettings(5, 86, False, "Ctrl+Shift+Q")
    controller.start("sim", -1)
    controller.pause()
    controller.next_step = 0
    controller.tick()
    assert controller.status["stage"] == 0
    controller.pause()
    for _ in STAGES:
        controller.next_step = 0
        controller.tick()
    assert not controller.status["active"]
    assert controller.history[0]["mode"] == "sim"
    assert controller.history[0]["games"] == controller.history[0]["cycles"] == 1
    controller.addGoal("Открыть сундуки", 1, 5)
    goal = controller.goals[0]
    controller.updateGoal(goal["id"], 2)
    assert controller.goals[0]["delta"] == 1
    controller.exportHistory(QUrl.fromLocalFile(str(tmp_path / "report.csv")))
    controller.close()
    reopened = Controller(tmp_path)
    try:
        assert reopened.settings["threshold"] == 86
        assert reopened.settings["stopKey"] == "Ctrl+Shift+Q"
        assert reopened.goals[0]["progress"] == 2
        with (tmp_path / "report.csv").open(encoding="utf-8-sig", newline="") as stream:
            assert next(csv.DictReader(stream))["cycles"] == "1"
    finally:
        reopened.close()


def test_capture_preview_is_available_in_memory(monkeypatch, tmp_path):
    import numpy as np
    from PySide6.QtCore import QSize
    from shadowafk import app as shadow_app

    qt_app = QApplication.instance() or QApplication([])
    frame = np.full((240, 420), 80, dtype=np.uint8)
    monkeypatch.setattr(shadow_app, "capture", lambda handle, pid: ("", frame))
    monkeypatch.setattr(shadow_app, "detect", lambda *args: shadow_app.Detection("LOBBY", 0.95))
    for name in ("preview.tmp", "preview.png"):
        (tmp_path / name).mkdir()  # Neither legacy path can be opened for writing.

    _, detection, image = shadow_app.process_frame({"handle": 1, "pid": 2}, [], 0.85)
    provider = shadow_app.PreviewProvider()
    provider.frame = image
    size = QSize()
    preview = provider.requestImage("1", size, QSize())
    assert (detection.state, detection.confidence) == ("LOBBY", 0.95)
    assert size == QSize(420, 240)
    assert preview.pixelColor(0, 0).red() == 80


def test_stale_capture_after_pause_and_stop(tmp_path):
    from concurrent.futures import Future
    from PySide6.QtGui import QImage
    from shadowafk.app import CaptureState, Detection

    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    try:
        controller.start("sim", -1)
        for cancel in (controller.pause, controller.stop):
            if controller.paused:
                controller.pause()
            job = Future()
            job.set_running_or_notify_cancel()
            controller.future = job
            controller.job_generation = controller.generation
            token = controller.cancelled
            cancel()
            assert token.is_set()
            job.set_result((CaptureState.FRAME_AVAILABLE, Detection("IN_MATCH", .99), QImage(8, 8, QImage.Format_Grayscale8)))
            controller.tick()
            assert not controller.preview_visible
            assert controller.match.detected == 0
            assert controller.future is None
    finally:
        controller.close()


def test_goal_progress_requires_manual_confirmation(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    try:
        controller.start("sim", -1)
        controller.addGoal("Сундуки", 2, 10)
        goal = controller.goals[0]["id"]
        controller.proposeGoal(goal, 4)
        draft = controller.goals[0]
        assert (draft["progress"], draft["pending"]) == (2, 4)
        assert draft["events"][0]["session_id"] == controller.session
        controller.updateGoal(goal, 4)
        confirmed = controller.goals[0]
        assert (confirmed["progress"], confirmed["pending"]) == (4, -1)
        assert confirmed["events"][0]["confirmed"] == 1
        assert confirmed["perMatch"] == "—"
    finally:
        controller.close()


def test_closed_window_reacquires_without_counting_a_new_match(monkeypatch, tmp_path):
    from concurrent.futures import Future
    from PySide6.QtGui import QImage
    from shadowafk import app as shadow_app

    qt_app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    old_window = {"handle": 10, "pid": 100, "title": "Fortnite"}
    new_window = {"handle": 20, "pid": 200, "title": "Fortnite"}
    monkeypatch.setattr(shadow_app, "windows", lambda: [new_window])

    def accept_capture(status, state=""):
        job = Future()
        image = QImage(8, 8, QImage.Format_Grayscale8) if state else None
        job.set_result((status, shadow_app.Detection(state, .95), image))
        controller.future = job
        controller.job_generation = controller.generation
        controller.next_step = float("inf")
        controller.tick()

    try:
        controller.window_list = [old_window]
        with monkeypatch.context() as startup:
            startup.setattr(controller, "tick", lambda: None)
            controller.start("live", 0)
        assert controller.session is not None
        controller.observe("IN_MATCH", 1)
        match_id = controller.match.match_id
        for status in (shadow_app.CaptureState.WINDOW_NOT_ACTIVE, shadow_app.CaptureState.NO_FRAME,
                       shadow_app.CaptureState.CAPTURE_ERROR, shadow_app.CaptureState.WINDOW_CLOSED):
            accept_capture(status)
            assert controller.match.state == "IN_MATCH"
            assert controller.match.match_id == match_id
        assert controller.window == new_window
        for _ in range(3):
            accept_capture(shadow_app.CaptureState.FRAME_AVAILABLE, "RESULTS")
        assert controller.match.detected == controller.match.completed == 1
        assert controller.errors == 1
    finally:
        controller.close()

    reopened = Controller(tmp_path)
    try:
        row = reopened.history[0]
        assert (row["mode"], row["games"], row["cycles"], row["result"]) == ("live", 1, 1, "Закрыто")
    finally:
        reopened.close()
