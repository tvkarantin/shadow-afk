import csv
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from time import monotonic

import cv2
from PySide6.QtCore import QObject, Property, QStandardPaths, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from shadowafk.capture import capture, windows
from shadowafk.match import LABELS, STAGES, Match, load_gray, recognize


def process_frame(window, templates, threshold):
    error, frame = capture(window["handle"], window["pid"])
    if frame is None:
        return error, 0, None
    state, confidence, box = recognize(frame, templates, threshold)
    if box:
        x, y, w, h = box
        cv2.rectangle(frame, (x, y), (x+w, y+h), 255, max(2, frame.shape[1] // 500))
    if frame.shape[1] > 800:
        frame = cv2.resize(frame, (800, round(frame.shape[0] * 800 / frame.shape[1])))
    height, width = frame.shape
    preview = QImage(frame.tobytes(), width, height, width, QImage.Format_Grayscale8)
    return state, confidence, preview.copy()


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
            CREATE TABLE IF NOT EXISTS templates(id INTEGER PRIMARY KEY, name TEXT, state TEXT,
                reference_width INTEGER, path TEXT);
            UPDATE sessions SET result='Прервано' WHERE result='Активна';
        """)
        self.settings_path = directory / "settings.json"
        self.config = {"speed": 3, "threshold": 85, "repeat": True, "stopKey": "Ctrl+Alt+Q"}
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.config.update(speed=max(1, min(5, int(saved["speed"]))),
                               threshold=max(50, min(99, int(saved["threshold"]))),
                               repeat=bool(saved["repeat"]), stopKey=saved.get("stopKey", "Ctrl+Alt+Q"))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.generation = 0
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
        elif self.mode == "live" and not self.preview_visible and self.match.state not in {"ERROR", "GAME_NOT_FOUND"}:
            hint = "Ожидание видимого кадра Fortnite"
        return dict(active=active, paused=self.paused, title=title, hint=hint, games=self.match.detected,
                    cycles=self.match.completed, seconds=int(self.active_time()), stage=self.stage,
                    mode=self.mode, state=self.match.state, confidence=self.confidence, action=self.action,
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
        return rows

    @Property("QVariantList", notify=libraryChanged)
    def templates(self):
        rows = self.rows("SELECT * FROM templates ORDER BY id DESC")
        for row in rows:
            row["url"] = QUrl.fromLocalFile(str(self.directory / row["path"])).toString()
        return rows

    @Property("QVariantList", notify=changed)
    def windowTitles(self):
        return [row["title"] for row in self.window_list]

    @Property(bool, constant=True)
    def windowsSupported(self):
        return sys.platform == "win32"

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
        self.changed.emit()

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
            for row in self.templates:
                try:
                    self.patterns.append((row["state"], load_gray(self.directory / row["path"]), row["reference_width"]))
                except (OSError, ValueError, cv2.error):
                    self.log(f"Недоступен шаблон: {row['name']}")
            if not self.patterns:
                self.notify.emit("Добавьте хотя бы один шаблон состояния")
                return
        self.mode = mode
        self.match = Match(state="GAME_NOT_FOUND" if mode == "live" else "LOBBY")
        self.stage = -1
        self.elapsed = self.errors = self.confidence = 0
        self.baseline = {row["id"]: row["progress"] for row in self.goals}
        self.action = ""
        self.preview_visible = False
        self.generation += 1
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

    @Slot()
    def pause(self):
        if self.session is None:
            return
        self.generation += 1
        self.paused = not self.paused
        if self.paused:
            self.elapsed = self.active_time()
            self.clock = None
        else:
            self.clock = monotonic()
            self.next_step = self.clock
        self.match.pending, self.match.confirmations = "", 0
        self.log("На паузе" if self.paused else "Сессия возобновлена")
        self.changed.emit()

    def checkpoint(self, result):
        now = self.active_time()
        spectating = self.match.spectating_seconds
        if self.match.state == "SPECTATING":
            spectating += now - self.match.changed_at
        with self.db:
            self.db.execute(
                "UPDATE sessions SET games=?, cycles=?, seconds=?, match_seconds=?, spectating_seconds=?, errors=?, result=? WHERE id=?",
                (self.match.detected, self.match.completed, int(now), self.match.match_seconds,
                 spectating, self.errors, result, self.session))

    @Slot()
    def stop(self, result="Остановлено"):
        if self.session is None:
            return
        self.generation += 1
        self.checkpoint(result)
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
            if state == "ERROR":
                self.errors += 1
            self.log(LABELS[state][0])
            if state == "RESULTS" and self.mode == "live":
                self.notify.emit("Матч завершён. Проверьте результаты в Fortnite.")

    def tick(self):
        if self.future is not None and self.future.done():
            job, generation = self.future, self.job_generation
            self.future = None
            if generation == self.generation:
                try:
                    state, self.confidence, frame = job.result()
                except Exception as error:
                    self.log(f"Ошибка захвата: {error}")
                    state, self.confidence, frame = "ERROR", 0, None
                self.preview_visible = frame is not None
                if self.preview_visible:
                    self.preview.frame = frame
                    self.preview_revision += 1
                self.observe(state, 3)
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
                                                   self.config["threshold"] / 100)
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
        self.config = dict(speed=speed, threshold=threshold, repeat=repeat, stopKey=stop_key)
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
        with self.db:
            self.db.execute("UPDATE goals SET progress=? WHERE id=?", (max(0, value), key))
        self.libraryChanged.emit()

    @Slot(int)
    def removeGoal(self, key):
        with self.db:
            self.db.execute("DELETE FROM goals WHERE id=?", (key,))
        self.libraryChanged.emit()

    @Slot(QUrl, str, int, int, int, int, int)
    def importTemplate(self, source, state, reference_width, x, y, w, h):
        if state not in {item[0] for item in STAGES}:
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
        self.libraryChanged.emit()
        self.notify.emit("Шаблон сохранён")

    @Slot(int)
    def removeTemplate(self, key):
        row = self.db.execute("SELECT path FROM templates WHERE id=?", (key,)).fetchone()
        if row:
            with self.db:
                self.db.execute("DELETE FROM templates WHERE id=?", (key,))
            (self.directory / row["path"]).unlink(missing_ok=True)
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
                self.db.execute("DELETE FROM sessions")
            self.match = Match()
            self.elapsed, self.stage = 0, -1
            self.libraryChanged.emit()
            self.changed.emit()

    def close(self):
        self.timer.stop()
        self.stop("Закрыто")
        self.executor.shutdown(wait=True, cancel_futures=True)
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
    engine = QQmlApplicationEngine()
    engine.addImageProvider("capture", controller.preview)
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(ui / "Main.qml")))
    if not engine.rootObjects():
        controller.close()
        return 1
    window = engine.rootObjects()[0]
    if smoke:
        for page in range(1, 7):
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
    app.aboutToQuit.connect(controller.close)
    if smoke:
        QTimer.singleShot(350, app.quit)
    result = app.exec()
    del engine
    return result
