# DigiPal 💜

**Digi** is a little 3D robot girl who lives on your desktop. She wanders around, sits on your windows, plays peekaboo, sings along to your music, reminds you to drink water, rolls dice for you, eats popcorn during movies, and a whole lot more. You can change her hair style, hair color, outfit, and skirt or shorts.

Made with love (and a little help from Claude).

**All of Digi's art was created by Sunny**, hand drawn in Procreate: Digi's character design, the app icon, Digi's room, the outfit designs and the dragon book cover. See [CREDITS.md](CREDITS.md).

## Install on Windows

1. Install **Python** from [python.org](https://www.python.org/downloads/) (on the first screen, tick **"Add python.exe to PATH"**).
2. On this page, click the green **Code** button → **Download ZIP**.
3. Unzip it somewhere you'll keep it (for example your Documents folder).
4. Open the folder and double-click **Install DigiPal**.
   - If Windows says "Windows protected your PC", click **More info → Run anyway**.
   - It installs what Digi needs, downloads her pictures (about 800 MB), and puts a **DigiPal** shortcut on your Desktop.

### Make her yours
Shift-click Digi (or right-click → **Customize Digi**):
- **Look:** hair style, hair color, skirt or shorts, outfits, speech bubble.
- **Personal settings:** your name, your city (for weather), bedtime.
- **Lists:** water, to-dos, reminders, birthdays.
- **Game night:** your tabletop games (D&D, Monster of the Week, Mothership...), turn order, and session notes.

### Talking to Digi
Hold-click her and talk, or double-click her. For voice, turn these on in Windows **Settings → Privacy & security**:
- **Speech → Online speech recognition**
- **Microphone → Let desktop apps access your microphone**

### Updates
Digi checks for updates once a day. When there's one, she tells you. Right-click her → **Update Digi**. You can also right-click → **Check for updates** anytime.

### Closing her
Right-click Digi → **Quit**.

## Install on Linux

Digi works best on desktops running **X11** (on Wayland she runs through XWayland automatically, but sitting on windows and noticing other apps may not work there).

1. On this page, click the green **Code** button → **Download ZIP**, and unzip it somewhere you'll keep it.
2. Open a terminal in that folder and run:
   ```
   bash install_linux.sh
   ```
   It sets up everything Digi needs in its own little space (it won't touch your system Python), downloads her pictures (about 800 MB) and her offline voice (about 40 MB), and adds **DigiPal** to your apps menu.
3. If voice doesn't work, install PortAudio: `sudo apt install libportaudio2` (Ubuntu/Debian) or `sudo dnf install portaudio` (Fedora).

If something acts weird, send the **digipal.log** file from Digi's folder to whoever shared her with you.

## Mac
The Mac version is coming soon!
