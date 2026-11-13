"""Standard Windows keyboard and mouse input for the foreground game."""
import ctypes as ct
from ctypes import wintypes as wt

from shadowafk.capture import _windows_api


class MouseInput(ct.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG), ("data", wt.DWORD),
                ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ct.c_size_t)]


class KeyInput(ct.Structure):
    _fields_ = [("vk", wt.WORD), ("scan", wt.WORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("extra", ct.c_size_t)]


class InputValue(ct.Union):
    _fields_ = [("mouse", MouseInput), ("key", KeyInput)]


class Input(ct.Structure):
    _fields_ = [("kind", wt.DWORD), ("value", InputValue)]


class WindowsInput:
    def __init__(self):
        _, _, self.user, _ = _windows_api()
        declarations = [
            ("SendInput", wt.UINT, [wt.UINT, ct.POINTER(Input), ct.c_int]),
            ("MapVirtualKeyW", wt.UINT, [wt.UINT, wt.UINT]),
            ("GetPhysicalCursorPos", wt.BOOL, [ct.POINTER(wt.POINT)]),
            ("SetPhysicalCursorPos", wt.BOOL, [ct.c_int, ct.c_int]),
            ("GetSystemMetrics", ct.c_int, [ct.c_int]),
            ("SetThreadDpiAwarenessContext", ct.c_void_p, [ct.c_void_p]),
        ]
        for name, result, arguments in declarations:
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, arguments

    def focused(self, window):
        handle = window["handle"]
        if self.user.GetForegroundWindow() != handle or self.user.IsIconic(handle):
            return False
        pid = wt.DWORD()
        self.user.GetWindowThreadProcessId(handle, ct.byref(pid))
        return pid.value == window["pid"]

    def geometry(self, window):
        handle = window["handle"]
        previous = self.user.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
        try:
            origin, rect = wt.POINT(), wt.RECT()
            if self.user.GetClientRect(handle, ct.byref(rect)) and self.user.ClientToScreen(handle, ct.byref(origin)):
                return origin.x, origin.y, rect.right, rect.bottom
            return None
        finally:
            if previous:
                self.user.SetThreadDpiAwarenessContext(previous)

    def primary_size(self):
        previous = self.user.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
        try:
            return self.user.GetSystemMetrics(0), self.user.GetSystemMetrics(1)
        finally:
            if previous:
                self.user.SetThreadDpiAwarenessContext(previous)

    def send(self, *inputs):
        return self.user.SendInput(len(inputs), (Input * len(inputs))(*inputs), ct.sizeof(Input))

    def key(self, vk, release=False):
        scan = self.user.MapVirtualKeyW(vk, 0)
        flags = 0x0008 | (0x0002 if release else 0)
        return bool(scan and self.send(Input(1, InputValue(key=KeyInput(scan=scan, flags=flags)))))

    def cursor(self):
        point = wt.POINT()
        if self.user.GetPhysicalCursorPos(ct.byref(point)):
            return point.x, point.y
        return None

    def move_cursor(self, point):
        return self.user.SetPhysicalCursorPos(*point)

    def click(self, window, geometry, point):
        if not self.focused(window) or self.geometry(window) != geometry or not self.move_cursor(point):
            return False
        if not self.focused(window) or self.cursor() != point:
            return False
        down = Input(0, InputValue(mouse=MouseInput(flags=0x0002)))
        up = Input(0, InputValue(mouse=MouseInput(flags=0x0004)))
        sent = self.send(down, up)
        if sent == 1:
            self.send(up)
        return sent == 2
