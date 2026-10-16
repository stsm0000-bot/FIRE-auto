# -*- coding: utf-8 -*-
"""
audio_synth.py ― 効果音と BGM を numpy だけで合成する（素材の権利問題をゼロにするため）
  効果音: pop（要素が出る）, coin（数字が伸びる）, sparkle（合計・締め）, whoosh（章の切り替え）, ding（章扉）
          reveal（ジャーン）, riser（盛り上げ）, tick（小さなクリック）
  BGM:    明るいポップ調（イントロ 1 小節 → A 8 小節 → B 8 小節 → A …）。
          ピアノ／ウクレレ風プラック＋サインベース＋ローパスのパッド＋キック／スネア／ハット＋ペンタトニックの短いメロディ。
          軽いリバーブと tanh コンプ、ラウドネス約 -18 LUFS、ピーク -1 dBFS 以下に整える。
外部 API（他ファイルから呼ばれる）: sfx(name) / bgm(seconds, bpm, seed) / write_wav(path, data)
  いずれも float の numpy 配列（-1〜1、24 kHz モノラル）を扱う。
"""
from __future__ import annotations
import math, wave
import numpy as np

SR = 24000
_TWO_PI = 2 * np.pi

# ---------------------------------------------------------------- 基本部品
def _env(n: int, a: float, d: float, sr=SR) -> np.ndarray:
    """直線アタック a 秒 → 指数減衰（時定数 d 秒）"""
    t = np.arange(n) / sr
    return np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-t / max(d, 1e-4))

def _tone(freq: float, sec: float, kind="sine", sr=SR) -> np.ndarray:
    t = np.arange(int(sec * sr)) / sr
    if kind == "tri":
        return 2 * np.abs(2 * ((t * freq) % 1) - 1) - 1
    if kind == "saw":
        return 2 * ((t * freq) % 1) - 1
    return np.sin(_TWO_PI * freq * t)

def _fade(x: np.ndarray, a: float = 0.003, r: float = 0.012) -> np.ndarray:
    """頭と尻を直線でなめらかに（クリック防止。a は 2ms 以上）"""
    x = x.copy(); n = len(x)
    na = min(n, max(int(a * SR), int(0.002 * SR))); nr = min(n, int(r * SR))
    if na > 0: x[:na] *= np.linspace(0, 1, na, endpoint=False)
    if nr > 0: x[n - nr:] *= np.linspace(1, 0, nr)
    return x

def _nf(name: str) -> float:
    """音名（"C4", "F#5", "Bb3"）→ 周波数"""
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    m = names[name[0]]; i = 1
    while i < len(name) and name[i] in "#b":
        m += 1 if name[i] == "#" else -1; i += 1
    octv = int(name[i:])
    return 440.0 * 2 ** ((m + 12 * (octv + 1) - 69) / 12)

def _fft_filter(x: np.ndarray, gain) -> np.ndarray:
    """ゼロ位相の周波数領域フィルタ。gain(f[Hz]) → 振幅倍率"""
    n = len(x)
    if n == 0: return x
    m = 1 << (n + int(0.05 * SR) - 1).bit_length()   # 2 のべき乗に詰めて高速化（末尾の回り込みも避ける）
    X = np.fft.rfft(x, m); f = np.fft.rfftfreq(m, 1 / SR)
    return np.fft.irfft(X * gain(f), m)[:n]

def _lowpass(x: np.ndarray, fc: float, order: float = 2) -> np.ndarray:
    return _fft_filter(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order)))

def _highpass(x: np.ndarray, fc: float, order: float = 2) -> np.ndarray:
    return _fft_filter(x, lambda f: (f / fc) ** order / np.sqrt(1 + (f / fc) ** (2 * order)))

def _fftconv(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """畳み込み（FFT）。長さは x に揃える"""
    n = len(x) + len(h) - 1; m = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)
    return y[:len(x)]

def _reverb_ir(seconds: float = 0.35, seed: int = 3) -> np.ndarray:
    """短いディレイ（コム）を重ねた簡易リバーブのインパルス応答。高域を減衰させて自然に"""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR); ir = np.zeros(n)
    for d_ms, g in ((23.1, 0.62), (31.7, 0.58), (41.3, 0.55), (53.9, 0.5)):
        d = int(d_ms / 1000 * SR); k = 1; a = g
        while k * d < n and a > 1e-3:
            ir[k * d] += a * (1 + 0.15 * rng.standard_normal()); k += 1; a *= g
    # 初期反射（細かいランダム）
    er = np.zeros(n); idx = rng.integers(int(0.004 * SR), int(0.03 * SR), 12)
    er[idx] = rng.uniform(0.2, 0.5, len(idx)) * rng.choice([-1, 1], len(idx))
    ir = ir + er
    t = np.arange(n) / SR
    ir *= np.exp(-t / (seconds * 0.45))           # 全体の減衰
    ir = _lowpass(ir, 4200, 1)                    # ダンピング
    return ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9) * 0.9

