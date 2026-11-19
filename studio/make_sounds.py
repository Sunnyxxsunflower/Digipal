"""Digi's calm background sounds: seamless loops, made from scratch (no recordings)."""
import numpy as np, wave, os, sys
from scipy import signal
OUT = sys.argv[1]
SR = 22050
DUR = 40                       # seconds per loop
FADE = 3.0                     # crossfade (end blends into start) so the loop has no seam
rng = np.random.default_rng(11)
PRE = 2.0                      # warm-up that's thrown away (filters settle)
N = int(SR * (DUR + FADE + PRE))


def lowpass(x, hz, order=2):
    b, a = signal.butter(order, hz / (SR / 2), "low")
    return signal.lfilter(b, a, x)


def highpass(x, hz, order=2):
    b, a = signal.butter(order, hz / (SR / 2), "high")
    return signal.lfilter(b, a, x)


def bandpass(x, lo, hi, order=2):
    b, a = signal.butter(order, [lo / (SR / 2), hi / (SR / 2)], "band")
    return signal.lfilter(b, a, x)


def pink(n):
    # Paul Kellet's filter: -3 dB/octave
    w = rng.standard_normal(n)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return signal.lfilter(b, a, w)


def brown(n):
    w = rng.standard_normal(n)
    y = np.cumsum(w)
    return highpass(y, 20)


def norm(x, peak=0.5):
    x = x - np.mean(x)
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def loop_and_save(x, name, peak=0.45):
    x = x[int(SR * PRE):]
    x = norm(x, peak)
    L = int(SR * DUR)
    f = int(SR * FADE)
    body = x[:L].copy()
    tail = x[L:L + f]
    ramp = np.linspace(0, 1, f)
    body[:f] = body[:f] * np.sqrt(ramp) + tail * np.sqrt(1 - ramp)   # equal-power: no dip at the seam
    pcm = (np.clip(body, -1, 1) * 32767).astype("<i2")
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(name, len(pcm) / SR, "s")


t = np.arange(N) / SR

# white noise: softened a little at the very top so it isn't hissy
loop_and_save(lowpass(rng.standard_normal(N), 7000), "white", 0.35)

# pink noise: deeper, like soft rain on a window
loop_and_save(lowpass(pink(N), 8000), "pink", 0.45)

# river: low rushing water plus a babbling, bubbly middle that wanders
rush = lowpass(brown(N), 900)
babble = bandpass(rng.standard_normal(N), 500, 2500)
wob = 0.55 + 0.45 * np.abs(lowpass(rng.standard_normal(N), 6, 1))
wob = wob / wob.max()
loop_and_save(norm(rush, 1) * 0.8 + norm(babble * wob, 1) * 0.35, "river", 0.45)

# waves: a soft roar that swells in and washes out every ~8-11 seconds
noise = pink(N)
env = np.zeros(N)
pos = 0
while pos < N:
    period = rng.uniform(8, 11) * SR
    k = np.arange(int(period))
    shape = np.where(k < period * 0.4, (k / (period * 0.4)) ** 1.6,
                     np.exp(-(k - period * 0.4) / (period * 0.22)))
    end = min(N, pos + len(k))
    env[pos:end] = np.maximum(env[pos:end], shape[:end - pos])
    pos += int(period * rng.uniform(0.85, 1.0))
env = 0.15 + 0.85 * lowpass(env, 3, 1)
bright = lowpass(noise, 600) * 0.7 + bandpass(noise, 600, 3500) * (env ** 2) * 0.6
loop_and_save(bright * env, "waves", 0.5)

# forest: a gentle breeze in the leaves, plus little birds chirping now and then
breeze = lowpass(pink(N), 1500) * (0.55 + 0.45 * lowpass(rng.standard_normal(N), 0.3, 1) / 3)
birds = np.zeros(N)
pos = int(SR * 1.5)
while pos < N - SR:
    f0 = rng.uniform(2600, 4200)
    n_chirps = rng.integers(2, 6)
    for c in range(n_chirps):
        dur = rng.uniform(0.06, 0.14)
        k = np.arange(int(dur * SR))
        sweep = f0 * (1 + rng.uniform(-0.25, 0.35) * (k / len(k)))
        ph = 2 * np.pi * np.cumsum(sweep) / SR
        a = np.sin(np.pi * k / len(k)) ** 2
        s = np.sin(ph) * a * rng.uniform(0.4, 1.0)
        start = pos + int(c * rng.uniform(0.12, 0.2) * SR)
        if start + len(s) < N:
            birds[start:start + len(s)] += s
    pos += int(rng.uniform(2.5, 6.0) * SR)
loop_and_save(norm(breeze, 1) * 0.6 + birds * 0.3, "forest", 0.45)
