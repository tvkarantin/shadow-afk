import csv
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from time import monotonic
from uuid import uuid4
from threading import Event

import cv2
from PySide6.QtCore import QObject, Property, QStandardPaths, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from shadowafk.telegram import Telegram
from shadowafk.capture import CaptureState, capture, windows
from shadowafk.hotkey import EmergencyHotkey, STOP_KEYS
from shadowafk.match import LABELS, STAGES, TRANSITIONS, Detection, Match, Pattern, detect, load_gray


def process_frame(window, templates, threshold, thresholds=None, current='', cancelled=None):
    status, frame = capture(window["handle"], window["pid"])
    if frame is None:
        return status, Detection(), None
    result = detect(frame, templates, threshold, thresholds, current, cancelled)
    if result.box:
        frame = frame.copy()
        x, y, w, h = result.box
        cv2.rectangle(frame, (x, y), (x+w, y+h), 255, max(2, frame.shape[1] // 500))
    if frame.shape[1] > 800:
        frame = cv2.resize(frame, (800, round(frame.shape[0] * 800 / frame.shape[1])))
    height, width = frame.shape
    preview = QImage(frame.tobytes(), width, height, width, QImage.Format_Grayscale8)
    return status, result, preview.copy()


class PreviewProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self.frame = QImage()

    def requestImage(self, image_id, size, requested_size):
        size.setWidth(self.frame.width())
        size.setHeight(self.frame.height())
        return self.frame


class Controller(QObject):
    changed = Signal()
    libraryChanged = Signal()
    settingsChanged = Signal()
    notify = Signal(str)

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.preview = PreviewProvider()
        self.preview_revision = 0
        self.db = sqlite3.connect(directory / "shadowafk.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, date TEXT, mode TEXT,
                games INTEGER, cycles INTEGER, seconds INTEGER, match_seconds REAL,
                spectating_seconds REAL, errors INTEGER, result TEXT);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, time TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, name TEXT, progress INTEGER, target INTEGER);
            CREATE TABLE IF NOT EXISTS goal_events(id INTEGER PRIMARY KEY, goal_id INTEGER,
                session_id INTEGER, date TEXT, before INTEGER, after INTEGER, confirmed INTEGER);
            CREATE TABLE IF NOT EXISTS templates(id INTEGER PRIMARY KEY, name TEXT, state TEXT,
                reference_width INTEGER, path TEXT);
            UPDATE sessions SET result='Прервано' WHERE result='Активна';
        """)
        self.settings_path = directory / "settings.json"
        self.config = {"speed": 3, "threshold": 85, "repeat": True, "stopKey": "Ctrl+Alt+Q"}
        saved = {}
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.config.update(speed=max(1, min(5, int(saved["speed"]))),
                               threshold=max(50, min(99, int(saved["threshold"]))),
                               repeat=bool(saved["repeat"]), stopKey=saved.get("stopKey", "Ctrl+Alt+Q"))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.config["stateOptions"] = saved.get("stateOptions", {}) if isinstance(saved, dict) else {}
        if not isinstance(self.config["stateOptions"], dict):
            self.config["stateOptions"] = {}
        if self.config["stopKey"] not in tuple(STOP_KEYS):
            self.config["stopKey"] = "Ctrl+Alt+Q"
        self.hotkey = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.telegram = None
        self.notification_session = ""
        self.window_closed_since = None
        self.recognition_misses = 0
        self.victory_frames = 0
        self.generation = 0
        self.cancelled = Event()
        self.capture_state = CaptureState.NO_FRAME
        self.detection = Detection()
        self.capture_error = ""
        self.last_frame = None
        self.last_detected = {}
        self.state_scores = {}
        self.template_counts = {}
        self.session = None
        self.mode = "sim"
        self.match = Match()
        self.stage = -1
        self.clock = None
        self.elapsed = 0
        self.errors = 0
        self.confidence = 0
        self.paused = False
        self.outcome = "Остановлено"
        self.next_step = 0
        self.last_checkpoint = -1
        self.window_list = []
        self.window_index = -1
        self.preview_visible = False
        self.patterns = []
        self.baseline = {}
        self.action = ""
        self.timer = QTimer(self, interval=200)
        self.timer.timeout.connect(self.tick)
        self.template_counts = self.count_templates(self.templates)
        self.timer.start()

    def rows(self, sql):
        return [dict(row) for row in self.db.execute(sql)]

    @Property("QVariantMap", notify=changed)
    def status(self):
        active = self.session is not None
        title, hint = LABELS.get(self.match.state, ("Ожидание кадра", "Выведите Fortnite на передний план"))
        if not active:
            title, hint = self.outcome, "Запустите симуляцию или мониторинг"
        elif self.paused:
            title, hint = "На паузе", "Продолжите, когда будете готовы"
        elif self.mode == "live" and self.capture_state != CaptureState.FRAME_AVAILABLE:
            hint = "Ожидание видимого кадра Fortnite"
        return dict(active=active, paused=self.paused, title=title, hint=hint, games=self.match.detected,
                    cycles=self.match.completed, seconds=int(self.active_time()), stage=self.stage,
                    mode=self.mode, state=self.match.state, confidence=self.confidence, action=self.action,
                    capture=str(self.capture_state), previous=self.match.previous,
                    matchId=str(self.match.match_id or ""), candidate=self.detection.candidate,
                    template=self.detection.template, reason=self.detection.reason,
                    captureError=self.capture_error,
                    confirmations=self.match.confirmations or self.match.last_confirmed,
                    frameAge=-1 if self.last_frame is None else round(monotonic() - self.last_frame, 1),
                    preview=f"image://capture/{self.preview_revision}" if self.preview_visible else "")

    @Property("QVariantList", constant=True)
    def stages(self):
        return [dict(key=key, title=title, hint=hint) for key, title, hint in STAGES]

    @Property("QVariantList", notify=libraryChanged)
    def logs(self):
        return self.rows("SELECT time, message FROM logs ORDER BY id DESC LIMIT 200")

    @Property("QVariantList", notify=libraryChanged)
    def history(self):
        return self.rows("SELECT * FROM sessions ORDER BY id DESC")

    @Property("QVariantList", notify=libraryChanged)
    def goals(self):
        rows = self.rows("SELECT * FROM goals ORDER BY id DESC")
        for row in rows:
            row["delta"] = row["progress"] - self.baseline.get(row["id"], row["progress"])
            events = list(self.db.execute(
                "SELECT * FROM goal_events WHERE goal_id=? ORDER BY id DESC LIMIT 10", (row["id"],)))
            row["events"] = [dict(event) for event in events]
            row["pending"] = next((event["after"] for event in events if not event["confirmed"]), -1)
            totals = self.db.execute("""
                SELECT COALESCE(SUM(changes.delta), 0), COALESCE(SUM(s.cycles), 0),
                       COALESCE(SUM(s.seconds), 0)
                FROM (SELECT session_id, SUM(after-before) AS delta FROM goal_events
                      WHERE goal_id=? AND confirmed=1 GROUP BY session_id) AS changes
                JOIN sessions s ON s.id=changes.session_id WHERE s.mode='live'
            """, (row["id"],)).fetchone()
            delta, matches, seconds = totals
            row["perMatch"] = f"{delta / matches:.2f}" if matches else "—"
            row["perHour"] = f"{delta * 3600 / seconds:.2f}" if seconds else "—"
        return rows

    @Property("QVariantList", notify=libraryChanged)
    def templates(self):
        rows = self.rows("SELECT * FROM templates ORDER BY id DESC")
        for row in rows:
            row["path"] = str(self.directory / row["path"])
            row["url"] = QUrl.fromLocalFile(row["path"]).toString()
            row["builtin"] = False
        for path in sorted(Path(__file__).with_name("ui").joinpath("templates").glob("*.png")):
            state, reference_width = path.stem.split("-")
            rows.append(dict(name=LABELS[state][0] + " · Встроенный", state=state,
                             reference_width=int(reference_width), path=str(path),
                             url=QUrl.fromLocalFile(str(path)).toString(), builtin=True))
        return rows

    @Property(str, notify=changed)
    def missingCritical(self):
        return ", ".join(LABELS[state][0] for state in ("LOBBY", "IN_MATCH", "RESULTS")
                         if not self.template_counts.get(state))

    @Property("QVariantList", notify=changed)
    def diagnostics(self):
        return [dict(state=key, title=title, count=self.template_counts.get(key, 0),
                     last=self.last_detected.get(key, "—"), confidence=self.state_scores.get(key, "—"))
                for key, title, _ in STAGES]

    @Slot(QUrl)
    def saveDiagnostic(self, target):
        if self.preview.frame.isNull() or not self.preview.frame.save(target.toLocalFile(), "PNG"):
            self.notify.emit("Не удалось сохранить диагностический кадр")

    @Slot(str, int, str)
    def setStateOptions(self, state, threshold, roi_text):
        try:
            roi = tuple(float(value.strip()) for value in roi_text.split(",")) if roi_text.strip() else None
            if state not in LABELS or not 0.50 <= threshold / 100 <= 0.99:
                raise ValueError
            if roi is not None:
                x, y, right, bottom = roi
                if not (0 <= x < right <= 1 and 0 <= y < bottom <= 1):
                    raise ValueError
        except (TypeError, ValueError):
            self.notify.emit("ROI: четыре числа от 0 до 1 через запятую")
            return
        self.config["stateOptions"][state] = dict(threshold=threshold / 100, roi=roi)
        self.saveSettings(self.config["speed"], self.config["threshold"], self.config["repeat"], self.config["stopKey"])
        self.notify.emit("Настройки состояния сохранены")

    @Property("QVariantList", notify=changed)
    def windowTitles(self):
        return [row["title"] for row in self.window_list]

    @Property(bool, constant=True)
    def windowsSupported(self):
        return sys.platform == "win32"

    @Property(bool, notify=settingsChanged)
    def globalStop(self):
        return self.hotkey is not None and self.hotkey.registered

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self.config.copy()

    def log(self, message):
        with self.db:
            self.db.execute("INSERT INTO logs(time, message) VALUES (?, ?)",
                            (datetime.now().strftime("%H:%M:%S"), message))
            self.db.execute("DELETE FROM logs WHERE id <= (SELECT MAX(id)-200 FROM logs)")
        self.libraryChanged.emit()

    def active_time(self):
        return self.elapsed + (monotonic() - self.clock if self.clock is not None else 0)

    @Slot()
    def refreshWindows(self):
        self.window_list = windows()
        self.template_counts = self.count_templates(self.templates)
        self.changed.emit()

    @staticmethod
    def count_templates(templates):
        counts = {}
        for item in templates:
            state = item["state"] if isinstance(item, dict) else item.state
            counts[state] = counts.get(state, 0) + 1
        return counts

    @Slot(str, int)
    def start(self, mode, index):
        if self.session is not None:
            if self.paused:
                self.pause()
            return
        if mode == "live":
            if not 0 <= index < len(self.window_list):
                self.notify.emit("Выберите окно Fortnite")
                return
            self.window = self.window_list[index].copy()
            self.patterns = []
            self.state_thresholds = {}
            for row in self.templates:
                try:
                    state = row["state"]
                    image = load_gray(row["path"])
                    if min(image.shape) < 6 or image.std() < 2:
                        raise ValueError("Недостаточный контраст или размер")
                    options = self.config["stateOptions"].get(state, {})
                    if not isinstance(options, dict):
                        options = {}
                    minimum = options.get("threshold", self.config["threshold"] / 100)
                    roi = options.get("roi")
                    if not isinstance(minimum, (int, float)) or not 0.5 <= minimum <= 0.99:
                        minimum = self.config["threshold"] / 100
                    if roi is not None and (
                        not isinstance(roi, (list, tuple)) or len(roi) != 4
                        or not all(isinstance(value, (int, float)) for value in roi)
                        or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)
                    ):
                        roi = None
                    if "threshold" in options:
                        self.state_thresholds[state] = minimum
                    self.patterns.append(Pattern(state, image, row["reference_width"], row["name"], roi))
                except (OSError, ValueError, cv2.error):
                    self.log(f"Недоступен шаблон: {row['name']}")
            if not self.patterns:
                self.notify.emit("Добавьте хотя бы один шаблон состояния")
                return
            self.template_counts = self.count_templates(self.patterns)
            if self.missingCritical:
                self.notify.emit("Нет шаблонов: " + self.missingCritical)
        self.mode = mode
        self.notification_session = uuid4().hex
        self.window_closed_since = None
        self.recognition_misses = 0
        self.victory_frames = 0
        self.match = Match(state="UNKNOWN" if mode == "live" else "LOBBY")
        self.stage = -1
        self.elapsed = self.errors = self.confidence = 0
        self.baseline = {row["id"]: row["progress"] for row in self.goals}
        self.action = ""
        self.preview_visible = False
        self.preview.frame = QImage()
        self.capture_state = CaptureState.NO_FRAME
        self.detection = Detection()
        self.capture_error = ""
        self.last_frame = None
        self.last_detected.clear()
        self.state_scores.clear()
        self.cancel_pending()
        self.clock = monotonic()
        self.next_step = self.clock
        self.last_checkpoint = -1
        with self.db:
            self.session = self.db.execute(
                "INSERT INTO sessions(date, mode, games, cycles, seconds, match_seconds, spectating_seconds, errors, result)"
                " VALUES (?, ?, 0, 0, 0, 0, 0, 0, 'Активна')",
                (datetime.now().isoformat(timespec="seconds"), mode)).lastrowid
        self.log("Начата симуляция" if mode == "sim" else "Начато наблюдение за Fortnite")
        self.tick()

    def cancel_pending(self):
        self.victory_frames = 0
        self.generation += 1
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
        self.cancelled = Event()

    @Slot()
    def pause(self):
        if self.session is None:
            return
        self.cancel_pending()
        self.paused = not self.paused
        if self.paused:
            self.elapsed = self.active_time()
            self.clock = None
        else:
            self.clock = monotonic()
            self.next_step = self.clock
        self.match.interrupt(self.active_time())
        self.log("На паузе" if self.paused else "Сессия возобновлена")
        self.changed.emit()

    def checkpoint(self, result):
        now = self.active_time()
        spectating = self.match.spectating_total(now)
        with self.db:
            self.db.execute(
                "UPDATE sessions SET games=?, cycles=?, seconds=?, match_seconds=?, spectating_seconds=?, errors=?, result=? WHERE id=?",
                (self.match.detected, self.match.completed, int(now), self.match.match_seconds,
                 spectating, self.errors, result, self.session))

    @Slot()
    def stop(self, result="Остановлено"):
        if self.session is None:
            return
        self.cancel_pending()
        self.checkpoint(result)
        if self.telegram and self.mode == "live":
            self.telegram.notice("summary", self.notification_session, games=self.match.detected,
                                 completed=self.match.completed, seconds=int(self.active_time()))
        self.match.interrupt(self.active_time())
        self.match.started = self.match.match_id = None
        self.elapsed = self.active_time()
        self.clock = None
        self.session = None
        self.paused = False
        self.outcome = result
        self.log(result)
        self.changed.emit()

    def observe(self, state, required):
        if self.match.observe(state, self.active_time(), required):
            self.stage = next((i for i, item in enumerate(STAGES) if item[0] == state), -1)
            self.log(LABELS[state][0])
            if state == "RESULTS" and self.mode == "live":
                self.notify.emit("Матч завершён. Проверьте результаты в Fortnite.")

    def tick(self):
        if self.future is not None and self.future.done():
            job, generation = self.future, self.job_generation
            self.future = None
            if generation == self.generation:
                try:
                    capture_status, self.detection, frame = job.result()
                    error_text = ""
                except Exception as error:
                    capture_status, self.detection, frame = CaptureState.CAPTURE_ERROR, Detection(), None
                    error_text = str(error)
                self.confidence = self.detection.confidence
                if capture_status == CaptureState.CAPTURE_ERROR and (
                    self.capture_state != capture_status or self.capture_error != error_text
                ):
                    self.errors += 1
                    self.log("Ошибка захвата: " + (error_text or "кадр недоступен"))
                    if self.telegram and self.mode == "live":
                        self.telegram.notice("app_error", self.notification_session)
                self.capture_state, self.capture_error = capture_status, error_text
                if capture_status == CaptureState.WINDOW_CLOSED and self.match.match_id:
                    if self.window_closed_since is None:
                        self.window_closed_since = monotonic()
                    elif monotonic() - self.window_closed_since >= 8 and self.telegram:
                        self.telegram.notice("fortnite_exit", f"{self.notification_session}:{self.match.match_id}")
                        self.window_closed_since = float("inf")
                else:
                    self.window_closed_since = None
                if frame is None:
                    self.recognition_misses = self.victory_frames = 0
                    self.match.interrupt(self.active_time())
                    if capture_status == CaptureState.WINDOW_CLOSED:
                        available = windows()
                        if len(available) == 1:
                            self.window = available[0]
                            self.log("Окно Fortnite найдено повторно")
                else:
                    self.preview_visible = True
                    self.preview.frame = frame
                    self.preview_revision += 1
                    self.last_frame = monotonic()
                    state = self.detection.state
                    if state == "VICTORY":
                        if self.mode == "live" and self.match.match_id:
                            self.victory_frames += 1
                            if self.victory_frames == 3:
                                if self.telegram:
                                    self.telegram.notice("victory", f"{self.notification_session}:{self.match.match_id}")
                                self.observe("RESULTS", 1)
                        state = ""
                    else:
                        self.victory_frames = 0
                    if self.detection.candidate:
                        self.state_scores[self.detection.candidate] = f"{self.confidence:.0%}"
                    if state and state != self.match.state and state not in TRANSITIONS[self.match.state]:
                        self.detection = replace(self.detection, reason="Переход из текущего состояния не подтверждён")
                    if self.detection.reason and self.detection.candidate:
                        self.recognition_misses += 1
                        if self.recognition_misses == 12 and self.telegram:
                            self.telegram.notice("recognition", self.notification_session)
                    else:
                        self.recognition_misses = 0
                    self.observe(state, 3)
                    if state and state == self.match.state:
                        self.last_detected[state] = datetime.now().strftime("%H:%M:%S")
                        if state == "SPECTATING" and self.match.spectating_since is None:
                            self.match.spectating_since = self.active_time()
        if self.session is None or self.paused:
            return
        now = monotonic()
        if now >= self.next_step:
            if self.mode == "sim":
                index = (self.stage + 1) % len(STAGES)
                if index == 0:
                    self.stage = 0
                    self.log("Лобби")
                    if self.match.state != "LOBBY":
                        self.observe("LOBBY", 1)
                    if self.match.completed and not self.config["repeat"]:
                        self.stop("Тест завершён")
                        return
                else:
                    self.observe(STAGES[index][0], 1)
                self.next_step = now + 6 / (self.config["speed"] + 1)
            elif self.future is None:
                self.job_generation = self.generation
                self.future = self.executor.submit(process_frame, self.window, self.patterns,
                                                   self.config["threshold"] / 100, self.state_thresholds,
                                                   self.match.state, self.cancelled)
                self.next_step = now + 0.65
        elapsed = int(self.active_time())
        if elapsed != self.last_checkpoint:
            self.checkpoint("Активна")
            self.last_checkpoint = elapsed
            self.libraryChanged.emit()
        self.changed.emit()

    @Slot(str)
    def simulateKey(self, key):
        if self.mode == "sim" and self.session is not None and not self.paused and self.match.state == "IN_MATCH":
            actions = {"W": "Вперёд", "A": "Влево", "S": "Назад", "D": "Вправо"}
            if key in actions:
                self.action = actions[key]
                self.log(f"Симулятор: {self.action}")
                self.changed.emit()

    @Slot(int, int, bool, str)
    def saveSettings(self, speed, threshold, repeat, stop_key):
        if stop_key not in STOP_KEYS:
            self.notify.emit("Недопустимая клавиша остановки")
            return
        if self.hotkey and stop_key != self.config["stopKey"]:
            self.hotkey.register(stop_key)
        self.config.update(speed=speed, threshold=threshold, repeat=repeat, stopKey=stop_key)
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config), encoding="utf-8")
        temporary.replace(self.settings_path)
        self.settingsChanged.emit()
        self.notify.emit("Настройки сохранены")

    @Slot(str, int, int)
    def addGoal(self, name, progress, target):
        if not name.strip() or target < 1 or progress < 0:
            return
        with self.db:
            key = self.db.execute("INSERT INTO goals(name,progress,target) VALUES (?,?,?)",
                                  (name.strip(), progress, target)).lastrowid
        self.baseline[key] = progress
        self.libraryChanged.emit()

    @Slot(int, int)
    def updateGoal(self, key, value):
        self.record_goal(key, value, True)

    @Slot(int, int)
    def proposeGoal(self, key, value):
        self.record_goal(key, value, False)

    def record_goal(self, key, value, confirmed):
        row = self.db.execute("SELECT progress FROM goals WHERE id=?", (key,)).fetchone()
        if row is None:
            return
        value = max(0, value)
        with self.db:
            self.db.execute("DELETE FROM goal_events WHERE goal_id=? AND confirmed=0", (key,))
            if confirmed:
                self.db.execute("UPDATE goals SET progress=? WHERE id=?", (value, key))
            self.db.execute(
                "INSERT INTO goal_events(goal_id, session_id, date, before, after, confirmed) VALUES(?,?,?,?,?,?)",
                (key, self.session, datetime.now().isoformat(timespec="seconds"), row["progress"], value, confirmed))
        self.libraryChanged.emit()

    @Slot(int)
    def removeGoal(self, key):
        with self.db:
            self.db.execute("DELETE FROM goal_events WHERE goal_id=?", (key,))
            self.db.execute("DELETE FROM goals WHERE id=?", (key,))
        self.libraryChanged.emit()

    @Slot(QUrl, str, int, int, int, int, int)
    def importTemplate(self, source, state, reference_width, x, y, w, h):
        if state not in LABELS:
            return
        try:
            frame = load_gray(source.toLocalFile())
            if w and h:
                if x < 0 or y < 0 or x+w > frame.shape[1] or y+h > frame.shape[0]:
                    raise ValueError("Область выходит за границы изображения")
                frame = frame[y:y+h, x:x+w]
            if min(frame.shape) < 6 or frame.std() < 2 or reference_width < frame.shape[1]:
                raise ValueError("Выберите контрастную область и укажите ширину полного кадра")
            from uuid import uuid4
            name = f"template-{uuid4().hex}.png"
            encoded, data = cv2.imencode(".png", frame)
            if not encoded:
                raise ValueError("Не удалось сохранить шаблон")
            (self.directory / name).write_bytes(data.tobytes())
            with self.db:
                self.db.execute("INSERT INTO templates(name,state,reference_width,path) VALUES(?,?,?,?)",
                                (Path(source.toLocalFile()).name, state, reference_width, name))
        except (OSError, ValueError, cv2.error) as error:
            self.notify.emit(str(error))
            return
        self.template_counts = self.count_templates(self.templates)
        self.changed.emit()
        self.libraryChanged.emit()
        self.notify.emit("Шаблон сохранён")

    @Slot(int)
    def removeTemplate(self, key):
        row = self.db.execute("SELECT path FROM templates WHERE id=?", (key,)).fetchone()
        if row:
            with self.db:
                self.db.execute("DELETE FROM templates WHERE id=?", (key,))
            (self.directory / row["path"]).unlink(missing_ok=True)
            self.template_counts = self.count_templates(self.templates)
            self.changed.emit()
            self.libraryChanged.emit()

    @Slot(QUrl)
    def exportHistory(self, url):
        columns = ("date", "mode", "games", "cycles", "seconds", "match_seconds", "spectating_seconds", "errors", "result")
        try:
            with Path(url.toLocalFile()).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(columns)
                writer.writerows(tuple(row[key] for key in columns) for row in self.history)
            self.notify.emit("CSV сохранён")
        except OSError as error:
            self.notify.emit(str(error))

    @Slot()
    def clearLogs(self):
        with self.db:
            self.db.execute("DELETE FROM logs")
        self.libraryChanged.emit()

    @Slot()
    def reset(self):
        if self.session is None:
            with self.db:
                self.db.execute("UPDATE goal_events SET session_id=NULL")
                self.db.execute("DELETE FROM sessions")
            self.match = Match()
            self.elapsed, self.stage = 0, -1
            self.libraryChanged.emit()
            self.changed.emit()

    def close(self):
        if self.hotkey:
            self.hotkey.close()
        self.timer.stop()
        self.stop("Закрыто")
        if self.telegram:
            self.telegram.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.db.close()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("ShadowAFK")
    app.setApplicationName("Shadow AFK")
    app.setQuitOnLastWindowClosed(False)
    ui = Path(__file__).parent / "ui"
    icon = QIcon(str(ui / "shadow.png"))
    app.setWindowIcon(icon)
    smoke = "--smoke" in sys.argv
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    if smoke:
        from tempfile import TemporaryDirectory
        temporary = TemporaryDirectory()
        directory = Path(temporary.name)
    controller = Controller(directory)
    telegram = Telegram(directory, offline=smoke)
    controller.telegram = telegram
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("telegram", telegram)
    engine.addImageProvider("capture", controller.preview)
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(ui / "Main.qml")))
    if not engine.rootObjects():
        controller.close()
        return 1
    window = engine.rootObjects()[0]
    if smoke:
        for page in range(1, 8):
            window.setProperty("page", page)
            app.processEvents()
        window.setProperty("page", 0)
    tray = QSystemTrayIcon(icon, app)
    menu = QMenu()
    menu.addAction("Открыть", window.showNormal)
    menu.addAction("Стоп", lambda: controller.stop())
    menu.addAction("Выход", app.quit)
    tray.setContextMenu(menu)
    tray.setToolTip("Shadow AFK")
    tray.activated.connect(lambda reason: window.showNormal() if reason == QSystemTrayIcon.Trigger else None)
    window.setProperty("trayAvailable", QSystemTrayIcon.isSystemTrayAvailable() and not smoke)
    if window.property("trayAvailable"):
        tray.show()
        controller.notify.connect(lambda message: tray.showMessage("Shadow AFK", message) if not window.isVisible() else None)
    if sys.platform == "win32" and not smoke:
        controller.hotkey = EmergencyHotkey(app, controller)
        controller.hotkey.register(controller.settings["stopKey"])
        controller.settingsChanged.emit()
    app.aboutToQuit.connect(controller.close)
    if smoke:
        QTimer.singleShot(350, app.quit)
    result = app.exec()
    del engine
    return result
