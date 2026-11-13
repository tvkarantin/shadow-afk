"""Asynchronous Telegram setup through the installation's Supabase Auth session."""
import json
import os
from pathlib import Path
from time import time
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtCore import QByteArray, QEventLoop, QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

EVENTS = {
    "victory": "Подтверждённая королевская победа",
    "recognition": "Ошибка распознавания",
    "fortnite_exit": "Возможный сбой Fortnite",
    "app_error": "Ошибка Shadow AFK",
    "offline": "Потеря связи с приложением",
    "summary": "Итог сессии",
}


class Telegram(QObject):
    changed = Signal()

    def __init__(self, directory, offline=False):
        super().__init__()
        config_path = Path(__file__).with_name("ui") / "telegram-config.json"
        config = self.read(config_path)
        self.url = os.getenv("SHADOW_SUPABASE_URL", config.get("url", "")).rstrip("/")
        self.key = os.getenv("SHADOW_SUPABASE_KEY", config.get("publishable_key", ""))
        self._offline = offline
        self.configured = not offline and self.url.startswith("https://") and self.key.startswith("sb_publishable_")
        self.credentials = directory / "telegram-session.json"
        self.auth = self.read(self.credentials) if self.configured else {}
        if self.auth.get("project") != self.url:
            self.auth = {}
        self.network = QNetworkAccessManager(self)
        self.queue = []
        self.busy = False
        self.remote = {}
        self.link = ""
        self.intent = "either"
        self.error = ""
        self.next_heartbeat = 0
        self.next_status = 0
        self.timer = QTimer(self, interval=2500)
        self.timer.timeout.connect(self.poll)
        if self.configured:
            self.timer.start()
            QTimer.singleShot(0, self.poll)

    @staticmethod
    def read(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @Property(bool, constant=True)
    def offline(self):
        return self._offline

    @Property("QVariantMap", notify=changed)
    def status(self):
        selected = self.remote.get("events", [])
        return dict(configured=self.configured, busy=self.busy, state=self.remote.get("state", "disconnected"),
                    name=self.remote.get("name") or "", error=self.error,
                    events=[dict(key=key, label=label, enabled=key in selected) for key, label in EVENTS.items()])

    def request(self, path, payload, callback, access=None):
        request = QNetworkRequest(QUrl(self.url + path))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"apikey", self.key.encode())
        request.setTransferTimeout(8000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        if access:
            request.setRawHeader(b"Authorization", ("Bearer " + access).encode())
        reply = self.network.post(request, QByteArray(json.dumps(payload).encode()))

        def finished():
            code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
            try:
                data = json.loads(bytes(reply.readAll()))
            except ValueError:
                data = {}
            reply.deleteLater()
            callback(code, data if isinstance(data, dict) else {})

        reply.finished.connect(finished)

    def enqueue(self, action, **payload):
        if not self.configured or len(self.queue) >= 40:
            return
        self.queue.append(dict(action=action, **payload))
        self.advance()

    def advance(self):
        if self.busy or not self.queue:
            return
        self.busy = True
        self.changed.emit()
        payload = self.queue[0]
        if self.auth.get("expires_at", 0) > time() + 30 and self.auth.get("access_token"):
            self.call(payload)
        elif self.auth.get("refresh_token"):
            self.request("/auth/v1/token?grant_type=refresh_token",
                         {"refresh_token": self.auth["refresh_token"]}, self.signed_in)
        elif payload["action"] == "begin":
            self.request("/auth/v1/signup", {}, self.signed_in)
        else:
            self.finish()

    def signed_in(self, code, data):
        if code == 200 and data.get("access_token") and data.get("refresh_token"):
            self.auth = dict(access_token=data["access_token"], refresh_token=data["refresh_token"],
                             expires_at=time() + int(data.get("expires_in", 3600)), project=self.url)
            temporary = self.credentials.with_suffix(".tmp")
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self.auth, stream)
                temporary.replace(self.credentials)
            except OSError:
                self.finish("Не удалось сохранить сессию установки")
                return
            self.call(self.queue[0])
        else:
            if code in (400, 401, 403) and self.auth:
                self.auth = {}
                try:
                    self.credentials.unlink(missing_ok=True)
                except OSError:
                    pass
                self.remote = {}
                self.link = ""
            self.finish("Не удалось авторизовать установку в Supabase")

    def call(self, payload):
        self.request("/functions/v1/telegram", payload, self.result, self.auth["access_token"])

    def result(self, code, data):
        action = self.queue[0]["action"]
        if code == 200:
            previous = self.remote.get("state")
            self.link = data.pop("link", "") if action == "begin" else self.link
            self.remote = data
            if action == "begin":
                self.openTelegram()
            elif data.get("state") != "pending":
                self.link = ""
            expired = (action == "status" and previous == "pending"
                       and data.get("state") == "disconnected")
            message = {
                "register": "Регистрация не завершена. Если аккаунт уже есть, выберите вход.",
                "login": "Вход не завершён. Если аккаунта ещё нет, выберите регистрацию.",
            }.get(self.intent, "Срок ссылки истёк")
            self.finish(message if expired else self.error if action == "status" and previous == "disconnected" else "")
            return
        if code == 401:
            self.auth["expires_at"] = 0
        messages = {
            "rate_limited": "Подождите несколько секунд и попробуйте снова",
            "delivery_failed": "Telegram не принял уведомление",
            "not_linked": "Привязка изменилась. Дождитесь обновления статуса",
            "bot_unconfigured": "Общий бот пока не настроен",
        }
        self.finish(messages.get(data.get("error"), "Не удалось связаться с сервисом Telegram"))

    def finish(self, error=""):
        self.queue.pop(0)
        self.error = error
        self.busy = False
        self.changed.emit()
        self.advance()

    def poll(self):
        if self.busy or not self.auth:
            return
        if self.remote.get("state") == "connected" and time() >= self.next_heartbeat:
            self.next_heartbeat = time() + 45
            self.enqueue("heartbeat")
        elif self.remote.get("state") == "pending" or time() >= self.next_status:
            self.next_status = time() + 30
            self.enqueue("status")

    def close(self):
        self.timer.stop()
        if not self.busy:
            return
        loop = QEventLoop()
        def drain():
            if not self.busy and not self.queue:
                loop.quit()
        self.changed.connect(drain)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(4000)
        loop.exec()
        self.changed.disconnect(drain)

    @Slot()
    def begin(self):
        self.enqueue("begin")

    @Slot(str)
    def startAccount(self, intent):
        self.intent = intent
        self.enqueue("begin", intent=intent)

    @Slot()
    def openTelegram(self):
        if not self.link:
            self.startAccount(self.intent)
            return
        url = urlsplit(self.link)
        if url.scheme == "https" and url.netloc == "t.me":
            QDesktopServices.openUrl(QUrl(self.link))

    @Slot()
    def cancel(self):
        self.enqueue("cancel")

    @Slot()
    def unlink(self):
        self.enqueue("unlink")

    @Slot()
    def testNotice(self):
        self.notice("test")

    @Slot(str, bool)
    def preference(self, key, enabled):
        events = set(self.remote.get("events", []))
        if enabled:
            events.add(key)
        else:
            events.discard(key)
        self.enqueue("preferences", events=sorted(events))

    def notice(self, event, key=None, **payload):
        binding = self.remote.get("binding")
        if binding and (event == "test" or event in self.remote.get("events", [])):
            self.enqueue("notify", event=event, key=key or uuid4().hex, binding=binding, **payload)
