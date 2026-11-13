import ctypes
import sys
from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication

from shadowafk.app import Controller
from shadowafk.studio import Studio, read_target, sample, scan_window
from shadowafk.studio_input import Input, WindowsInput


def test_studio_scan_tracks_offset_and_rejects_other_sizes(monkeypatch):
    frame = np.random.default_rng(7).integers(0, 256, (200, 320, 3), dtype=np.uint8)
    geometry = (40, 50, 320, 200)
    monkeypatch.setattr("shadowafk.studio.capture", lambda *args, **kwargs: (None, (frame, geometry)))
    window = {"handle": 1, "pid": 2}
    reference = sample(frame, 158, 108)
    targets = {"play": (150, 100, 320, 200, reference),
               "replay": (150, 100, 640, 400, reference)}
    assert scan_window(window, targets, lambda: (320, 200)) == (
        geometry, {"play": (100, (158, 108)), "replay": (0, (150, 100))}
    )


def test_studio_confirms_button_and_releases_key(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    studio = Studio(controller, enabled=False)
    controller.studio = studio
    events = []
    geometry = (10, 20, 320, 200)
    studio.input = SimpleNamespace(
        key=lambda vk, release: events.append((vk, release)) or True,
        cursor=lambda: (0, 0), geometry=lambda window: geometry,
        click=lambda window, rect, point: events.append(point) or True,
    )
    studio.held = ord("W")
    studio.apply_scan(geometry, {"play": (90, (100, 100))}, 1)
    assert events == []
    studio.apply_scan(geometry, {"play": (90, (100, 100))}, 2)
    assert events == [(ord("W"), True), (110, 120)]
    assert studio.click_count == 1
    studio.apply_scan(geometry, {"play": (90, (100, 100))}, 3)
    studio.apply_scan(geometry, {"play": (90, (100, 100))}, 4)
    assert studio.click_count == 1
    controller.close()


def test_studio_settings_and_target_survive_restart(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    studio = Studio(controller, enabled=False)
    controller.studio = studio
    target = read_target([100, 120, 320, 200, *range(136)])
    studio.targets["replay"] = target
    studio.configure(3, 9, 85, False, True)
    controller.close()

    controller = Controller(tmp_path)
    studio = Studio(controller, enabled=False)
    controller.studio = studio
    assert studio.settings == dict(low=3, high=9, threshold=85, movement=False, clicks=True)
    assert studio.targets["replay"][:4] == target[:4]
    np.testing.assert_array_equal(studio.targets["replay"][4], target[4])
    controller.close()


def test_windows_studio_input_abi():
    if sys.platform == "win32":
        assert ctypes.sizeof(Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        assert all(size > 0 for size in WindowsInput().primary_size())
