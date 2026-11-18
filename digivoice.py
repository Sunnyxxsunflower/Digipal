"""
DigiPal's ears: speech recognition with Apple's own on-device Speech framework.

Needs:  pip3 install pyobjc-framework-Speech pyobjc-framework-AVFoundation
Nothing you say leaves the Mac when on-device recognition is available.
"""
import re
import sys
import time
import ast
import json
import os
import ctypes
import operator

from PySide6.QtCore import QObject, Signal, QTimer

try:
    import Speech
    import AVFoundation
    from Foundation import NSLocale
    HAS_VOICE = True
except Exception:          # packages not installed yet
    HAS_VOICE = False

MIC_FILE = os.path.expanduser("~/.desk_pet_mic.json")


def log(*parts):
    try:
        print(time.strftime("%H:%M:%S"), "[voice]", *parts, file=sys.stderr, flush=True)
    except Exception:
        pass


# ------------------------------------------------------------------ microphones
def _fourcc(s):
    return int.from_bytes(s.encode("ascii"), "big")


class _Addr(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32),
                ("element", ctypes.c_uint32)]


_CA = None


def _ca():
    global _CA
    if _CA is None:
        _CA = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        _CA.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(_Addr), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32)]
        _CA.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(_Addr), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    return _CA


def _cfstring_to_str(ptr):
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(512)
    ok = cf.CFStringGetCString(ptr, buf, 512, 0x08000100)   # UTF-8
    cf.CFRelease(ptr)
    return buf.value.decode("utf-8", "replace") if ok else "?"


def _get_string(dev, selector):
    ca = _ca()
    addr = _Addr(_fourcc(selector), _fourcc("glob"), 0)
    ref = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    if ca.AudioObjectGetPropertyData(dev, ctypes.byref(addr), 0, None,
                                     ctypes.byref(size), ctypes.byref(ref)) != 0 or not ref.value:
        return None
    return _cfstring_to_str(ref.value)


def list_microphones():
    """[(device_id, uid, name)] for every device that can record."""
    out = []
    try:
        ca = _ca()
        addr = _Addr(_fourcc("dev#"), _fourcc("glob"), 0)
        size = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(1, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
            return out
        n = size.value // 4
        ids = (ctypes.c_uint32 * n)()
        if ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None,
                                         ctypes.byref(size), ids) != 0:
            return out
        for dev in ids:
            st = _Addr(_fourcc("stm#"), _fourcc("inpt"), 0)
            ssize = ctypes.c_uint32(0)
            ca.AudioObjectGetPropertyDataSize(dev, ctypes.byref(st), 0, None, ctypes.byref(ssize))
            if ssize.value == 0:
                continue                     # no input streams: speakers only
            name = _get_string(dev, "lnam") or "Microphone"
            uid = _get_string(dev, "uid ") or str(dev)
            out.append((int(dev), uid, name))
    except Exception as ex:
        log("list_microphones failed:", ex)
    return out


def default_microphone_id():
    try:
        ca = _ca()
        addr = _Addr(_fourcc("dIn "), _fourcc("glob"), 0)
        dev = ctypes.c_uint32(0)
        size = ctypes.c_uint32(4)
        if ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None,
                                         ctypes.byref(size), ctypes.byref(dev)) == 0:
            return int(dev.value)
    except Exception:
        pass
    return None


def load_mic_choice():
    try:
        with open(MIC_FILE) as f:
            return json.load(f).get("uid")
    except Exception:
        return None


def save_mic_choice(uid):
    try:
        with open(MIC_FILE, "w") as f:
            json.dump({"uid": uid}, f)
    except Exception:
        pass


# words that help Apple's recognizer expect her name and dice talk
CONTEXT = ["Digi", "Hey Digi", "Hi Digi", "d20", "d12", "d10", "d8", "d6", "d4",
           "d100", "advantage", "disadvantage", "roll", "dice"]

# ways her name tends to come out of speech-to-text
NAME = r"(?:digi|diggy|digie|digy|deegee|dg|d\.?g\.?|dig e|didi|dizzy|ziggy|digit|digby|dixie|dicky|dee gee|d gee)"
WAKE_RE = re.compile(r"\b(?:(?:hey|hi|hello|okay|ok|yo|oi)[\s,]+)?" + NAME + r"\b[\s,!?.]*", re.I)