_IR = None
def _reverb(x: np.ndarray, wet: float = 0.25, seconds: float = 0.35) -> np.ndarray:
    global _IR
    if _IR is None or len(_IR) != int(seconds * SR):
        _IR = _reverb_ir(seconds)
    return x + wet * _fftconv(x, _IR)

def _resonator_sweep(noise: np.ndarray, f_from: float, f_to: float, bw: float = 400, curve: float = 1.0) -> np.ndarray:
    """2 極の共振器で帯域を低→高へ掃引（短い素材向け。ループは数千〜2 万回）"""
    n = len(noise); t = np.linspace(0, 1, n) ** curve
    freqs = f_from * (f_to / f_from) ** t
    r = math.exp(-math.pi * bw / SR)
    out = np.empty(n); y = 0j
    for i in range(n):
        p = r * complex(math.cos(_TWO_PI * freqs[i] / SR), math.sin(_TWO_PI * freqs[i] / SR))
        y = noise[i] + p * y
        out[i] = y.imag
    return out * (1 - r)

def _lufs(x: np.ndarray) -> float:
    """BS.1770 の K 特性を周波数領域で近似した統合ラウドネス（ゲーティング無し）"""
    def kw(f):
        shelf = 10 ** ((4.0 * f ** 2 / (f ** 2 + 2200.0 ** 2)) / 20)
        hp = (f / 38.0) ** 2 / np.sqrt(1 + (f / 38.0) ** 4)
        return shelf * hp
    y = _fft_filter(x, kw)
    return -0.691 + 10 * math.log10(float(np.mean(y ** 2)) + 1e-12)

# ---------------------------------------------------------------- 楽器
def _pluck(freq: float, sec: float = 0.5, bright: float = 1.0, seed: int = 0) -> np.ndarray:
    """ピアノ／ウクレレ風プラック: 倍音 4 本（高い倍音ほど早く減衰）＋ごく短い爪ノイズ"""
    n = int(sec * SR); t = np.arange(n) / SR
    out = np.zeros(n)
    partials = ((1.0, 1.0, 0.32), (2.003, 0.5 * bright, 0.18), (3.01, 0.22 * bright, 0.11), (4.02, 0.08 * bright, 0.07))
    for ratio, amp, dec in partials:
        f = freq * ratio
        if f > SR * 0.45: continue
        out += amp * np.sin(_TWO_PI * f * t + 0.3 * ratio) * np.exp(-t / dec)
    att = np.minimum(t / 0.003, 1.0)
    rng = np.random.default_rng(seed)
    out = out * att + rng.standard_normal(n) * np.exp(-t / 0.004) * 0.08 * att
    return _fade(out, 0.002, 0.02) * 0.5

def _bass_note(freq: float, sec: float) -> np.ndarray:
    n = int(sec * SR); t = np.arange(n) / SR
    body = np.sin(_TWO_PI * freq * t) + 0.35 * np.sin(_TWO_PI * freq * 2 * t) + 0.08 * np.sin(_TWO_PI * freq * 3 * t)
    env = np.minimum(t / 0.008, 1.0) * np.minimum(1.0, np.exp(-(t - sec * 0.6) / 0.06))  # 6 割まで持続 → リリース
    return _fade(body * env, 0.004, 0.03) * 0.5

_PAD_CACHE: dict[tuple, np.ndarray] = {}
def _pad_chord(freqs: list[float], sec: float, seed: int = 0) -> np.ndarray:
    """デチューンした鋸波を薄く重ね、ローパス気味に（同じ和音・長さはキャッシュ）"""
    key = (tuple(round(f, 2) for f in freqs), round(sec, 4))
    if key in _PAD_CACHE: return _PAD_CACHE[key]
    n = int(sec * SR); t = np.arange(n) / SR
    out = np.zeros(n)
    for i, f in enumerate(freqs):
        for det in (-0.004, 0.004):
            ph = (i * 0.37 + det) % 1
            out += (2 * ((t * f * (1 + det) + ph) % 1) - 1) * 0.5
    out = _lowpass(out, 1100, 2)
    a = 0.08; r = 0.15
    env = np.minimum(t / a, 1.0) * np.minimum(1.0, np.maximum(0.0, (sec - t) / r))
    _PAD_CACHE[key] = out * env / max(len(freqs), 1)
    return _PAD_CACHE[key]

