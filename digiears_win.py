"""
DigiPal's ears on Windows: Windows' own speech recognition (the same one behind voice typing).

Needs:  pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections
        winrt-Windows.Globalization winrt-Windows.Media.SpeechRecognition
And in Windows Settings -> Privacy & security:
  * Speech -> "Online speech recognition" ON
  * Microphone -> "Let desktop apps access your microphone" ON
Works like the Mac version: the same `heard` / `status` signals, start("ptt" | "always"),
finish_talking() and stop().
"""
import sys
import time
import asyncio
import threading

from PySide6.QtCore import QObject, Signal, QTimer

try:
    from winrt.windows.media.speechrecognition import (
        SpeechRecognizer, SpeechRecognitionTopicConstraint, SpeechRecognitionScenario,
        SpeechRecognitionResultStatus)
    from winrt.windows.globalization import Language
    HAS_VOICE = True
except Exception as _ex:      # packages not installed yet
    HAS_VOICE = False
    _IMPORT_ERROR = _ex


def log(*parts):
    try:
        print(time.strftime("%H:%M:%S"), "[voice]", *parts, file=sys.stderr, flush=True)
    except Exception:
        pass


def list_microphones():
    """Windows' speech recognizer always uses the default mic (set in Sound settings)."""
    return [(0, "default", "Windows default mic")]


def default_microphone_id():
    return 0


# a background thread that runs the Windows speech calls (they're all async)
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop)


class Ears(QObject):
    """Listens to the mic. Sends text out with the `heard` signal."""
    heard = Signal(str, bool)          # text, is_final
    status = Signal(str)               # "listening", "stopped", "missing", "dictation", "mic-denied", "error: ..."
    _done = Signal()                   # recognition finished
    want_always = False

    def __init__(self):
        super().__init__()
        self.mode = None
        self.recognizer = None
        self.started_at = 0
        self.mic_uid = "default"
        self.mic_name = "Windows default mic"
        self.last_error = ""
        self.last_heard = ""
        self.buffers = 0
        self._gen = 0
        self._committed = ""
        self._hyp = ""
        self._done.connect(self._finished)
        if not HAS_VOICE:
            log("speech packages missing:", _IMPORT_ERROR)

    # ---- start / stop ----
    def start(self, mode):
        if not HAS_VOICE:
            self.status.emit("missing")
            return
        self.stop(quiet=True)
        self.mode = mode
        self._gen += 1
        self._committed = self._hyp = ""
        self.buffers = 0
        _run(self._start(self._gen))

    async def _start(self, gen):
        try:
            try:
                rec = SpeechRecognizer(Language("en-US"))
            except Exception:
                rec = SpeechRecognizer()
            rec.constraints.append(
                SpeechRecognitionTopicConstraint(SpeechRecognitionScenario.DICTATION, "dictation"))
            res = await rec.compile_constraints_async()
            if res.status != SpeechRecognitionResultStatus.SUCCESS:
                raise RuntimeError(f"couldn't get ready ({res.status})")
            if gen != self._gen:
                rec.close()
                return
            rec.add_hypothesis_generated(lambda s, a: self._on_hyp(gen, a))
            sess = rec.continuous_recognition_session
            sess.add_result_generated(lambda s, a: self._on_result(gen, a))
            sess.add_completed(lambda s, a: self._on_completed(gen, a))
            self.recognizer = rec
            await sess.start_async()
            self.started_at = time.time()
            log("listening (", self.mode, ")")
            self.status.emit("listening")
        except Exception as ex:
            msg = str(ex)
            log("couldn't start listening:", msg)
            self.last_error = msg
            low = msg.lower()
            if "privacy" in low or "80045509" in low:
                self.status.emit("dictation")       # online speech recognition is off
            elif "access" in low or "80070005" in low:
                self.status.emit("mic-denied")
            else:
                self.status.emit("error: " + msg[:60])
            if gen == self._gen:
                self.mode = None

    def _text(self):
        return (self._committed + " " + self._hyp).strip()

    def _on_hyp(self, gen, args):
        if gen != self._gen:
            return
        try:
            self._hyp = args.hypothesis.text
        except Exception:
            return
        self.buffers += 1
        self.last_heard = self._text()
        self.heard.emit(self.last_heard, False)

    def _on_result(self, gen, args):
        if gen != self._gen:
            return
        try:
            text = args.result.text
        except Exception:
            text = ""
        self._hyp = ""
        if text:
            self._committed = (self._committed + " " + text).strip()
        self.last_heard = self._text()
        self.heard.emit(self.last_heard, False)

    def _on_completed(self, gen, args):
        if gen != self._gen:
            return
        text = self._text()
        log(f"heard ({self.mode}): {text!r}")
        self.heard.emit(text, True)
        self._done.emit()

    def finish_talking(self):
        """Push-to-talk released: stop listening and wait for the final words."""
        log(f"done talking, so far: {self.last_heard!r}")
        rec = self.recognizer

        async def go():
            try:
                await rec.continuous_recognition_session.stop_async()
            except Exception as ex:
                log("stop:", ex)
        if rec is not None:
            _run(go())

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
        rec, self.recognizer = self.recognizer, None

        async def go():
            try:
                await rec.continuous_recognition_session.cancel_async()
            except Exception:
                pass
            try:
                rec.close()
            except Exception:
                pass
        if rec is not None:
            _run(go())
        self.mode = None
        if not quiet:
            self.status.emit("stopped")
