"""Read pixels from the visible Windows desktop via standard screen capture."""
import sys
from pathlib import PureWindowsPath

import cv2
import numpy as np


def _windows_api():
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = [
        (user, "GetWindowThreadProcessId", wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        (user, "GetWindowTextW", ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        (user, "IsWindowVisible", wintypes.BOOL, [wintypes.HWND]),
        (user, "GetForegroundWindow", wintypes.HWND, []),
        (user, "GetClientRect", wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
        (user, "ClientToScreen", wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]),
        (kernel, "OpenProcess", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
        (kernel, "QueryFullProcessImageNameW", wintypes.BOOL,
         [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]),
        (kernel, "CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
    ]
    for library, name, result, args in declarations:
        function = getattr(library, name)
        function.restype, function.argtypes = result, args
    return ctypes, wintypes, user, kernel


def windows():
    if sys.platform != "win32":
        return []
    ctypes, types, user, kernel = _windows_api()
    entries = []
    callback = ctypes.WINFUNCTYPE(types.BOOL, types.HWND, types.LPARAM)

    @callback
    def visit(handle, unused):
        title = ctypes.create_unicode_buffer(512)
        if not user.IsWindowVisible(handle) or not user.GetWindowTextW(handle, title, len(title)):
            return True
        if "fortnite" not in title.value.casefold():
            return True
        pid = types.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process = kernel.OpenProcess(0x1000, False, pid.value)  # Query image name only.
        if process:
            try:
                path = ctypes.create_unicode_buffer(32768)
                length = types.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                    if PureWindowsPath(path.value).name.casefold().startswith("fortniteclient-win64-"):
                        entries.append({"handle": handle, "pid": pid.value, "title": title.value})
            finally:
                kernel.CloseHandle(process)
        return True

    user.EnumWindows.argtypes = [callback, types.LPARAM]
    user.EnumWindows.restype = types.BOOL
    user.EnumWindows(visit, 0)
    return entries


def capture(handle, expected_pid):
    from mss import mss

    ctypes, types, user, _ = _windows_api()
    pid = types.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    if pid.value != expected_pid:
        return "GAME_NOT_FOUND", None
    if user.GetForegroundWindow() != handle:
        return "", None
    rect, origin = types.RECT(), types.POINT()
    if not user.GetClientRect(handle, ctypes.byref(rect)) or not user.ClientToScreen(handle, ctypes.byref(origin)):
        return "ERROR", None
    width, height = rect.right, rect.bottom
    with mss() as screen:
        desktop = screen.monitors[0]
        if (min(width, height) <= 0 or origin.x < desktop["left"] or origin.y < desktop["top"]
                or origin.x + width > desktop["left"] + desktop["width"]
                or origin.y + height > desktop["top"] + desktop["height"]):
            return "ERROR", None
        pixels = np.asarray(screen.grab(dict(left=origin.x, top=origin.y, width=width, height=height)))
    if user.GetForegroundWindow() != handle:
        return "", None
    frame = cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
    if frame.max() < 8:
        return "ERROR", None
    return "", frame
