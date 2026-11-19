import numpy as np, wave
from scipy import signal
SR = 32000
FADE = 3.0
x = np.fromfile("forest_src.f32", np.float32).astype(np.float64)
b, a = signal.butter(2, 60 / (SR / 2), "high")
x = signal.filtfilt(b, a, x)
# soften the loud bird calls (gentle compressor) so they stay pretty but don't startle
win = int(0.05 * SR)
env = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, "same")) + 1e-9
env = signal.filtfilt(*signal.butter(1, 8 / (SR / 2), "low"), env)
thr = 0.05
gain = np.where(env > thr, (thr * (env / thr) ** (1 / 3.5)) / env, 1.0)
x = x * gain
e1 = np.sqrt(np.convolve(x ** 2, np.ones(SR) / SR, "same"))
s0 = 6 * SR + int(np.argmin(e1[6 * SR:11 * SR]))
s1 = 64 * SR + int(np.argmin(e1[64 * SR:69 * SR]))
f = int(FADE * SR)
body = x[s0:s1].copy()
tail = x[s1:s1 + f]
r = np.linspace(0, 1, f)
body[:f] = body[:f] * np.sqrt(r) + tail * np.sqrt(1 - r)
g = min(0.075 / np.sqrt(np.mean(body ** 2)), 0.85 / np.abs(body).max())
body *= g
pcm = (np.clip(body, -1, 1) * 32767).astype("<i2")
with wave.open("forest.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
y = pcm / 32767
print("forest %.1fs from %.1f to %.1f" % (len(y) / SR, s0 / SR, s1 / SR), "rms %.3f peak %.2f gain %.2f" %
      (np.sqrt(np.mean(y ** 2)), np.abs(y).max(), g),
      "seam end/start rms %.3f/%.3f" % (np.sqrt(np.mean(y[-SR:] ** 2)), np.sqrt(np.mean(y[:SR] ** 2))))
