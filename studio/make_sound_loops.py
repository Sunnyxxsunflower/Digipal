import numpy as np, wave, sys
from scipy import signal
SR = 32000
FADE = 3.0


def load(n):
    return np.fromfile(n + ".f32", np.float32).astype(np.float64)


def env(x, secs):
    win = int(SR * secs)
    return np.sqrt(np.convolve(x ** 2, np.ones(win) / win, "same"))


def trough(e, a, b):
    i0, i1 = int(a * SR), int(b * SR)
    return i0 + int(np.argmin(e[i0:i1]))


def make(x, start, end, out, target_rms=0.085):
    b, a = signal.butter(2, 40 / (SR / 2), "high")
    x = signal.filtfilt(b, a, x)
    f = int(FADE * SR)
    seg = x[start:end + f].copy()                  # a bit extra for the crossfade
    body = seg[:end - start].copy()
    tail = seg[end - start:end - start + f]
    r = np.linspace(0, 1, f)
    body[:f] = body[:f] * np.sqrt(r) + tail * np.sqrt(1 - r)   # loop seam: end flows into start
    rms = np.sqrt(np.mean(body ** 2))
    gain = min(target_rms / rms, 0.9 / np.abs(body).max())
    body *= gain
    pcm = (np.clip(body, -1, 1) * 32767).astype("<i2")
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(out, "%.1fs" % (len(pcm) / SR), "rms %.3f" % np.sqrt(np.mean((pcm / 32767) ** 2)),
          "peak %.2f" % (np.abs(pcm).max() / 32767), "gain %.2f" % gain)


w = load("698911__jojo1298__tayrona-colombia-waves-shoreline-1")
e = env(w, 2.0)
s0 = trough(e, 45, 52)
s1 = trough(e, s0 / SR + 58, s0 / SR + 66)
print("waves", s0 / SR, s1 / SR)
make(w, s0, s1, "waves.wav")

r = load("730154__brunoauzet__saliouse-river-murmur-1")
make(r, 20 * SR, 80 * SR, "river.wav")
