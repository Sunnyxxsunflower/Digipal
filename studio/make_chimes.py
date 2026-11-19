"""Digi's meditation chimes, synthesized (no recordings)."""
import numpy as np, wave, sys, os
OUT = sys.argv[1]
SR = 44100
rng = np.random.default_rng(5)


def save(name, x, peak=0.55):
    x = x / (np.abs(x).max() + 1e-9) * peak
    fade = int(0.05 * SR)
    x[-fade:] *= np.linspace(1, 0, fade)
    pcm = (x * 32767).astype("<i2")
    with wave.open(os.path.join(OUT, f"chime_{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    print(name, "%.1fs" % (len(pcm) / SR))


def strike(t, f0, partials, decay, attack=0.004):
    """partials: (ratio, amp, decay multiplier, detune Hz for a slow shimmer)"""
    y = np.zeros_like(t)
    a = np.minimum(1, t / attack)
    for ratio, amp, dk, det in partials:
        f = f0 * ratio
        tone = np.sin(2 * np.pi * f * t)
        if det:
            tone = 0.5 * (tone + np.sin(2 * np.pi * (f + det) * t))     # beating, like a real bowl
        y += amp * tone * np.exp(-t * decay * dk)
    return y * a


def place(total, events):
    t_all = np.arange(int(total * SR)) / SR
    y = np.zeros_like(t_all)
    for start, fn in events:
        i = int(start * SR)
        t = t_all[: len(y) - i]
        y[i:] += fn(t)
    return y


# soft bell: one warm note (the original)
save("bell", place(3.0, [(0, lambda t: strike(t, 523.25, [(1, 1, 1, 0), (2.76, 0.35, 1.25, 0), (5.4, 0.15, 2.5, 0)], 2.4))]))

# singing bowl: low, long, with a slow wavering shimmer
save("bowl", place(6.0, [(0, lambda t: strike(t, 196.0, [(1, 1, 1, 1.6), (2.71, 0.55, 1.4, 2.3),
                                                         (5.15, 0.25, 2.0, 3.1), (8.4, 0.08, 3.0, 0)],
                                                 0.55, attack=0.03))]))

# wind chimes: a little cascade of bright notes
notes = [1046.5, 1174.7, 1318.5, 1568.0, 1760.0, 2093.0]
ev = []
tm = 0.0
for k in range(6):
    f = notes[rng.integers(0, len(notes))]
    amp = rng.uniform(0.5, 1.0)
    ev.append((tm, lambda t, f=f, amp=amp: amp * strike(t, f, [(1, 1, 1, 0), (2.76, 0.3, 1.5, 0)], 1.8)))
    tm += rng.uniform(0.12, 0.3)
save("windchimes", place(4.0, ev))

# gong: deep and rich, it blooms then fades
save("gong", place(6.0, [(0, lambda t: strike(t, 130.8, [(1, 1, 1, 0.7), (1.48, 0.6, 1.2, 0), (2.1, 0.5, 1.5, 1.1),
                                                        (2.9, 0.4, 2.0, 0), (3.6, 0.3, 2.6, 0), (5.2, 0.2, 3.0, 1.5)],
                                                0.6, attack=0.05) * (1 + 0.6 * (1 - np.exp(-t * 3))))]))

# tingsha: two small cymbals clinked twice, high and shimmering
ting = lambda t: strike(t, 2217.0, [(1, 1, 1, 6.0), (1.52, 0.4, 1.6, 4.0), (2.33, 0.2, 2.4, 0)], 1.1)
save("tingsha", place(4.5, [(0, ting), (0.9, lambda t: 0.8 * ting(t))]))

# middle: a lighter single tone; end: two rising notes
save("middle", place(3.0, [(0, lambda t: strike(t, 659.25, [(1, 1, 1, 0), (2.76, 0.35, 1.25, 0)], 2.4))]), 0.4)
save("end", place(3.4, [(0, lambda t: strike(t, 784.0, [(1, 1, 1, 0), (2.76, 0.35, 1.25, 0)], 2.4)),
                        (0.35, lambda t: strike(t, 1046.5, [(1, 1, 1, 0), (2.76, 0.35, 1.25, 0)], 2.4))]))
