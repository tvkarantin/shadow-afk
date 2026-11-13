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
    monkeypatch.setattr(shadow_app, "recognize", lambda *args: ("LOBBY", 0.95, None))
    for name in ("preview.tmp", "preview.png"):
        (tmp_path / name).mkdir()  # Neither legacy path can be opened for writing.

    state, confidence, image = shadow_app.process_frame({"handle": 1, "pid": 2}, [], 0.85)
    provider = shadow_app.PreviewProvider()
    provider.frame = image
    size = QSize()
    preview = provider.requestImage("1", size, QSize())
    assert (state, confidence) == ("LOBBY", 0.95)
    assert size == QSize(420, 240)
    assert preview.pixelColor(0, 0).red() == 80