class Ears(QObject):
    """Listens to the mic. Sends text out with the `heard` signal."""
    heard = Signal(str, bool)          # text, is_final
    status = Signal(str)               # "listening", "stopped", "denied", "error: ..."
    _perm = Signal(str)                # permission answers, brought back to the main thread
    _done = Signal()                   # recognition finished

    def __init__(self):
        super().__init__()
        self.mode = None               # None, "ptt", "always"
        self.engine = None
        self.request = None
        self.task = None
        self.recognizer = None
        self.authorized = False
        self.started_at = 0
        self._tap_fn = None
        self._handler = None
        self.mic_uid = load_mic_choice()      # None = the Mac's default mic
        self.mic_name = "Mac default"
        self.last_error = ""
        self.last_heard = ""
        self.buffers = 0
        self._pending = None
        self._perm.connect(self._on_perm)
        self._done.connect(self._finished)
        if HAS_VOICE:
            loc = NSLocale.localeWithLocaleIdentifier_("en-US")
            self.recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(loc)

    # ---- permissions ----
    def mic_status(self):
        try:
            return int(AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
                AVFoundation.AVMediaTypeAudio))
        except Exception:
            return 3

    def can_ask_for_mic(self):
        """macOS kills an app that asks for the mic without saying why in its Info.plist."""
        try:
            from Foundation import NSBundle
            b = NSBundle.mainBundle()
            log("running as bundle:", b.bundlePath())
            return b.objectForInfoDictionaryKey_("NSMicrophoneUsageDescription") is not None
        except Exception:
            return False

    def ask_permission(self, then):
        """Speech Recognition first, then the Microphone. Calls then() when both are allowed."""
        if not HAS_VOICE:
            self.status.emit("missing")
            return
        self._pending = then
        st = int(Speech.SFSpeechRecognizer.authorizationStatus())
        if st == 3:
            self._perm.emit("speech-ok")
        elif st == 0:
            def speech_answer(status):
                self._perm.emit("speech-ok" if status == 3 else "denied")
                return None
            self._speech_cb = speech_answer
            Speech.SFSpeechRecognizer.requestAuthorization_(speech_answer)
        else:
            self._perm.emit("denied")

    def _on_perm(self, what):
        if what == "denied":
            self.status.emit("denied")
            return
        if what == "mic-denied":
            self.status.emit("mic-denied")
            return
        if what == "speech-ok":
            m = self.mic_status()
            if m == 3:
                what = "all-ok"
            elif m == 0:
                if not self.can_ask_for_mic():
                    log("no mic usage text in this process's bundle - asking would crash")
                    self.status.emit("needs-fix")
                    return
                log("asking for microphone permission")
                def mic_answer(granted):
                    self._perm.emit("all-ok" if granted else "mic-denied")
                    return None
                self._mic_cb = mic_answer
                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVFoundation.AVMediaTypeAudio, mic_answer)
                return
            else:
                self.status.emit("mic-denied")
                return
        if what == "all-ok":
            self.authorized = True
            then, self._pending = self._pending, None
            if then:
                then()

    # ---- start / stop ----
    def start(self, mode):
        if not HAS_VOICE:
            self.status.emit("missing")
            return
        if not self.authorized:
            self.ask_permission(lambda: self.start(mode))
            return
        self.stop(quiet=True)
        self.mode = mode
        try:
            self.engine = AVFoundation.AVAudioEngine.alloc().init()
            node = self.engine.inputNode()
            self.use_chosen_mic(node)
            fmt = node.outputFormatForBus_(0)
            log("mic:", self.mic_name, "| format:", fmt.sampleRate(), "Hz,",
                fmt.channelCount(), "ch")
            if fmt.sampleRate() == 0 or fmt.channelCount() == 0:
                self.last_error = "that mic gives no sound"
                self.status.emit("error: that mic gives no sound")
                self.stop(quiet=True)
                return
            req = Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
            req.setShouldReportPartialResults_(True)
            try:
                if self.recognizer.supportsOnDeviceRecognition():
                    req.setRequiresOnDeviceRecognition_(True)
            except Exception:
                pass
            try:
                req.setContextualStrings_(CONTEXT)
            except Exception:
                pass
            self.request = req

            self.buffers = 0

            def tap(buf, when):
                try:
                    self.buffers += 1
                    req.appendAudioPCMBuffer_(buf)
                except Exception:
                    pass
                return None
            self._tap_fn = tap
            node.installTapOnBus_bufferSize_format_block_(0, 1024, fmt, tap)
            self.engine.prepare()
            ok = self.engine.startAndReturnError_(None)
            if isinstance(ok, tuple):
                ok = ok[0]
            if not ok:
                self.status.emit("error: microphone didn't start")
                self.stop(quiet=True)
                return

            def handler(result, error):
                self._on_result(result, error)
                return None

            self._handler = handler
            self.task = self.recognizer.recognitionTaskWithRequest_resultHandler_(req, handler)
            self.started_at = time.time()
            self.status.emit("listening")
        except Exception as ex:
            self.status.emit(f"error: {ex}")
            self.stop(quiet=True)

    def _on_result(self, result, error):
        try:
            if error is not None:
                msg = str(error.localizedDescription())
                code = int(error.code())
                log("speech error", code, msg)
                # 1110 = no speech heard, 216/301 = we cancelled it: normal
                if code == 201:
                    self.last_error = f"{msg} ({code})"
                    self.status.emit("dictation")
                elif code not in (1110, 216, 301) and not (self.mode == "always" and code == 1107):
                    self.last_error = f"{msg} ({code})"
                    if self.mode == "ptt":
                        self.status.emit("error: " + msg)
            if result is not None:
                text = str(result.bestTranscription().formattedString())
                self.last_heard = text
                if result.isFinal():
                    log(f"heard ({self.mode}, {self.buffers} chunks): {text!r}")
                self.heard.emit(text, bool(result.isFinal()))
            if error is not None or (result is not None and result.isFinal()):
                self._done.emit()
        except Exception:
            pass

    def use_chosen_mic(self, node):
        """Points the recorder at the mic picked in her menu."""
        self.mic_name = "Mac default"
        mics = list_microphones()
        want = None
        if self.mic_uid:
            want = next((m for m in mics if m[1] == self.mic_uid), None)
            if want is None:
                log("chosen mic not plugged in, using default")
        if want is None:
            d = default_microphone_id()
            hit = next((m for m in mics if m[0] == d), None)
            if hit:
                self.mic_name = hit[2] + " (default)"
            return
        try:
            au = node.AUAudioUnit() if hasattr(node, "AUAudioUnit") else node.auAudioUnit()
            r = au.setDeviceID_error_(want[0], None)
            ok = r[0] if isinstance(r, tuple) else r
            if ok:
                self.mic_name = want[2]
            else:
                log("couldn't switch mic:", r)
                self.last_error = "couldn't switch to " + want[2]
        except Exception as ex:
            log("couldn't switch mic:", ex)
            self.last_error = f"couldn't switch mic ({ex})"

    def finish_talking(self):
        """Push-to-talk released: stop recording, wait for the final words."""
        log(f"done talking after {self.buffers} chunks, so far: {self.last_heard!r}")
        try:
            if self.engine is not None:
                self.engine.stop()
                self.engine.inputNode().removeTapOnBus_(0)
            if self.request is not None:
                self.request.endAudio()
        except Exception:
            pass

    def restart(self):
        if self.mode == "always":
            self.start("always")

    def _finished(self):
        mode = self.mode
        self.stop(quiet=True)
        if mode == "always":
            QTimer.singleShot(300, lambda: self.start("always") if self.mode is None and self.want_always else None)
        else:
            self.status.emit("stopped")

    want_always = False

    def stop(self, quiet=False):
        try:
            if self.engine is not None:
                self.engine.stop()
                self.engine.inputNode().removeTapOnBus_(0)
        except Exception:
            pass
        try:
            if self.task is not None:
                self.task.cancel()
        except Exception:
            pass
        self.engine = self.request = self.task = None
        self.mode = None
        if not quiet:
            self.status.emit("stopped")


