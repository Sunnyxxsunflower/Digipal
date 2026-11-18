#!/usr/bin/env bash
# Sets up DigiPal on Linux. Run it from a terminal in this folder:   bash install_linux.sh
here="$(cd "$(dirname "$0")" && pwd)"
data="$HOME/.local/share/digipal"
mkdir -p "$data"
echo
echo "  ~ Setting up Digi! ~"
echo

# 1. Python + a private spot for Digi's libraries (doesn't touch your system Python)
if ! command -v python3 >/dev/null; then
    echo "Please install Python 3 first (Ubuntu/Debian: sudo apt install python3 python3-venv)"
    exit 1
fi
if [ ! -x "$data/venv/bin/python" ]; then
    python3 -m venv "$data/venv" || {
        echo "Couldn't make Digi's Python space. On Ubuntu/Debian run:  sudo apt install python3-venv"
        exit 1; }
fi
py="$data/venv/bin/python"
echo "Installing Digi's window library (this can take a few minutes)..."
"$py" -m pip install --upgrade pip >/dev/null
"$py" -m pip install --upgrade PySide6 psutil python-xlib || {
    echo "That didn't install - send the error above to whoever gave you Digi!"; exit 1; }
echo "Installing Digi's ears (offline voice)..."
"$py" -m pip install --upgrade vosk sounddevice || echo "(voice didn't install - Digi still works without it)"

# 2. the speech model her ears use (about 40 MB, works offline)
if [ ! -d "$data/vosk-model" ]; then
    echo "Downloading Digi's ears (about 40 MB)..."
    "$py" - "$data" <<'PY'
import sys, os, zipfile, urllib.request, shutil
data = sys.argv[1]
url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
z = os.path.join(data, "model.zip")
try:
    urllib.request.urlretrieve(url, z)
    with zipfile.ZipFile(z) as f:
        f.extractall(data)
    os.replace(os.path.join(data, "vosk-model-small-en-us-0.15"), os.path.join(data, "vosk-model"))
except Exception as ex:
    print("Couldn't get the speech model:", ex)
finally:
    if os.path.exists(z):
        os.remove(z)
PY
fi

# 3. her pictures: from ~/Downloads/pet_frames.zip, or downloaded from GitHub
if [ ! -f "$here/pet_frames/idle_00.png" ]; then
    echo "Getting Digi's pictures (about 800 MB - give it a while)..."
    "$py" - "$here" <<'PY'
import sys, os, json, zipfile, urllib.request, shutil
here = sys.argv[1]
z = os.path.expanduser("~/Downloads/pet_frames.zip")
tmp = None
try:
    if not os.path.exists(z):
        info = json.load(open(os.path.join(here, "version.json")))
        tmp = z = os.path.join(here, "pet_frames_download.zip")
        urllib.request.urlretrieve(info["frames_url"], z)
    with zipfile.ZipFile(z) as f:
        f.extractall(here)
    shutil.rmtree(os.path.join(here, "__MACOSX"), ignore_errors=True)
    print("Frames are ready!")
except Exception as ex:
    print("Couldn't get Digi's pictures:", ex)
finally:
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
PY
fi

# 4. an app-menu entry (and a desktop icon if you have a Desktop folder)
entry="[Desktop Entry]
Type=Application
Name=DigiPal
Comment=Digi, your desktop pal
Exec=\"$py\" \"$here/digipal.py\"
Icon=$here/icon.png
Terminal=false
Categories=Utility;"
mkdir -p "$HOME/.local/share/applications"
printf '%s\n' "$entry" > "$HOME/.local/share/applications/digipal.desktop"
desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$desk" ]; then
    printf '%s\n' "$entry" > "$desk/digipal.desktop"
    chmod +x "$desk/digipal.desktop"
    gio set "$desk/digipal.desktop" metadata::trusted true 2>/dev/null
fi
echo "Added DigiPal to your apps menu."

echo
echo "If voice doesn't work, your system may need the PortAudio library:"
echo "   Ubuntu/Debian: sudo apt install libportaudio2     Fedora: sudo dnf install portaudio"
echo
echo "All done! Starting Digi..."
nohup "$py" "$here/digipal.py" >/dev/null 2>&1 &
sleep 2
