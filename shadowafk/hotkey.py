"""Register the emergency stop with Windows without intercepting game input."""
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

    def nativeEventFilter(self, event_type, message):
        if self.registered and bytes(event_type) == b"windows_dispatcher_MSG":
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312 and event.wParam == self.key_id:
                self.controller.stop()
                return True, 0
        return False, 0

    def unregister(self):
        if self.registered:
            self.user.UnregisterHotKey(None, self.key_id)
            self.registered = False

    def close(self):
        self.unregister()
        self.app.removeNativeEventFilter(self)
