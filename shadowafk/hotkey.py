"""Register global shortcuts through the Windows hotkey API."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

STOP_KEYS = {"Ctrl+Alt+Q": (0x0003, ord("Q")),
             "Ctrl+Shift+Q": (0x0006, ord("Q")),
             "Ctrl+C": (0x0002, ord("C"))}


class EmergencyHotkey(QAbstractNativeEventFilter):
    key_id = 1

    def __init__(self, app, controller):
        super().__init__()
        self.app = app
        self.controller = controller
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.registered = False
        self.studio_keys = {}
        app.installNativeEventFilter(self)

    def register(self, sequence):
        self.unregister()
        if sequence == "Ctrl+C":
            return False  # Preserve copy in other Windows applications.
        modifiers, key = STOP_KEYS[sequence]
        self.registered = bool(self.user.RegisterHotKey(None, self.key_id, modifiers | 0x4000, key))
        if not self.registered:
            self.controller.log("Глобальная клавиша остановки недоступна: " + sequence)
            self.controller.notify.emit("Глобальная клавиша занята. Используйте «Стоп» в приложении.")
        return self.registered

    def register_studio(self, studio):
        shortcuts = [studio.toggle, lambda: studio.record("play"),
                     lambda: studio.record("replay"), self.app.quit]
        for number, callback in enumerate(shortcuts, start=6):
            if self.user.RegisterHotKey(None, number, 0x4000, 0x70 + number - 1):
                self.studio_keys[number] = callback
            else:
                self.controller.log(f"Глобальная клавиша F{number} занята")

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_dispatcher_MSG":
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312:
                if self.registered and event.wParam == self.key_id:
                    self.controller.stop()
                    return True, 0
                callback = self.studio_keys.get(event.wParam)
                if callback:
                    callback()
                    return True, 0
        return False, 0

    def unregister(self):
        if self.registered:
            self.user.UnregisterHotKey(None, self.key_id)
            self.registered = False

    def close(self):
        self.unregister()
        for number in self.studio_keys:
            self.user.UnregisterHotKey(None, number)
        self.studio_keys.clear()
        self.app.removeNativeEventFilter(self)
