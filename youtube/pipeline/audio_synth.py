# -*- coding: utf-8 -*-
"""
audio_synth.py ― 効果音と BGM を自前で合成する（素材の権利問題をゼロにするため）
  効果音: pop（要素が出る）, coin（数字が伸びる）, sparkle（合計・締め）, whoosh（章の切り替え）, ding（章扉）
  BGM:    明るいポップ調のループ（ウクレレ風の分散和音＋軽い打ち込み）を指定秒数ぶん
"""
from __future__ import annotations
import math, wave
import numpy as np

SR = 24000

def _env(n: int, a: float, d: float, sr=SR) -> np.ndarray:
    t = np.arange(n) / sr
    return np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-t / max(d, 1e-4))

def _tone(freq: float, sec: float, kind="sine", sr=SR) -> np.ndarray:
    t = np.arange(int(sec * sr)) / sr
    if kind == "tri":
        return 2 * np.abs(2 * ((t * freq) % 1) - 1) - 1
    if kind == "saw":
        return 2 * ((t * freq) % 1) - 1
    return np.sin(2 * np.pi * freq * t)

def sfx(name: str) -> np.ndarray:
    if name == "pop":
        n = int(0.09 * SR); t = np.arange(n) / SR
        f = 520 * np.exp(-t * 18) + 180
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.03) * 0.5
    if name == "coin":
        a = _tone(1975, 0.07) * _env(int(0.07 * SR), 0.001, 0.02)
        b = _tone(2637, 0.22) * _env(int(0.22 * SR), 0.001, 0.07)
        out = np.zeros(int(0.30 * SR)); out[:len(a)] += a; st = int(0.07 * SR); out[st:st + len(b)] += b
        return out * 0.35
    if name == "sparkle":
        out = np.zeros(int(0.9 * SR))
        for i, f in enumerate([1047, 1319, 1568, 2093, 2637]):
            s = _tone(f, 0.5) * _env(int(0.5 * SR), 0.002, 0.12)
            st = int(i * 0.07 * SR); out[st:st + len(s)] += s[:len(out) - st]
        return out * 0.28
    if name == "whoosh":
        n = int(0.35 * SR); noise = np.random.default_rng(1).standard_normal(n)
        # 簡単なローパス（移動平均）を時間とともに開く
        k = 24; sm = np.convolve(noise, np.ones(k) / k, mode="same")
        mix = sm * np.linspace(1, 0.2, n) + noise * np.linspace(0, 0.3, n)
        return mix * _env(n, 0.08, 0.12) * 0.5
    if name == "ding":
        n = int(0.8 * SR)
        return (_tone(1319, 0.8) * 0.6 + _tone(2637, 0.8) * 0.25 + _tone(3951, 0.8) * 0.1) * _env(n, 0.002, 0.25) * 0.4
    raise ValueError(name)

# ---- BGM
_CHORDS = {  # 明るい進行 I–V–vi–IV（C 調）
    "C": [261.63, 329.63, 392.00], "G": [196.00, 246.94, 293.66], "Am": [220.00, 261.63, 329.63], "F": [174.61, 220.00, 261.63],
}
def bgm(seconds: float, bpm: int = 112, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    beat = 60 / bpm; bar = beat * 4
    total = int(seconds * SR) + SR
    out = np.zeros(total)
    prog = ["C", "G", "Am", "F"]
    # 分散和音（ウクレレ風の短い三角波）
    nbars = int(seconds / bar) + 2
    for b in range(nbars):
        chord = _CHORDS[prog[b % 4]]
        notes = chord + [chord[0] * 2, chord[1] * 2]
        for s in range(8):  # 8 分音符
            t0 = b * bar + s * beat / 2
            f = notes[(s * 3 + b) % len(notes)] * (2 if s in (3, 7) and rng.random() < 0.4 else 1)
            n = int(beat * 0.9 * SR)
            tone = _tone(f, n / SR, "tri") * _env(n, 0.004, 0.09) * 0.22
            st = int(t0 * SR)
            if st + n < total:
                out[st:st + n] += tone
        # ベース（1 拍目と 3 拍目）
        for s in (0, 2):
            n = int(beat * 0.8 * SR); st = int((b * bar + s * beat) * SR)
            if st + n < total:
                out[st:st + n] += _tone(chord[0] / 2, n / SR) * _env(n, 0.005, 0.18) * 0.25
        # 軽いハイハット（裏拍）とキック
        for s in range(8):
            st = int((b * bar + s * beat / 2) * SR)
            if s % 2 == 1:
                n = int(0.03 * SR); hh = rng.standard_normal(n) * _env(n, 0.001, 0.008) * 0.06
                if st + n < total: out[st:st + n] += hh
            if s in (0, 4):
                n = int(0.12 * SR); t = np.arange(n) / SR
                kick = np.sin(2 * np.pi * (120 * np.exp(-t * 25) + 40) * t) * _env(n, 0.002, 0.05) * 0.5
                if st + n < total: out[st:st + n] += kick
    out = out[:int(seconds * SR)]
    return np.tanh(out * 1.2) * 0.8

def write_wav(path, data: np.ndarray, sr=SR):
    pcm = np.clip(data, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())

if __name__ == "__main__":
    import sys
    from pathlib import Path
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for n in ("pop", "coin", "sparkle", "whoosh", "ding"):
        write_wav(out / f"sfx_{n}.wav", sfx(n))
    write_wav(out / "bgm_synth.wav", bgm(60))
    print("wrote", out)