def _kick(seed: int = 11) -> np.ndarray:
    n = int(0.3 * SR); t = np.arange(n) / SR
    f = 46 + 115 * np.exp(-t * 26)
    body = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t * 8.5)
    click = np.random.default_rng(seed).standard_normal(n) * np.exp(-t * 350) * 0.35
    return _fade(np.tanh((body + click) * 1.6), 0.002, 0.02) * 0.9

def _snare(seed: int = 12) -> np.ndarray:
    n = int(0.22 * SR); t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    noise = np.diff(rng.standard_normal(n + 1)) * 0.6 + rng.standard_normal(n) * 0.5
    noise = noise * np.exp(-t * 20)
    f = 180 + 70 * np.exp(-t * 45)
    body = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t * 28) * 0.7
    return _fade((noise * 0.55 + body), 0.002, 0.02) * 0.7

def _hat(open_: bool = False, seed: int = 13) -> np.ndarray:
    sec = 0.18 if open_ else 0.055
    n = int(sec * SR); t = np.arange(n) / SR
    noise = np.random.default_rng(seed).standard_normal(n + 2)
    noise = np.diff(np.diff(noise))  # 2 回差分 ≒ 急なハイパス
    env = np.exp(-t * (28 if open_ else 95))
    return _fade(noise * env / 2.2, 0.002, 0.01) * 0.6