# ------------------------------------------------------------------ understanding
NUM_WORDS = {
    "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}
SMALL = {k: v for k, v in NUM_WORDS.items() if k not in ("a", "an", "for")}


def words_to_digits(text):
    """'twenty five' -> '25', 'one hundred' -> '100' (good enough for dice and math)."""
    toks = text.split()
    out, cur, have = [], 0, False
    for t in toks:
        w = t.lower().strip(",.?!")
        if w in SMALL:
            v = SMALL[w]
            if v == 100:
                cur = (cur or 1) * 100
            else:
                cur += v
            have = True
        else:
            if have:
                out.append(str(cur))
                cur, have = 0, False
            out.append(t)
    if have:
        out.append(str(cur))
    return " ".join(out)


def strip_wake(text):
    """Returns (had_name, rest_of_text)."""
    m = WAKE_RE.search(text)
    if not m:
        return False, text.strip()
    rest = (text[:m.start()] + " " + text[m.end():]).strip(" ,.!?")
    return True, rest


def parse_dice(text):
    t = " " + text.lower() + " "
    if "disadvantage" in t:
        return (2, 20, 0, "disadvantage")
    if "advantage" in t:
        return (2, 20, 0, "advantage")
    t = re.sub(r"\b(dee|die|the|d\.)\s*(?=\d|twenty|twelve|ten|eight|six|four|hundred|one hundred)", "d", t)
    t = words_to_digits(t)
    t = re.sub(r"(?<![a-z])d\s+(\d+)", r"d\1", t)     # "1D 20" / "d 20" -> "1d20"
    m = re.search(r"(\d+|a|an|one)?\s*d(\d+)s?\b(?:\s*(plus|\+|minus|-)\s*(\d+))?", t)
    if not m:
        return None
    c = m.group(1)
    count = 1 if c in (None, "a", "an", "one") else int(c)
    sides = int(m.group(2))
    mod = int(m.group(4) or 0) * (-1 if m.group(3) in ("minus", "-") else 1)
    if not (1 <= count <= 50 and 2 <= sides <= 1000):
        return None
    return (count, sides, mod, None)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.UAdd: operator.pos, ast.Mod: operator.mod}


