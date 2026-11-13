"""Read pixels from the visible Windows desktop via standard screen capture."""
import sys
from enum import StrEnum
from functools import lru_cache
from pathlib import PureWindowsPath

import cv2
import numpy as np



class CaptureState(StrEnum):
    NO_FRAME = "NO_FRAME"
    WINDOW_NOT_ACTIVE = "WINDOW_NOT_ACTIVE"
    WINDOW_MINIMIZED = "WINDOW_MINIMIZED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    CAPTURE_ERROR = "CAPTURE_ERROR"
    FRAME_AVAILABLE = "FRAME_AVAILABLE"


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = [
        (user, "GetWindowThreadProcessId", wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        (user, "GetWindowTextW", ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        (user, "IsIconic", wintypes.BOOL, [wintypes.HWND]),
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


def is_fortnite(pid):
    ctypes, types, _, kernel = _windows_api()
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    try:
        path = ctypes.create_unicode_buffer(32768)
        length = types.DWORD(len(path))
        if not kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
            return False
        executable = PureWindowsPath(path.value)
        return executable.suffix.casefold() == ".exe" and executable.stem.casefold().startswith("fortniteclient-win64-")
    finally:
        kernel.CloseHandle(process)


def windows():
    if sys.platform != "win32":
        return []
    ctypes, types, user, _ = _windows_api()
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
        if is_fortnite(pid.value):
            entries.append({"handle": handle, "pid": pid.value, "title": title.value})
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
        return CaptureState.WINDOW_CLOSED, None
    if user.IsIconic(handle):
        return CaptureState.WINDOW_MINIMIZED, None
    if user.GetForegroundWindow() != handle:
        return CaptureState.WINDOW_NOT_ACTIVE, None
    if not is_fortnite(expected_pid):
        return CaptureState.WINDOW_CLOSED, None
    set_dpi = user.SetThreadDpiAwarenessContext
    set_dpi.argtypes = [ctypes.c_void_p]
    set_dpi.restype = ctypes.c_void_p
    previous = set_dpi(ctypes.c_void_p(-4))  # Per-monitor aware v2.
    try:
        return capture_client(handle, ctypes, types, user, mss)
    finally:
        if previous:
            set_dpi(previous)


def capture_client(handle, ctypes, types, user, mss):
    rect, origin = types.RECT(), types.POINT()
    if not user.GetClientRect(handle, ctypes.byref(rect)) or not user.ClientToScreen(handle, ctypes.byref(origin)):
        return CaptureState.CAPTURE_ERROR, None
    width, height = rect.right, rect.bottom
    with mss() as screen:
        desktop = screen.monitors[0]
        if (min(width, height) <= 0 or origin.x < desktop["left"] or origin.y < desktop["top"]
                or origin.x + width > desktop["left"] + desktop["width"]
                or origin.y + height > desktop["top"] + desktop["height"]):
            return CaptureState.CAPTURE_ERROR, None
        pixels = np.asarray(screen.grab(dict(left=origin.x, top=origin.y, width=width, height=height)))
    if user.GetForegroundWindow() != handle:
        return CaptureState.WINDOW_NOT_ACTIVE, None
    current_rect, current_origin = types.RECT(), types.POINT()
    if (not user.GetClientRect(handle, ctypes.byref(current_rect))
            or not user.ClientToScreen(handle, ctypes.byref(current_origin))
            or (current_origin.x, current_origin.y, current_rect.right, current_rect.bottom)
            != (origin.x, origin.y, width, height)):
        return CaptureState.NO_FRAME, None
    frame = cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
    if frame.max() < 8:
        return CaptureState.NO_FRAME, None
    return CaptureState.FRAME_AVAILABLE, frame