# ---------------------------------------------------------------- 効果音
def sfx(name: str) -> np.ndarray:
    if name == "pop":
        # 気持ちいい「ポン」: 2 つの短い倍音、ごく短いピッチ下降
        n = int(0.12 * SR); t = np.arange(n) / SR
        f = 420 + 380 * np.exp(-t * 60)
        ph = _TWO_PI * np.cumsum(f) / SR
        out = np.sin(ph) * np.exp(-t / 0.045) + 0.45 * np.sin(2 * ph) * np.exp(-t / 0.022)
        out += np.random.default_rng(5).standard_normal(n) * np.exp(-t / 0.003) * 0.12
        out *= np.minimum(t / 0.002, 1.0)
        return _fade(out, 0.002, 0.03) * 0.55
    if name == "coin":
        # 金属感のある「チャリン」: 非整数倍音 2 つ＋軽い FM、2 音
        def hit(f0, sec, amp):
            n = int(sec * SR); t = np.arange(n) / SR
            mod = np.sin(_TWO_PI * f0 * 1.41 * t) * 0.9 * np.exp(-t / 0.03)
            s = np.sin(_TWO_PI * f0 * t + mod) * np.exp(-t / (sec * 0.33))
            s += 0.5 * np.sin(_TWO_PI * f0 * 2.76 * t) * np.exp(-t / (sec * 0.18))
            s += 0.25 * np.sin(_TWO_PI * f0 * 5.4 * t) * np.exp(-t / (sec * 0.1))
            return _fade(s * np.minimum(t / 0.002, 1.0), 0.002, 0.02) * amp
        out = np.zeros(int(0.42 * SR))
        a = hit(1975, 0.10, 0.8); b = hit(2637, 0.34, 1.0)
        out[:len(a)] += a; st = int(0.075 * SR); out[st:st + len(b)] += b
        return _reverb(out, 0.12, 0.25) * 0.32
    if name == "sparkle":
        # 上昇アルペジオ＋短い残響
        out = np.zeros(int(1.1 * SR))
        for i, nm in enumerate(("C6", "E6", "G6", "C7", "E7", "G7")):
            f = _nf(nm); n = int(0.45 * SR); t = np.arange(n) / SR
            s = (np.sin(_TWO_PI * f * t) + 0.4 * np.sin(_TWO_PI * f * 2 * t) * np.exp(-t / 0.08)) * np.exp(-t / 0.14)
            s = _fade(s * np.minimum(t / 0.002, 1.0), 0.002, 0.03) * (0.6 + 0.08 * i)
            st = int(i * 0.065 * SR); out[st:st + n] += s[:len(out) - st]
        return _fade(_reverb(out, 0.35, 0.4), 0.002, 0.05) * 0.26
    if name == "whoosh":
        # ノイズを帯域フィルタで低→高へ掃引
        n = int(0.42 * SR); t = np.arange(n) / SR
        noise = np.random.default_rng(1).standard_normal(n)
        sw = _resonator_sweep(noise, 180, 3800, bw=350, curve=1.3)
        sw += 0.25 * _resonator_sweep(noise, 90, 1900, bw=200, curve=1.3)
        env = np.minimum(t / 0.06, 1.0) * np.exp(-((t - 0.16) / 0.11) ** 2 * (t > 0.16)) * np.minimum(1.0, (0.42 - t) / 0.08)
        out = sw * env
        return _fade(out / (np.max(np.abs(out)) + 1e-9), 0.004, 0.03) * 0.5
    if name == "ding":
        # 柔らかい鐘: 倍音ごとに減衰を変え、立ち上がりを少し丸める
        n = int(0.9 * SR); t = np.arange(n) / SR
        f0 = _nf("E6")
        out = (np.sin(_TWO_PI * f0 * t) * np.exp(-t / 0.35)
               + 0.35 * np.sin(_TWO_PI * f0 * 2.0 * t + 0.5) * np.exp(-t / 0.18)
               + 0.18 * np.sin(_TWO_PI * f0 * 2.71 * t) * np.exp(-t / 0.10)
               + 0.08 * np.sin(_TWO_PI * f0 * 4.1 * t) * np.exp(-t / 0.05))
        out *= np.minimum(t / 0.005, 1.0)
        return _fade(_reverb(out, 0.2, 0.3), 0.003, 0.06) * 0.38
    if name == "reveal":
        # 「ジャーン」: 和音のスタブ（プラック＋鋸波のうねり）＋短い残響、0.6 秒
        n = int(0.6 * SR); t = np.arange(n) / SR
        out = np.zeros(n)
        for i, nm in enumerate(("C4", "E4", "G4", "C5", "E5")):
            f = _nf(nm)
            p = _pluck(f, 0.6, bright=1.2, seed=20 + i)
            st = int(i * 0.012 * SR)
            out[st:] += p[:n - st] * (1.0 - 0.1 * i)
            saw = (2 * ((t * f * 1.003) % 1) - 1) * 0.5 + (2 * ((t * f * 0.997) % 1) - 1) * 0.5
            out += saw * np.exp(-t / 0.22) * np.minimum(t / 0.015, 1.0) * 0.1
        out = _lowpass(out, 5000, 1)
        out = _reverb(out, 0.3, 0.3) * np.minimum(1.0, np.maximum(0.0, (0.6 - t) / 0.12))
        return _fade(out / (np.max(np.abs(out)) + 1e-9), 0.003, 0.05) * 0.6
    if name == "riser":
        # 0.8 秒のノイズ上昇（帯域とピッチが上がり、音量も膨らむ）
        n = int(0.8 * SR); t = np.arange(n) / SR
        noise = np.random.default_rng(9).standard_normal(n)
        sw = _resonator_sweep(noise, 250, 5200, bw=300, curve=0.8)
        tone_f = 220 * 2 ** (t / 0.8 * 1.5)
        tone = np.sin(_TWO_PI * np.cumsum(tone_f) / SR) * 0.15
        env = (t / 0.8) ** 1.8 * 0.85 + 0.15
        out = (sw / (np.max(np.abs(sw)) + 1e-9) + tone) * env * np.minimum(t / 0.01, 1.0)
        return _fade(out / (np.max(np.abs(out)) + 1e-9), 0.004, 0.02) * 0.5
    if name == "tick":
        # 20ms の軽いクリック
        n = int(0.02 * SR); t = np.arange(n) / SR
        out = np.sin(_TWO_PI * 2400 * t) * np.exp(-t / 0.004) + 0.5 * np.sin(_TWO_PI * 4100 * t) * np.exp(-t / 0.0025)
        out += np.random.default_rng(3).standard_normal(n) * np.exp(-t / 0.002) * 0.3
        return _fade(out * np.minimum(t / 0.002, 1.0), 0.002, 0.006) * 0.45
    raise ValueError(name)

