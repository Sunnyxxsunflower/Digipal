"""
DigiPal's ears on Linux: Vosk, a speech recognizer that runs completely offline.

Needs:  pip install vosk sounddevice   (+ the PortAudio library, e.g. sudo apt install libportaudio2)
        and a Vosk model in ~/.local/share/digipal/vosk-model (install_linux.sh downloads it)
Works like the Mac/Windows versions: same `heard` / `status` signals, start("ptt" | "always"),
finish_talking() and stop().
"""
import os
import sys
import json
import time
import queue
import threading

from PySide6.QtCore import QObject, Signal, QTimer

MODEL_DIR = os.path.expanduser("~/.local/share/digipal/vosk-model")
MIC_FILE = os.path.expanduser("~/.desk_pet_mic.json")

try:
    import vosk
    import sounddevice as sd
    vosk.SetLogLevel(-1)
    HAS_VOICE = os.path.isdir(MODEL_DIR)
    _IMPORT_ERROR = None if HAS_VOICE else "no speech model (run install_linux.sh)"
except Exception as _ex:
    HAS_VOICE = False
    _IMPORT_ERROR = _ex


def log(*parts):
    try:
        print(time.strftime("%H:%M:%S"), "[voice]", *parts, file=sys.stderr, flush=True)
    except Exception:
        pass


def list_microphones():
    """[(index, uid, name)] for every input device."""
    out = []
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                out.append((i, dev["name"], dev["name"]))
    except Exception:
        pass
    return out


def default_microphone_id():
    return None


_model = None


def _get_model():
    global _model
    if _model is None:
        _model = vosk.Model(MODEL_DIR)
    return _model


class Ears(QObject):
    heard = Signal(str, bool)
    status = Signal(str)
    _done = Signal()
    _emit = Signal(str, bool)
    want_always = False

    def __init__(self):
        super().__init__()
        self.mode = None
        self.recognizer = None
        self.started_at = 0
        self.last_error = ""
        self.last_heard = ""
        self.buffers = 0
        self._gen = 0
        self._stop_flag = threading.Event()
        self._finish_flag = threading.Event()
        try:
            with open(MIC_FILE) as f:
                d = json.load(f)
            self.mic_uid, self.mic_name = d.get("uid"), d.get("name", "System default")
        except Exception:
            self.mic_uid, self.mic_name = None, "System default"
        self._done.connect(self._finished)
        if not HAS_VOICE:
            log("ears unavailable:", _IMPORT_ERROR)

    def _device(self):
        if not self.mic_uid:
            return None
        for i, uid, name in list_microphones():
            if uid == self.mic_uid:
                return i
        return None

    def start(self, mode):
        if not HAS_VOICE:
            self.status.emit("missing")
            return
        self.stop(quiet=True)
        self.mode = mode
        self._gen += 1
        self.buffers = 0
        self.last_heard = ""
        self._stop_flag = threading.Event()
        self._finish_flag = threading.Event()
        threading.Thread(target=self._listen, args=(self._gen, self._stop_flag, self._finish_flag),
                         daemon=True).start()

    def _listen(self, gen, stop_flag, finish_flag):
        q = queue.Queue()
        try:
            model = _get_model()
            dev = self._device()
            rate = int(sd.query_devices(dev, "input")["default_samplerate"])
            rec = vosk.KaldiRecognizer(model, rate)

            def cb(indata, frames, t, st):
                q.put(bytes(indata))
                return None

            with sd.RawInputStream(samplerate=rate, blocksize=4000, device=dev, dtype="int16",
                                   channels=1, callback=cb):
                self.started_at = time.time()
                self.status.emit("listening")
                log("listening (", self.mode, ")")
                said = ""
                while not stop_flag.is_set():
                    try:
                        data = q.get(timeout=0.2)
                    except queue.Empty:
                        data = None
                    if finish_flag.is_set():
                        break
                    if data is None:
                        continue
                    self.buffers += 1
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get("text", "")
                        if text:
                            said = (said + " " + text).strip()
                            self.last_heard = said
                            self.heard.emit(said, False)
                            if self.mode == "always":
                                break           # one sentence at a time when always listening
                    else:
                        part = json.loads(rec.PartialResult()).get("partial", "")
                        if part:
                            self.last_heard = (said + " " + part).strip()
                            self.heard.emit(self.last_heard, False)
            if stop_flag.is_set() or gen != self._gen:
                return
            final = json.loads(rec.FinalResult()).get("text", "")
            text = (said + " " + final).strip() if final else said
            log(f"heard ({self.mode}): {text!r}")
            self.heard.emit(text, True)
            self._done.emit()
        except Exception as ex:
            log("couldn't listen:", ex)
            self.last_error = str(ex)
            if gen == self._gen:
                self.mode = None
                self.status.emit("error: " + str(ex)[:60])

    def finish_talking(self):
        log(f"done talking, so far: {self.last_heard!r}")
        self._finish_flag.set()

    def restart(self):
        if self.mode == "always":
            self.start("always")

    def _finished(self):
        mode = self.mode
        self.stop(quiet=True)
        if mode == "always":
            QTimer.singleShot(300, lambda: self.start("always")
                              if self.mode is None and self.want_always else None)
        else:
            self.status.emit("stopped")

    def stop(self, quiet=False):
        self._gen += 1
        self._stop_flag.set()
        self.mode = None
        if not quiet:
            self.status.emit("stopped")
