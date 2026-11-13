"""Port of the Studio movement, button recording and matching loop."""
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from shadowafk.capture import capture, windows
from shadowafk.studio_input import WindowsInput

TARGETS = {"play": "Играть", "replay": "Играть снова"}
KEYS = (ord("W"), ord("A"), ord("S"), ord("D"), 0x20)
WIDTH, HEIGHT = 170, 64
COLS, ROWS = 17, 8
SAMPLE_X = (2 * np.arange(COLS) + 1) * WIDTH // (2 * COLS)
SAMPLE_Y = (2 * np.arange(ROWS) + 1) * HEIGHT // (2 * ROWS)


def sample(frame, x, y):
    left, top = x - WIDTH // 2, y - HEIGHT // 2
    if left < 0 or top < 0 or left + WIDTH > frame.shape[1] or top + HEIGHT > frame.shape[0]:
        return None
    return frame[(top + SAMPLE_Y)[:, None], left + SAMPLE_X].astype(np.int16)


def read_target(values):
    x, y, width, height, *pixels = values
    if not all(type(v) is int for v in values) or len(pixels) != ROWS * COLS or not all(0 <= p <= 0xffffff for p in pixels):
        raise ValueError("Некорректный шаблон")
    colors = np.array(pixels, dtype=np.int32).reshape(ROWS, COLS)
    return x, y, width, height, np.stack([colors & 255, (colors >> 8) & 255, colors >> 16], axis=2)