# ---------------------------------------------------------------- BGM
_CHORDS = {
    "C": ["C4", "E4", "G4"], "G": ["G3", "B3", "D4"], "Am": ["A3", "C4", "E4"], "F": ["F3", "A3", "C4"],
    "Em": ["E3", "G3", "B3"], "Dm": ["D3", "F3", "A3"],
}
_PROG = {"intro": ["C"], "A": ["C", "G", "Am", "F"], "B": ["F", "G", "Em", "Am", "F", "G", "C", "C"]}
# メロディ: (2 小節内の 8 分音符位置, 音名, 長さ[8 分音符]) ― C メジャー・ペンタトニック
_MELODY = {
    "A": [(0, "E5", 2), (2, "G5", 1), (3, "A5", 1), (4, "G5", 2), (6, "E5", 2), (8, "D5", 2), (10, "E5", 1), (11, "G5", 1), (12, "E5", 4)],
    "A2": [(0, "E5", 2), (2, "G5", 1), (3, "A5", 1), (4, "C6", 2), (6, "A5", 2), (8, "G5", 1), (9, "E5", 1), (10, "D5", 2), (12, "C5", 4)],
    "B": [(0, "G5", 1), (1, "A5", 1), (2, "C6", 2), (4, "D6", 1), (5, "C6", 1), (6, "A5", 2), (8, "G5", 2), (10, "A5", 1), (11, "C6", 1), (12, "D6", 2), (14, "E6", 2)],
    "B2": [(0, "E6", 1), (1, "D6", 1), (2, "C6", 2), (4, "A5", 1), (5, "G5", 1), (6, "A5", 2), (8, "C6", 2), (10, "D6", 1), (11, "C6", 1), (12, "G5", 4)],
}