def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _calc(node.left), _calc(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 10:
            raise ValueError("too big")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    raise ValueError("not math")


def parse_math(text):
    t = text.lower()
    t = re.sub(r"\b(what's|what is|whats|calculate|how much is|what does|equal|equals|=|\?)", " ", t)
    t = words_to_digits(t)
    rep = [(r"multiplied by|times|\bx\b|×", "*"), (r"divided by|over|÷", "/"),
           (r"plus", "+"), (r"minus|take away", "-"), (r"squared", "**2"),
           (r"cubed", "**3"), (r"to the power of", "**"), (r"percent of", "/100*")]
    for a, b in rep:
        t = re.sub(a, b, t)
    t = t.replace(",", "")
    expr = "".join(ch for ch in t if ch in "0123456789.+-*/() ")
    expr = expr.strip()
    if not re.search(r"\d", expr) or not re.search(r"[+\-*/]", expr):
        return None
    try:
        val = _calc(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    if isinstance(val, float):
        val = round(val, 4)
        if val == int(val):
            val = int(val)
    pretty = expr.replace("**", "^").replace("*", "×").replace("/", "÷")
    return pretty, val


def understand(text):
    """Turns what you said into (action, details)."""
    t = text.lower().strip(" ,.!?")
    if not t:
        return ("hello", None)
    if re.search(r"\broll|\bdice|(?<![a-z])d\s*\d|advantage", t):
        d = parse_dice(t)
        if d:
            return ("roll", d)
    m = parse_math(t)
    if m:
        return ("math", m)
    if re.search(r"\b(move|scoot|out of the way|go away|in the way|shoo|other side)", t):
        return ("move", None)
    if re.search(r"\b(come here|come back|over here)", t):
        return ("come", None)
    if re.search(r"\b(nap|sleep|bedtime|go to bed)", t):
        return ("sleep", None)
    if re.search(r"\b(wake up|good morning)", t):
        return ("wake", None)
    if re.search(r"\b(drank|drink|had some) .*water|\bwater\b", t):
        return ("water", None)
    if re.search(r"\b(bomb|explode|explosion|kaboom|boom)", t):
        return ("bomb", None)
    if re.search(r"\b(ball|play|fetch)", t):
        return ("ball", None)
    if re.search(r"\bwhat time|\btime is it", t):
        return ("time", None)
    if re.search(r"\b(sit|take a seat)", t):
        return ("sit", None)
    if re.search(r"\b(dance|sing)", t):
        return ("dance", None)
    if re.search(r"\b(hi|hello|hey|how are you|good (afternoon|evening))\b", t):
        return ("hello", None)
    if re.search(r"\b(thank|thanks|love you|good girl|cute)", t):
        return ("love", None)
    return ("unknown", t)


# ------------------------------------------------------------------ Windows
# On Windows her ears use Windows' own speech recognition instead (digiears_win.py);
# everything above about understanding what you said stays the same.
if sys.platform == "win32":
    try:
        from digiears_win import (Ears, HAS_VOICE, list_microphones,  # noqa: F401,F811
                                  default_microphone_id)
    except Exception as _ex:
        log("Windows ears didn't load:", _ex)
        HAS_VOICE = False

# ------------------------------------------------------------------ Linux
# On Linux her ears use Vosk, which works offline (digiears_linux.py).
if sys.platform.startswith("linux"):
    try:
        from digiears_linux import (Ears, HAS_VOICE, list_microphones,  # noqa: F401,F811
                                    default_microphone_id)
    except Exception as _ex:
        log("Linux ears didn't load:", _ex)
        HAS_VOICE = False
