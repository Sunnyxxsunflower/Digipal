"""
Linux helpers for DigiPal (same functions as digiwin.py on Windows).
Works best on X11 (or XWayland). Everything fails quietly: if something can't be read on
someone's Linux, that one feature just stays off.

Uses: psutil, python-xlib (pip), and dbus-send / loginctl if the system has them.
"""
import os
import sys
import shutil
import subprocess

try:
    import psutil
except Exception:
    psutil = None

try:
    from Xlib import display as _xdisplay, X
    from Xlib.ext import screensaver as _ss
except Exception:
    _xdisplay = None

_dpy = None


def _x():
    """A connection to the X server (None on pure Wayland or without python-xlib)."""
    global _dpy
    if _xdisplay is None or not os.environ.get("DISPLAY"):
        return None
    if _dpy is None:
        try:
            _dpy = _xdisplay.Display()
        except Exception:
            _dpy = None
    return _dpy


# ------------------------------------------------------------------ running programs
def processes():
    """[(name in lowercase, full path or "")] for everything running."""
    out = []
    if psutil is not None:
        for p in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                exe = p.info.get("exe") or " ".join(p.info.get("cmdline") or [])
                out.append(((p.info.get("name") or "").lower(), exe or ""))
            except Exception:
                continue
        return out
    try:
        r = subprocess.run(["ps", "-eo", "comm=,args="], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            parts = line.split(None, 1)
            if parts:
                out.append((parts[0].lower(), parts[1] if len(parts) > 1 else ""))
    except Exception:
        pass
    return out


def running(*names):
    want = {n.lower() for n in names}
    return any(n in want for n, _ in processes())


def obs_running():
    return running("obs", "obs-studio")


def screenshot_running():
    return running("gnome-screenshot", "spectacle", "flameshot", "ksnip", "xfce4-screenshooter",
                   "shutter", "scrot")


def steam_state():
    """(Steam is open, a Steam game is running)"""
    procs = processes()
    steam = any(n in ("steam", "steamwebhelper") for n, _ in procs)
    game = steam and any("/steamapps/common/" in (x or "").lower() for _, x in procs)
    return steam, game


# ------------------------------------------------------------------ keyboard / idle
def seconds_since_input():
    """Seconds since the last key press or mouse movement (X11 only)."""
    d = _x()
    if d is None:
        return 999.0
    try:
        info = _ss.query_info(d, d.screen().root)
        return info.idle / 1000.0
    except Exception:
        return 999.0


# ------------------------------------------------------------------ battery
def battery():
    """(percent, on_battery) or None when there's no battery."""
    if psutil is None:
        return None
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return int(round(b.percent)), not b.power_plugged
    except Exception:
        return None


def screen_locked():
    try:
        sid = os.environ.get("XDG_SESSION_ID")
        cmd = ["loginctl", "show-session", "-p", "LockedHint"] + ([sid] if sid else ["auto"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return "LockedHint=yes" in r.stdout
    except Exception:
        return False


# ------------------------------------------------------------------ windows on screen
def _atom(d, name):
    return d.intern_atom(name)


def _prop(d, w, name):
    try:
        p = w.get_full_property(_atom(d, name), X.AnyPropertyType)
        return p.value if p is not None else None
    except Exception:
        return None


def windows_front_to_back(skip_pid):
    """[(x, y, w, h) in screen pixels] for normal app windows, frontmost first (X11)."""
    d = _x()
    if d is None:
        return []
    out = []
    try:
        root = d.screen().root
        ids = _prop(d, root, "_NET_CLIENT_LIST_STACKING")     # bottom to top
        if ids is None:
            return []
        normal = _atom(d, "_NET_WM_WINDOW_TYPE_NORMAL")
        hidden = _atom(d, "_NET_WM_STATE_HIDDEN")
        for wid in reversed(list(ids)):
            try:
                w = d.create_resource_object("window", wid)
                pid = _prop(d, w, "_NET_WM_PID")
                if pid is not None and len(pid) and int(pid[0]) == skip_pid:
                    continue
                types = _prop(d, w, "_NET_WM_WINDOW_TYPE")
                if types is not None and len(types) and normal not in list(types):
                    continue
                state = _prop(d, w, "_NET_WM_STATE")
                if state is not None and hidden in list(state):
                    continue
                g = w.get_geometry()
                pos = w.translate_coords(root, 0, 0)
                x, y = -pos.x, -pos.y
                ext = _prop(d, w, "_NET_FRAME_EXTENTS")       # left, right, top, bottom
                if ext is not None and len(ext) == 4:
                    l, r, t, b = [int(v) for v in ext]
                    x, y = x - l, y - t
                    out.append((x, y, g.width + l + r, g.height + t + b))
                else:
                    out.append((x, y, g.width, g.height))
            except Exception:
                continue
    except Exception:
        return []
    return out


def front_app_name():
    """Name of the program you're using right now."""
    d = _x()
    if d is None:
        return ""
    try:
        root = d.screen().root
        act = _prop(d, root, "_NET_ACTIVE_WINDOW")
        if act is None or not len(act) or not act[0]:
            return ""
        w = d.create_resource_object("window", act[0])
        pid = _prop(d, w, "_NET_WM_PID")
        if pid is not None and len(pid) and psutil is not None:
            name = psutil.Process(int(pid[0])).name().lower()
            return APP_NAMES.get(name, name.capitalize())
        cls = w.get_wm_class()
        return cls[1] if cls else ""
    except Exception:
        return ""


APP_NAMES = {
    "chrome": "Google Chrome", "google-chrome": "Google Chrome", "chromium": "Chromium",
    "firefox": "Firefox", "firefox-bin": "Firefox", "brave": "Brave", "discord": "Discord",
    "resolve": "DaVinci Resolve", "spotify": "Spotify", "steam": "Steam", "blender": "Blender",
    "obs": "OBS", "gnome-terminal-server": "Terminal", "konsole": "Terminal", "code": "VS Code",
    "calibre": "Calibre", "libreoffice": "LibreOffice", "soffice.bin": "LibreOffice",
}


# ------------------------------------------------------------------ music / videos
def _dbus(*args):
    r = subprocess.run(["dbus-send", "--session", "--print-reply"] + list(args),
                       capture_output=True, text=True, timeout=3)
    return r.stdout


def media_playing():
    """True when a media player says it's playing (MPRIS: Spotify, browsers playing YouTube,
    VLC, Rhythmbox...)."""
    if not shutil.which("dbus-send"):
        return None
    try:
        names = [line.split('"')[1] for line in _dbus(
            "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus.ListNames").splitlines()
            if "org.mpris.MediaPlayer2." in line]
        for n in names:
            out = _dbus("--dest=" + n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                        "string:org.mpris.MediaPlayer2.Player", "string:PlaybackStatus")
            if '"Playing"' in out:
                return True
        return False
    except Exception:
        return None


# ------------------------------------------------------------------ start at login
AUTOSTART = os.path.expanduser("~/.config/autostart/digipal.desktop")


def autostart_enabled():
    return os.path.exists(AUTOSTART)


def set_autostart(on, command):
    if on:
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        here = os.path.dirname(os.path.abspath(__file__))
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=DigiPal\n"
                    f"Exec={command}\nIcon={os.path.join(here, 'icon.png')}\n"
                    "X-GNOME-Autostart-enabled=true\n")
    elif os.path.exists(AUTOSTART):
        os.remove(AUTOSTART)


def pythonw():
    return sys.executable