def bgm(seconds: float, bpm: int = 112, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    beat = 60 / bpm; bar = beat * 4; e8 = beat / 2
    nbars = int(math.ceil(seconds / bar)) + 2
    total = int((nbars + 1) * bar * SR)
    bus = {k: np.zeros(total) for k in ("pluck", "mel", "bass", "pad", "kick", "drum", "hat")}

    def put(name: str, sig: np.ndarray, t0: float, gain: float = 1.0):
        st = int(t0 * SR)
        if st < 0 or st >= total: return
        m = min(len(sig), total - st)
        bus[name][st:st + m] += sig[:m] * gain

    kick, snare, hat_c, hat_o = _kick(), _snare(), _hat(False), _hat(True)
    pluck_cache: dict[tuple, np.ndarray] = {}
    def pluck(freq, sec=0.45, bright=1.0):
        key = (round(freq, 2), round(sec, 3), bright)
        if key not in pluck_cache:
            pluck_cache[key] = _pluck(freq, sec, bright, seed=int(freq) % 97)
        return pluck_cache[key]

    def jitter(lo=0.86, hi=1.0):
        return rng.uniform(lo, hi)

    for b in range(nbars):
        if b == 0:
            sec_name = "intro"; chord_name = "C"; pos = 0
        else:
            pos = (b - 1) % 16
            sec_name = "A" if pos < 8 else "B"
            prog = _PROG[sec_name]
            chord_name = prog[(pos % 8) % len(prog)]
        chord = [_nf(x) for x in _CHORDS[chord_name]]
        root, third, fifth = chord
        t_bar = b * bar
        is_b = sec_name == "B"
        last_of_section = (b > 0) and ((pos % 8) == 7)

        # --- プラック（ウクレレ風の分散和音。1 拍目は軽いストラム）
        pattern = [root, fifth, root * 2, third * 2, fifth, root * 2, third * 2, fifth * 2] if not is_b \
            else [root, third * 2, fifth * 2, root * 2, third * 2, fifth * 2, root * 4 if root * 4 < 1200 else root * 2, fifth * 2]
        for s in range(8):
            t0 = t_bar + s * e8
            vel = (1.0 if s in (0, 4) else 0.78) * jitter()
            if s == 0 or (is_b and s == 4):
                for i, f in enumerate((root, third * 2, fifth * 2, root * 2)):
                    put("pluck", pluck(f, 0.55, 1.1 if is_b else 1.0), t0 + i * 0.011, vel * 0.55)
            else:
                f = pattern[s]
                put("pluck", pluck(f, 0.45, 1.1 if is_b else 1.0), t0, vel * (0.6 if b == 0 else 0.75))

        # --- ベース（サイン）
        bass_root = root / 4 if root / 4 >= 60 else root / 2
        if b == 0:
            put("bass", _bass_note(bass_root, beat * 1.8), t_bar, 0.9)
        else:
            put("bass", _bass_note(bass_root, beat * 0.95), t_bar, 1.0 * jitter(0.92, 1.0))
            put("bass", _bass_note(bass_root, beat * 0.95), t_bar + 2 * beat, 0.9 * jitter(0.92, 1.0))
            if is_b:
                put("bass", _bass_note(bass_root * 2, beat * 0.45), t_bar + 1.5 * beat, 0.6)
            if rng.random() < (0.7 if is_b else 0.45):
                put("bass", _bass_note(bass_root * 1.5 if not last_of_section else bass_root * 2, beat * 0.45), t_bar + 3.5 * beat, 0.7)

        # --- パッド（小節をまたいで薄くクロスフェード）
        pad_notes = [root, third, fifth, root * 2]
        put("pad", _pad_chord(pad_notes, bar + 0.1, seed=b), t_bar - 0.05, 1.25 if is_b else (0.9 if b == 0 else 1.0))

        # --- メロディ（イントロは休み）
        if b > 0 and (pos % 2) == 0:
            phrase = _MELODY[("B" if is_b else "A") + ("" if (pos % 8) in (0, 2) else "2")]
            for e, nm, ln in phrase:
                f = _nf(nm)
                put("mel", pluck(f, min(0.9, ln * e8 * 1.1 + 0.1), 0.9), t_bar + e * e8, (0.9 if e % 4 == 0 else 0.75) * jitter(0.85, 1.0))

        # --- ドラム
        if b == 0:
            for s in range(8):
                put("hat", hat_c, t_bar + s * e8, (0.5 if s % 2 == 0 else 0.32) * jitter())
            put("kick", kick, t_bar, 0.8)
            # セクション頭への小さなフィル
            for i in range(2):
                put("drum", snare, t_bar + 3.5 * beat + i * e8 / 2, 0.35 + 0.15 * i)
        else:
            for s in range(8):
                vel = (1.0 if s % 2 == 0 else 0.58) * jitter(0.84, 1.0)
                if is_b and s % 2 == 1:
                    put("hat", hat_o, t_bar + s * e8, vel * 0.8)
                else:
                    put("hat", hat_c, t_bar + s * e8, vel)
            put("kick", kick, t_bar, 1.0 * jitter(0.95, 1.0))
            put("kick", kick, t_bar + 2 * beat, 0.92 * jitter(0.92, 1.0))
            if is_b:
                put("kick", kick, t_bar + 3.5 * beat, 0.7)
            put("drum", snare, t_bar + beat, 1.0 * jitter(0.9, 1.0))
            put("drum", snare, t_bar + 3 * beat, 0.95 * jitter(0.9, 1.0))
            if last_of_section:
                for i in range(4):
                    put("drum", snare, t_bar + 3 * beat + (i + 1) * beat / 4, 0.3 + 0.12 * i)

    # --- ミックス（バスごとの音量とリバーブ送り）
    g = {"pluck": 0.55, "mel": 0.38, "bass": 0.30, "pad": 0.12, "kick": 0.30, "drum": 0.40, "hat": 0.14}
    dry = (g["pluck"] * bus["pluck"] + g["mel"] * bus["mel"] + g["bass"] * bus["bass"] + g["pad"] * bus["pad"]
           + g["kick"] * bus["kick"] + g["drum"] * bus["drum"] + g["hat"] * _lowpass(bus["hat"], 9000, 1))
    send = 0.22 * g["pluck"] * bus["pluck"] + 0.32 * g["mel"] * bus["mel"] + 0.12 * g["pad"] * bus["pad"] + 0.14 * g["drum"] * bus["drum"]
    mix = dry + _fftconv(send, _reverb_ir(0.35))
    mix = _highpass(mix, 32, 1)
    mix = mix[:int(seconds * SR)]

    # --- マスタリング: 軽いコンプ（tanh）→ ラウドネス約 -18 LUFS → ピーク -1 dBFS 以下
    mix = np.tanh(mix * 1.5) / math.tanh(1.5) * 0.7
    target = -18.0
    mix *= 10 ** ((target - _lufs(mix)) / 20)
    lim = 10 ** (-1 / 20)
    peak = float(np.max(np.abs(mix))) if len(mix) else 0.0
    if peak > lim:
        mix = lim * np.tanh(mix / lim)
        mix *= 10 ** (min(0.0, target - _lufs(mix)) / 20)
    return _fade(mix, 0.01, 0.02)

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
    for n in ("pop", "coin", "sparkle", "whoosh", "ding", "reveal", "riser", "tick"):
        write_wav(out / f"sfx_{n}.wav", sfx(n))
    write_wav(out / "bgm_synth.wav", bgm(60))
    print("wrote", out)