def scan_window(window, targets, primary_size):
    _, result = capture(window["handle"], window["pid"], color=True)
    if result is None:
        return None, {}
    frame, geometry = result
    scores = {}
    desktop_size = primary_size() if any(target[2] < 0 for target in targets.values()) else None
    for name, (x, y, width, height, reference) in targets.items():
        best, point = 0, (x, y)
        if width < 0:
            x, y = x - geometry[0], y - geometry[1]
        if (width < 0 and (-width, height) == desktop_size) or (width, height) == geometry[2:]:
            for dy in range(-16, 17, 8):
                for dx in range(-24, 25, 8):
                    pixels = sample(frame, x + dx, y + dy)
                    if pixels is None:
                        continue
                    score = int(100 * np.count_nonzero(np.abs(pixels - reference).sum(axis=2) < 112) // (ROWS * COLS))
                    if score > best:
                        best, point = score, (x + dx, y + dy)
        scores[name] = (best, point)
    return geometry, scores


class Studio(QObject):
    changed = Signal()
    settingsChanged = Signal()

    def __init__(self, controller, enabled):
        super().__init__(controller)
        self.controller = controller
        self.input = WindowsInput() if sys.platform == "win32" and enabled else None
        self.path = controller.directory / "studio.json"
        self.legacy = Path(os.getenv("LOCALAPPDATA", "")) / "ShadowAFKStudio" if self.input else None
        self.config = dict(low=2, high=5, threshold=78, movement=True, clicks=True)
        self.targets = {}
        self.load()
        self.window = None
        self.started = None
        self.generation = 0
        self.held = None
        self.key_count = self.click_count = self.walks = 0
        self.jump_after = 5
        self.previous_key = None
        self.next_key = self.key_end = self.next_scan = self.cooldown = self.keyboard_pause = 0
        self.future = self.recording = self.restore = None
        self.scores, self.streaks = {}, {}
        self.message = "Готов к запуску"
        self.timer = QTimer(self, interval=50)
        self.timer.timeout.connect(self.tick)
        self.executor = ThreadPoolExecutor(max_workers=1)
        if self.input:
            self.timer.start()

    def load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                settings = data["settings"]
                targets = data["targets"]
            elif self.legacy:
                settings, targets = {}, {}
                legacy_settings = self.legacy / "settings.txt"
                if legacy_settings.exists():
                    low, high, threshold, movement, clicks = legacy_settings.read_text(encoding="utf-8-sig").splitlines()[:5]
                    settings = dict(low=int(low), high=int(high), threshold=int(threshold),
                                    movement=movement.lower() == "true", clicks=clicks.lower() == "true")
                for name in TARGETS:
                    path = self.legacy / f"target_{name}.txt"
                    if path.exists():
                        try:
                            values = list(map(int, path.read_text(encoding="utf-8-sig").splitlines()))
                            values[2] = -abs(values[2])  # Legacy targets use physical desktop coordinates.
                            targets[name] = values
                        except (OSError, ValueError, IndexError):
                            self.controller.log(f"Перезапишите шаблон «{TARGETS[name]}»")
            else:
                return
            low = max(1, min(120, int(settings.get("low", 2))))
            high = max(low, min(120, int(settings.get("high", 5))))
            threshold = max(55, min(96, int(settings.get("threshold", 78))))
            self.config.update(low=low, high=high, threshold=threshold,
                               movement=bool(settings.get("movement", True)), clicks=bool(settings.get("clicks", True)))
            for name in TARGETS.keys() & targets.keys():
                try:
                    self.targets[name] = read_target(targets[name])
                except (ValueError, TypeError):
                    self.controller.log(f"Перезапишите шаблон «{TARGETS[name]}»")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            self.controller.log(f"Настройки Studio: {error}")

    def save(self):
        targets = {}
        for name, (x, y, width, height, colors) in self.targets.items():
            b, g, r = np.moveaxis(colors.astype(np.int32), 2, 0)
            targets[name] = [x, y, width, height, *((r << 16) | (g << 8) | b).ravel().tolist()]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(dict(settings=self.config, targets=targets)), encoding="utf-8")
        temporary.replace(self.path)

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self.config

    @Property("QVariantMap", notify=changed)
    def status(self):
        now = monotonic()
        delay = max(0, self.next_key - now)
        return dict(active=self.started is not None, message=self.message, keys=self.key_count,
                    clicks=self.click_count, seconds=int(now - self.started) if self.started else 0,
                    next=f"{delay:.1f} с" if self.message == "Fortnite активно" and self.config["movement"] else "—",
                    play=self.target_status("play"), replay=self.target_status("replay"))

    def target_status(self, name):
        if self.recording and self.recording[0] == name:
            return "Запись…"
        if name not in self.targets:
            return "Не сохранено"
        if name in self.scores:
            return f"{self.scores[name][0]}%"
        return "Сохранено"

    @Slot(int, int, int, bool, bool)
    def configure(self, low, high, threshold, movement, clicks):
        low = max(1, min(120, low))
        previous = self.config
        self.config = dict(low=low, high=max(low, min(120, high)), threshold=max(55, min(96, threshold)),
                           movement=movement, clicks=clicks)
        try:
            self.save()
        except OSError as error:
            self.config = previous
            self.controller.log(f"Не удалось сохранить настройки Studio: {error}")
            self.controller.notify.emit("Не удалось сохранить настройки Studio")
            self.settingsChanged.emit()
            return
        if not self.recording:
            self.generation += 1
        self.streaks.clear()
        if not movement:
            self.release()
        self.settingsChanged.emit()
        self.changed.emit()

    def available(self):
        if not self.input:
            self.controller.notify.emit("Studio доступна в Windows")
            return False
        telegram = self.controller.telegram
        if telegram and not telegram.offline and telegram.status["state"] != "connected":
            self.controller.notify.emit("Сначала войдите через Telegram")
            return False
        return True

    @Slot()
    def toggle(self):
        if self.started is not None:
            self.stop()
            return
        if not self.available():
            return
        choices = windows()
        self.window = next((window for window in choices if self.input.focused(window)), None)
        if self.window is None and len(choices) == 1:
            self.window = choices[0]
        if self.window is None:
            self.controller.notify.emit("Перейдите в Fortnite и нажмите F6")
            return
        if not (self.config["movement"] or self.config["clicks"] and self.targets):
            self.controller.notify.emit("Включите движение или запишите кнопку и включите автонажатия")
            return
        self.started = monotonic()
        self.next_key = self.started + self.delay()
        self.next_scan = self.started
        self.keyboard_pause = 0
        self.walks, self.previous_key = 0, None
        self.jump_after = random.randint(4, 7)
        self.message = "Переключитесь в Fortnite"
        self.controller.log(f"Studio запущена: {self.window['title']}")
        self.changed.emit()

    def release(self):
        if self.held is None:
            return True
        if not self.input.key(self.held, release=True):
            return False
        self.held = None
        return True

    def stop(self):
        active = self.started is not None
        self.started = None
        self.recording = None
        self.generation += 1
        self.streaks.clear()
        self.scores.clear()
        self.release()
        self.restore_cursor(float("inf"))
        self.message = "Готов к запуску"
        if active:
            self.controller.log("Studio остановлена")
        self.changed.emit()

    def delay(self):
        return random.uniform(self.config["low"], self.config["high"])

    @Slot(str)
    def record(self, name):
        if name not in TARGETS or not self.available() or self.recording:
            return
        window = next((item for item in windows() if self.input.focused(item)), None)
        if window is None:
            key = "F7" if name == "play" else "F8"
            self.controller.notify.emit(f"Наведите курсор на центр «{TARGETS[name]}» в Fortnite и нажмите {key}")
            return
        point = self.input.cursor()
        geometry = self.input.geometry(window)
        if not point or not geometry:
            return
        left, top, width, height = geometry
        x, y = point[0] - left, point[1] - top
        if not (WIDTH // 2 <= x <= width - WIDTH // 2 and HEIGHT // 2 <= y <= height - HEIGHT // 2):
            self.controller.notify.emit("Кнопка слишком близко к краю окна")
            return
        self.release()
        self.generation += 1
        self.streaks.clear()
        self.recording = (name, window, geometry, x, y, monotonic() + 0.28)
        away = (point[0], top + (y + 135 if y + 135 < height else max(0, y - 135)))
        if self.input.focused(window) and self.input.move_cursor(away):
            self.restore = (window, away, point, monotonic() + 0.6)
        self.changed.emit()

    def restore_cursor(self, now):
        if self.restore:
            window, point, previous, when = self.restore
            if now >= when:
                self.restore = None
                if self.input.focused(window) and self.input.cursor() == point:
                    self.input.move_cursor(previous)

    def finish_recording(self, name, geometry, x, y, result):
        self.recording = None
        if result is None or result[1] != geometry:
            self.controller.log(f"Не удалось записать «{TARGETS[name]}»: окно изменилось")
            return
        colors = sample(result[0], x, y)
        if colors is None or np.ptp(colors.mean(axis=2)) < 13:
            self.controller.log(f"Не удалось записать «{TARGETS[name]}»: наведите курсор на текст кнопки")
            return
        previous = self.targets.get(name)
        self.targets[name] = (x, y, *geometry[2:], colors)
        try:
            self.save()
        except OSError:
            if previous is None:
                del self.targets[name]
            else:
                self.targets[name] = previous
            raise
        self.scores.pop(name, None)
        self.controller.log(f"Сохранена кнопка «{TARGETS[name]}»")

    def apply_scan(self, geometry, scores, now):
        self.scores = scores
        if geometry is None or self.input.geometry(self.window) != geometry:
            self.streaks.clear()
            return
        self.streaks = {name: self.streaks.get(name, 0) + 1 if score >= self.config["threshold"] else 0
                        for name, (score, _) in scores.items()}
        candidates = [name for name in scores if self.streaks[name] >= 2]
        if now < self.cooldown or not candidates or not self.release():
            return
        name = max(candidates, key=lambda item: scores[item][0])
        score, (x, y) = scores[name]
        point = (geometry[0] + x, geometry[1] + y)
        previous = self.input.cursor()
        clicked = self.input.click(self.window, geometry, point)
        if previous is not None and self.input.cursor() == point:
            self.restore = (self.window, point, previous, now + 0.135)
        self.streaks.clear()
        self.cooldown, self.keyboard_pause = now + 10, now + 8
        self.next_key = self.keyboard_pause + self.delay()
        if clicked:
            self.click_count += 1
        message = "Автонажатие" if clicked else "Windows не приняла клик"
        self.controller.log(f"{message} «{TARGETS[name]}» ({score}%)")

    def move(self, now):
        if self.held is not None:
            if now >= self.key_end and self.release():
                self.next_key = now + self.delay()
            return
        if now < self.next_key:
            return
        jump = self.walks >= self.jump_after
        key = KEYS[-1] if jump else random.choice([key for key in KEYS[:-1] if key != self.previous_key])
        if not self.input.focused(self.window):
            return
        if not self.input.key(key):
            self.next_key = now + 2
            self.controller.log("Windows отклонила нажатие клавиши Studio")
            return
        self.held = self.previous_key = key
        duration = random.uniform(0.10, 0.19) if jump else random.uniform(0.16, 0.36)
        self.key_end = now + duration
        self.key_count += 1
        if self.key_count % 6 == 0:
            self.controller.log(f"Studio: нажатий клавиш — {self.key_count}")
        self.walks = 0 if jump else self.walks + 1
        if jump:
            self.jump_after = random.randint(4, 7)

    def tick(self):
        try:
            self.advance(monotonic())
        except Exception as error:
            self.stop()
            self.message = "Studio остановлена из-за ошибки"
            self.controller.log(f"Ошибка Studio: {error}")
            if self.controller.telegram:
                self.controller.telegram.notice("app_error", self.controller.notification_session)
            self.changed.emit()

    def advance(self, now):
        if self.started is not None or self.recording:
            telegram = self.controller.telegram
            if telegram and not telegram.offline and telegram.status["state"] != "connected":
                self.stop()
        focused = self.started is not None and self.input.focused(self.window)
        if not focused or self.recording or not self.config["movement"]:
            self.release()
        if self.started is not None and not focused:
            self.streaks.clear()
            if not self.recording and self.message != "Пауза: переключитесь в Fortnite":
                self.generation += 1
            self.message = "Пауза: переключитесь в Fortnite"
            self.next_key = max(self.next_key, now + 1)
        if self.future and self.future[0].done():
            job, generation, recording = self.future
            self.future = None
            if generation == self.generation:
                if recording:
                    name, window, geometry, x, y, _ = recording
                    _, result = job.result()
                    self.finish_recording(name, geometry, x, y, result if self.input.focused(window) else None)
                    self.changed.emit()
                elif focused and self.config["clicks"]:
                    self.apply_scan(*job.result(), now)
        if self.recording:
            name, window, geometry, x, y, when = self.recording
            if not self.future and now >= when:
                job = self.executor.submit(capture, window["handle"], window["pid"], True)
                self.future = job, self.generation, self.recording
        elif focused:
            self.message = "Fortnite активно" if now >= self.keyboard_pause else "Ожидание матча"
            if self.config["movement"] and now >= self.keyboard_pause:
                self.move(now)
            if self.config["clicks"] and self.targets and not self.future and now >= self.next_scan:
                self.next_scan = now + 0.52
                job = self.executor.submit(scan_window, self.window, self.targets.copy(), self.input.primary_size)
                self.future = job, self.generation, None
        self.restore_cursor(now)
        if self.started is not None or self.recording or self.restore or self.future:
            self.changed.emit()

    def close(self):
        self.timer.stop()
        self.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
