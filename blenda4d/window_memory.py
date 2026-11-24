# SPDX-License-Identifier: GPL-3.0-or-later
"""Blenda remembers the window: its place and size are kept while Blender runs and put back when Blenda starts.

Blender itself opens every session at the window its startup file has (maximized on a fresh install). macOS: through
the window's own frame (a full-screen window is left alone); Windows: through user32 (a maximized window comes back
maximized); Linux: the window manager places Blender's window, as before."""
import ctypes
import json
import os
import sys

import bpy

SAVE_EVERY = 2.0
FILE = "window.json"
_state = {"frame": None, "applied": False}


def _path():
    try:
        return os.path.join(bpy.utils.user_resource("CONFIG", path="blenda4d", create=True), FILE)
    except Exception:
        return None


def _read():
    try:
        with open(_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return None


def _write(data):
    p = _path()
    if not p:
        return
    try:
        with open(p + ".tmp", "w") as fh:
            json.dump(data, fh)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


# --- the window -----------------------------------------------------------------------------------------------------

MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"

if MAC:
    _objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    _objc.objc_getClass.restype = ctypes.c_void_p
    _objc.sel_registerName.restype = ctypes.c_void_p

    class _Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

    def _msg(res, *types):
        return ctypes.CFUNCTYPE(res, ctypes.c_void_p, ctypes.c_void_p, *types)(("objc_msgSend", _objc))

    def _main_window():
        app = _msg(ctypes.c_void_p)(_objc.objc_getClass(b"NSApplication"), _objc.sel_registerName(b"sharedApplication"))
        wins = _msg(ctypes.c_void_p)(app, _objc.sel_registerName(b"windows"))
        best, area = None, -1.0
        for i in range(_msg(ctypes.c_ulong)(wins, _objc.sel_registerName(b"count"))):
            w = _msg(ctypes.c_void_p, ctypes.c_ulong)(wins, _objc.sel_registerName(b"objectAtIndex:"), i)
            f = _msg(_Rect)(w, _objc.sel_registerName(b"frame"))
            if f.w * f.h > area:
                best, area = w, f.w * f.h
        return best

    def _is_full(w):
        mask = _msg(ctypes.c_ulong)(w, _objc.sel_registerName(b"styleMask"))
        return bool(mask & (1 << 14))                         # NSWindowStyleMaskFullScreen

    def get_frame():
        w = _main_window()
        if not w or _is_full(w):                              # a full-screen window keeps the size it had before
            return None
        f = _msg(_Rect)(w, _objc.sel_registerName(b"frame"))
        return [f.x, f.y, f.w, f.h]

    def set_frame(frame):
        w = _main_window()
        if w and frame and not _is_full(w):
            _msg(None, _Rect, ctypes.c_byte)(w, _objc.sel_registerName(b"setFrame:display:"), _Rect(*frame), 1)

elif WIN:
    from ctypes import wintypes
    _user32 = ctypes.windll.user32

    def _main_window():
        pid = os.getpid()
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _l):
            p = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid and _user32.IsWindowVisible(hwnd):
                r = wintypes.RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(r))
                found.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
            return True
        _user32.EnumWindows(each, 0)
        return max(found)[1] if found else None

    def get_frame():
        h = _main_window()
        if not h or _user32.IsZoomed(h) or _user32.IsIconic(h):
            return ["MAXIMIZED"] if h and _user32.IsZoomed(h) else None
        r = wintypes.RECT()
        _user32.GetWindowRect(h, ctypes.byref(r))
        return [r.left, r.top, r.right - r.left, r.bottom - r.top]

    def set_frame(frame):
        h = _main_window()
        if not h or not frame:
            return
        if frame == ["MAXIMIZED"]:
            _user32.ShowWindow(h, 3)                          # SW_MAXIMIZE
            return
        _user32.ShowWindow(h, 9)                              # SW_RESTORE
        _user32.MoveWindow(h, int(frame[0]), int(frame[1]), int(frame[2]), int(frame[3]), True)

else:
    def get_frame():
        return None

    def set_frame(frame):
        pass


# --- keeping and giving back --------------------------------------------------------------------------------------

def _off():
    """Test copies (BLENDA4D_NO_REMEMBER) and background runs leave the remembered window alone."""
    return bool(os.environ.get("BLENDA4D_NO_REMEMBER")) or bpy.app.background


def _keep():
    if _off():
        return None
    try:
        f = get_frame()
        if f and _state["applied"] and f != _state["frame"]:
            _state["frame"] = f
            _write(f)
    except Exception as ex:
        print("Blenda 4D: window not remembered:", ex)
    return SAVE_EVERY


def _start():
    if _off():
        return None
    try:
        frame = _read()
        if frame:
            set_frame(frame)
            _state["frame"] = frame
    except Exception as ex:
        print("Blenda 4D: window not put back:", ex)
    _state["applied"] = True
    return None


def _early_try():
    """As soon as Blender has made its window: put it back (tries for a moment while the window comes up)."""
    _state["tries"] = _state.get("tries", 0) + 1
    if _state["applied"] or _off():
        return None
    frame = _read()
    if not frame:
        _state["applied"] = True
        return None
    try:
        if get_frame() is None and _state["tries"] < 50:   # no window yet
            return 0.01
        set_frame(frame)
        _state["frame"] = frame
    except Exception as ex:
        print("Blenda 4D: window not put back:", ex)
    _state["applied"] = True
    return None


def early():
    """Called first thing when the add-on loads, before Blenda mode builds its layout."""
    if _off():
        return
    try:
        frame = _read()
        if frame:
            _early_try()                                  # maybe the window already exists
        if not _state["applied"] and not bpy.app.timers.is_registered(_early_try):
            bpy.app.timers.register(_early_try, first_interval=0.0)
    except Exception as ex:
        print("Blenda 4D: window not put back:", ex)


def register():
    if _off():
        return
    if not _state["applied"]:
        bpy.app.timers.register(_start, first_interval=0.1)
    if not bpy.app.timers.is_registered(_keep):
        bpy.app.timers.register(_keep, first_interval=SAVE_EVERY, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_keep):
        bpy.app.timers.unregister(_keep)
