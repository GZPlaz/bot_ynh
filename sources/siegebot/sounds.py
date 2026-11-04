"""Procedurally generated noises: original synthesized sounds, no copyrighted game audio.
Written once to DATA_DIR/sounds/*.wav; uploaded clips live in the same folder."""
import math
import os
import random
import struct
import wave

RATE = 48000

BUILTIN = {
    "air_horn": "Triple air horn. Maximum obnoxiousness.",
    "alarm": "Two-tone emergency alarm",
    "siren_sweep": "Rising/falling siren that never ends",
    "earrape_square": "Clipped, distorted square-wave sweep. You have been warned.",
    "sad_trombone": "Wah wah wah waaaah",
    "fake_footsteps": "Heavy footsteps creeping closer (are they behind you?)",
    "fake_drone": "Whirring little drone rolling around",
    "fake_defuser": "Beeping that speeds up like a device being planted",
    "fake_breach": "Beep-beep-beep... BOOM",
    "fake_gunfire": "Burst of rapid gunfire",
    "fake_reinforce": "Metallic hammering, like a wall being reinforced",
    "fake_glass": "Window shattering",
}


def _sine(f, t):
    return math.sin(2 * math.pi * f * t)


def _saw(f, t):
    x = (f * t) % 1.0
    return 2 * x - 1


def _square(f, t):
    return 1.0 if (f * t) % 1.0 < 0.5 else -1.0


def _env(t, attack=0.005, decay=None, length=None):
    a = min(1.0, t / attack) if attack else 1.0
    if decay:
        a *= math.exp(-t / decay)
    if length is not None and t > length:
        return 0.0
    return a


def _write(path, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s / peak)) * 32000)) for s in samples))


def _render(dur, fn):
    return [fn(i / RATE) for i in range(int(dur * RATE))]


def _air_horn():
    def f(t):
        blasts = [(0.0, 0.35), (0.45, 0.35), (0.9, 1.2)]
        for start, ln in blasts:
            if start <= t < start + ln:
                lt = t - start
                v = sum(_saw(fr * (1 + 0.003 * _sine(6, lt)), lt) for fr in (440, 554, 659))
                return math.tanh(3 * v) * _env(lt, 0.01)
        return 0.0
    return _render(2.2, f)


def _alarm():
    return _render(3.0, lambda t: math.tanh(2 * _square(960 if int(t * 4) % 2 else 720, t)))


def _siren():
    return _render(4.0, lambda t: _saw(600 + 500 * _sine(0.5, t), t) * 0.9)


def _earrape():
    phase = [0.0]

    def f(t):
        fr = 120 + 1800 * ((t * 1.5) % 1.0)
        phase[0] += fr / RATE
        v = (1.0 if phase[0] % 1.0 < 0.5 else -1.0) + 0.6 * random.uniform(-1, 1)
        return max(-0.6, min(0.6, v * 4))  # hard clip
    return _render(3.0, f)


def _trombone():
    notes = [(0.0, 392), (0.55, 370), (1.1, 349), (1.65, 330)]

    def f(t):
        for i, (s, fr) in enumerate(notes):
            ln = 0.5 if i < 3 else 1.5
            if s <= t < s + ln:
                lt = t - s
                vib = 1 + (0.02 * _sine(5, lt) if i == 3 else 0)
                return (_saw(fr * vib, lt) * 0.6 + _square(fr * vib / 2, lt) * 0.3) * _env(lt, 0.03) * (1 - lt / ln * 0.3)
        return 0.0
    return _render(3.2, f)


def _footsteps():
    out, lp = [], 0.0
    steps = [0.3 + i * 0.55 for i in range(7)]
    for i in range(int(4.2 * RATE)):
        t = i / RATE
        v = 0.0
        for k, s in enumerate(steps):
            if s <= t < s + 0.18:
                lt = t - s
                v += (random.uniform(-1, 1) * 0.6 + _sine(70, lt)) * math.exp(-lt / 0.04) * (0.4 + k * 0.1)
        lp += 0.08 * (v - lp)  # low-pass: muffled thud
        out.append(lp)
    return out


def _drone():
    return _render(4.0, lambda t: (_saw(210 + 15 * _sine(9, t), t) * 0.5 + _saw(420 + 30 * _sine(9, t), t) * 0.2
                                   + random.uniform(-0.15, 0.15)) * (0.6 + 0.4 * _sine(0.4, t)))


def _defuser():
    times, t, gap = [], 0.0, 0.6
    while t < 4.0:
        times.append(t)
        t += gap
        gap = max(0.08, gap * 0.82)

    def f(t):
        for s in times:
            if s <= t < s + 0.06:
                return _sine(2400, t) * _env(t - s, 0.002)
        return 0.0
    return _render(4.2, f)


def _breach():
    def f(t):
        for s in (0.0, 0.35, 0.7):
            if s <= t < s + 0.1:
                return _square(1800, t) * 0.5
        if t >= 1.0:
            lt = t - 1.0
            return random.uniform(-1, 1) * math.exp(-lt / 0.35) + _sine(45, lt) * math.exp(-lt / 0.5)
        return 0.0
    return _render(2.6, f)


def _gunfire():
    shots = [i * 0.09 for i in range(18)]

    def f(t):
        for s in shots:
            if s <= t < s + 0.08:
                lt = t - s
                return (random.uniform(-1, 1) + _sine(110, lt)) * math.exp(-lt / 0.02)
        return 0.0
    return _render(1.9, f)


def _reinforce():
    hits = [0.2, 0.75, 1.3, 1.6, 2.2]
    partials = (523, 1418, 2650, 4130)

    def f(t):
        v = 0.0
        for s in hits:
            if t >= s:
                lt = t - s
                v += sum(_sine(p, lt) / (n + 1) for n, p in enumerate(partials)) * math.exp(-lt / 0.12)
        return v
    return _render(3.0, f)


def _glass():
    pings = [(random.uniform(0.0, 0.6), random.uniform(2500, 7000)) for _ in range(25)]

    def f(t):
        v = random.uniform(-1, 1) * math.exp(-t / 0.08)
        for s, fr in pings:
            if t >= s:
                v += _sine(fr, t - s) * math.exp(-(t - s) / 0.15) * 0.25
        return v
    return _render(1.6, f)


GENERATORS = {"air_horn": _air_horn, "alarm": _alarm, "siren_sweep": _siren, "earrape_square": _earrape,
              "sad_trombone": _trombone, "fake_footsteps": _footsteps, "fake_drone": _drone,
              "fake_defuser": _defuser, "fake_breach": _breach, "fake_gunfire": _gunfire,
              "fake_reinforce": _reinforce, "fake_glass": _glass}

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".opus", ".m4a", ".flac", ".webm")


def sound_dir(data_dir):
    d = os.path.join(data_dir, "sounds")
    os.makedirs(d, exist_ok=True)
    return d


def ensure_builtin(data_dir):
    d = sound_dir(data_dir)
    for name, gen in GENERATORS.items():
        p = os.path.join(d, name + ".wav")
        if not os.path.exists(p):
            _write(p, gen())


def list_sounds(data_dir):
    d = sound_dir(data_dir)
    out = []
    for fn in sorted(os.listdir(d)):
        name, ext = os.path.splitext(fn)
        if ext.lower() in AUDIO_EXT:
            out.append({"name": name, "file": os.path.join(d, fn), "builtin": name in BUILTIN,
                        "description": BUILTIN.get(name, "Uploaded clip"), "size": os.path.getsize(os.path.join(d, fn))})
    return out


def find_sound(data_dir, name):
    for s in list_sounds(data_dir):
        if s["name"] == name:
            return s
    return None
