from PySide6.QtWidgets import QApplication

from shadowafk import telegram


def test_telegram_binding_survives_client_restart(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("SHADOW_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SHADOW_SUPABASE_KEY", "sb_publishable_test")
    calls = []
    opened = []
    link = "https://t.me/ShadowExampleBot?start=" + "a" * 64

    def request(self, path, payload, callback, access=None):
        calls.append((path, payload, access))
        if path == "/auth/v1/signup":
            callback(200, {"access_token": "install-token", "refresh_token": "refresh"})
        elif payload["action"] == "begin":
            callback(200, {"state": "pending", "link": link})
        elif payload["action"] == "unlink":
            callback(200, {"state": "disconnected"})
        else:
            callback(200, {"state": "connected", "name": "Alice", "binding": "binding", "events": []})

    monkeypatch.setattr(telegram.Telegram, "request", request)
    monkeypatch.setattr(telegram.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    first = telegram.Telegram(tmp_path)
    first.begin()
    assert opened == [link]
    assert first.status["state"] == "pending"
    assert link not in first.credentials.read_text(encoding="utf-8")
    first.poll()
    assert first.status["name"] == "Alice"
    first.close()

    second = telegram.Telegram(tmp_path)
    second.poll()
    assert second.status["state"] == "connected"
    second.testNotice()
    assert calls[-1][1]["binding"] == "binding"
    assert calls[-1][2] == "install-token"
    second.unlink()
    assert second.status["state"] == "disconnected"
    assert sum(path == "/auth/v1/signup" for path, _, _ in calls) == 1
    second.close()
