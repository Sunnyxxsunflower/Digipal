"""
Windows helpers for DigiPal: everything that was a Mac-only trick in digipal.py
(which apps are running, battery, which window is in front, music playing, start at login...).
Every function fails quietly and returns something harmless, so Digi keeps working
even if one of these can't be read.
"""
import os
import sys
import ctypes
import subprocess
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    dwmapi = ctypes.windll.dwmapi
except Exception:
    dwmapi = None

try:
    import psutil
except Exception:
    psutil = None

NO_WINDOW = 0x08000000          # run helper commands without flashing a console window


# ------------------------------------------------------------------ running programs
def processes():
    """[(exe name in lowercase, full path or "")] for everything running."""
    out = []
    if psutil is not None:
        for p in psutil.process_iter(["name", "exe"]):
            try:
                out.append(((p.info.get("name") or "").lower(), p.info.get("exe") or ""))
            except Exception:
                continue
        return out
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                           timeout=6, creationflags=NO_WINDOW)
        for line in r.stdout.splitlines():
            parts = line.split('","')
            if parts:
                out.append((parts[0].strip('"').lower(), ""))
    except Exception:
        pass
    return out


def running(*names):
    want = {n.lower() for n in names}
    return any(n in want for n, _ in processes())


# ------------------------------------------------------------------ keyboard / idle
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def seconds_since_input():
    """Seconds since the last key press or mouse movement anywhere."""
    try:
        li = _LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if user32.GetLastInputInfo(ctypes.byref(li)):
            return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        pass
    return 999.0


# ------------------------------------------------------------------ battery
class _POWER(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def battery():
    """(percent, on_battery) or None when there's no battery."""
    try:
        s = _POWER()
        if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None
        if s.BatteryFlag & 128 or s.BatteryLifePercent == 255:
            return None
        return int(s.BatteryLifePercent), s.ACLineStatus == 0
    except Exception:
        return None


def screen_locked():
    return running("logonui.exe")


# ------------------------------------------------------------------ windows on screen
class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                "Windows.UI.Core.CoreWindow", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland"}
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14


def _class_name(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def _title(h):
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def _pid(h):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def _bounds(h):
    r = _RECT()
    if dwmapi is not None:
        try:
            if dwmapi.DwmGetWindowAttribute(h, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r),
                                            ctypes.sizeof(r)) == 0:
                return r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception:
            pass
    if user32.GetWindowRect(h, ctypes.byref(r)):
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return None


def _cloaked(h):
    if dwmapi is None:
        return False
    v = ctypes.c_int(0)
    try:
        dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        return False
    return v.value != 0


def windows_front_to_back(skip_pid):
    """[(x, y, w, h) in real screen pixels] for normal app windows, frontmost first."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(h, _):
        try:
            if not user32.IsWindowVisible(h) or user32.IsIconic(h):
                return True
            if _pid(h) == skip_pid:
                return True
            ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
            if ex & WS_EX_TOOLWINDOW:
                return True
            if _class_name(h) in SKIP_CLASSES or not _title(h):
                return True
            if _cloaked(h):
                return True
            b = _bounds(h)
            if b and b[2] > 0 and b[3] > 0:
                found.append(b)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(each, 0)
    except Exception:
        pass
    return found


def front_app_name():
    """Name of the program you're using right now, e.g. "Discord" or "Spotify"."""
    try:
        h = user32.GetForegroundWindow()
        pid = _pid(h)
        name = psutil.Process(pid).name() if psutil is not None else ""
        return APP_NAMES.get(name.lower(), os.path.splitext(name)[0])
    except Exception:
        return ""


# program file names -> the names Digi's reactions use
APP_NAMES = {
    "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
    "brave.exe": "Brave", "opera.exe": "Opera", "discord.exe": "Discord",
    "resolve.exe": "DaVinci Resolve", "capcut.exe": "CapCut", "winword.exe": "Microsoft Word",
    "notepad.exe": "Notepad", "spotify.exe": "Spotify", "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam", "windowsterminal.exe": "Terminal", "cmd.exe": "Terminal",
    "powershell.exe": "Terminal", "blender.exe": "Blender", "obs64.exe": "OBS",
    "calibre.exe": "Calibre", "procreate.exe": "Procreate", "canva.exe": "Canva",
    "itunes.exe": "Music", "applemusic.exe": "Music", "claude.exe": "Claude",
}


# ------------------------------------------------------------------ music / videos
_media_mgr = None


def media_playing():
    """True when anything is playing through Windows' media controls: Spotify, YouTube in a
    browser, Apple Music, movies... Needs the winrt-Windows.Media.Control package."""
    global _media_mgr
    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as St)
    except Exception:
        return None

    async def check():
        global _media_mgr
        if _media_mgr is None:
            _media_mgr = await Mgr.request_async()
        for s in _media_mgr.get_sessions():
            try:
                if s.get_playback_info().playback_status == St.PLAYING:
                    return True
            except Exception:
                continue
        return False

    try:
        return asyncio.run(check())
    except Exception:
        _media_mgr = None
        return None


# ------------------------------------------------------------------ start at login
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "DigiPal")
            return True
    except Exception:
        return False


def set_autostart(on, command):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "DigiPal", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(k, "DigiPal")
            except FileNotFoundError:
                pass


def pythonw():
    """pythonw.exe next to the running Python (runs Digi without a console window)."""
    d = os.path.dirname(sys.executable)
    w = os.path.join(d, "pythonw.exe")
    return w if os.path.exists(w) else sys.executable
