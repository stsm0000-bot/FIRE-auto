# -*- coding: utf-8 -*-
"""
audio_synth.py ― 効果音と BGM を numpy だけで合成する（素材の権利問題をゼロにするため）
  効果音: pop（要素が出る）, coin（数字が伸びる）, sparkle（合計・締め）, whoosh（章の切り替え）, ding（章扉）
          reveal（ジャーン）, riser（盛り上げ）, tick（小さなクリック）
          物語用: step（足音）, door（ドア）, hammer（とんかち）, cash（チャリーン）, stamp（ハンコ）, boing（ずっこけ）,
                  sad（しょぼん）, shock（びっくり）, jingle_open（冒頭ジングル 1.5 秒）, jingle_end（締めジングル 2 秒）
  環境音: ambience(name, seconds, seed) ― street / night / rain / room / site。つなぎ目の目立たないループ素材、約 -30 LUFS。
  BGM:    明るいポップ調（イントロ 1 小節 → A 8 小節 → B 8 小節 → A …）。
          ピアノ／ウクレレ風プラック＋サインベース＋ローパスのパッド＋キック／スネア／ハット＋ペンタトニックの短いメロディ。
          軽いリバーブと tanh コンプ、ラウドネス約 -18 LUFS、ピーク -1 dBFS 以下に整える。
外部 API（他ファイルから呼ばれる）: sfx(name) / ambience(name, seconds, seed) / bgm(seconds, bpm, seed) / write_wav(path, data)
  いずれも float の numpy 配列（-1〜1、24 kHz モノラル）を扱う。
検査: python audio_synth.py sheet out_dir  → 全効果音を 0.4 秒おきに並べた sfx_sheet.wav、各環境音 6 秒の amb_*.wav、ラウドネス表
      python audio_synth.py out_dir        → 個別の sfx_*.wav / amb_*.wav / bgm_synth.wav
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

# ---------------------------------------------------------------- 追加部品（物語用の効果音・環境音で使う）
def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)

def _bandpass(x: np.ndarray, lo: float, hi: float, order: float = 2) -> np.ndarray:
    return _fft_filter(x, lambda f: ((f / lo) ** order / np.sqrt(1 + (f / lo) ** (2 * order))) / np.sqrt(1 + (f / hi) ** (2 * order)))

def _put(out: np.ndarray, sig: np.ndarray, t0: float, gain: float = 1.0) -> None:
    """out の t0 秒の位置に sig を足し込む（はみ出しは切る）"""
    st = int(round(t0 * SR))
    if st < 0 or st >= len(out): return
    m = min(len(sig), len(out) - st)
    out[st:st + m] += sig[:m] * gain

def _put_wrap(out: np.ndarray, sig: np.ndarray, t0: float, gain: float = 1.0) -> None:
    """ループ素材用: 末尾からはみ出た分は頭に回す"""
    n = len(out)
    if n == 0: return
    st = int(round(t0 * SR)) % n
    sig = sig[:n]
    first = min(len(sig), n - st)
    out[st:st + first] += sig[:first] * gain
    if first < len(sig):
        out[:len(sig) - first] += sig[first:] * gain

def _norm(x: np.ndarray, lufs: float = -18.0, peak: float = 0.6, max_drive: float = 1.6) -> np.ndarray:
    """ラウドネスを目標 LUFS に合わせる。ピークが上限を超えるときは bgm と同じ流儀で tanh の軽いリミッタ
    （押し込みは最大 max_drive 倍まで）に通し、上限 peak を超えない＝クリップしないようにする。
    打撃系（足音・とんかち）は山が鋭いので目標より数 dB 小さく落ち着く"""
    x = x * 10 ** ((lufs - _lufs(x)) / 20)
    p = float(np.max(np.abs(x))) if len(x) else 0.0
    if p > peak:
        drive = min(p / peak, max_drive)
        x = peak * np.tanh(x * (drive / p))
        x = x * 10 ** (min(0.0, lufs - _lufs(x)) / 20)
    return x

def _slow_lfo(n: int, rate_hz: float, seed: int, depth: float = 1.0) -> np.ndarray:
    """ゆっくり揺れる制御信号（ノイズをローパス → 0〜1 に正規化 → (1-depth)〜1）"""
    x = _lowpass(_noise(n, seed), rate_hz, 2)
    x = (x - x.min()) / (x.max() - x.min() + 1e-9)
    return 1 - depth + depth * x

def _loop(x: np.ndarray, n: int, xf_sec: float = 1.0) -> np.ndarray:
    """長さ n+xf 以上の x から、末尾 xf 秒を頭にクロスフェードして、つなぎ目の目立たない n サンプルのループ素材を作る"""
    xf = min(int(xf_sec * SR), n // 2, max(len(x) - n, 0))
    y = x[:n].copy()
    if xf > 0:
        w = np.linspace(0, 1, xf)
        y[:xf] = y[:xf] * w + x[n:n + xf] * (1 - w)
    return y

def _bird(rng: np.random.Generator) -> np.ndarray:
    """さえずり 1 回ぶん（2〜5 音の、ピッチが動く短いサイン波）"""
    k = int(rng.integers(2, 6)); out = np.zeros(int((0.16 * k + 0.1) * SR))
    base = rng.uniform(2400, 4200); pos = 0.0
    for _ in range(k):
        d = rng.uniform(0.04, 0.09); n = int(d * SR); t = np.arange(n) / SR
        f0 = base * rng.uniform(0.9, 1.15); f1 = f0 * rng.uniform(0.75, 1.4)
        shape = np.sin(np.pi * t / d) if rng.random() < 0.5 else t / d
        f = f0 * (f1 / f0) ** shape
        s = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.sin(np.pi * t / d) ** 0.7
        _put(out, s, pos); pos += d + rng.uniform(0.02, 0.07)
    return out

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
SFX_NAMES = ("pop", "coin", "sparkle", "whoosh", "ding", "reveal", "riser", "tick",
             "step", "door", "hammer", "cash", "stamp", "boing", "sad", "shock", "jingle_open", "jingle_end")
AMBIENCE_NAMES = ("street", "night", "rain", "room", "site")

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
    # ---- 以下、物語用（v3）。長さ 0.2〜1.2 秒（ジングルは 1.5 / 2 秒）、_norm で pop/coin と同程度のラウドネスに揃える
    if name == "step":
        # 足音 2 歩（とっ、とっ）: 短い中低域のノック＋ごく短い擦れノイズ。軽く
        out = np.zeros(int(0.45 * SR))
        for i, (t0, f0, sd) in enumerate(((0.0, 190, 31), (0.22, 170, 32))):
            n = int(0.12 * SR); t = np.arange(n) / SR
            f = f0 + 130 * np.exp(-t * 120)
            knock = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t / 0.025)
            nz = _bandpass(_noise(n, sd), 600, 4000, 2) * np.exp(-t / 0.010) * 0.7
            s = (knock + nz) * np.minimum(t / 0.0015, 1.0)
            _put(out, _fade(s, 0.002, 0.03), t0, 1.0 if i == 0 else 0.85)
        return _norm(out, -19.0, 0.55)
    if name == "door":
        # ドアが開いて閉まる: カチャ（金属の小さなクリック 3 つ）… 擦れ … パタン（低いドン＋木の胴鳴り＋ラッチ）
        out = np.zeros(int(1.0 * SR))
        for j, (dt, fc, sd, g) in enumerate(((0.0, 2600, 41, 0.5), (0.028, 3400, 42, 0.7), (0.07, 2100, 43, 0.45))):
            n = int(0.05 * SR); t = np.arange(n) / SR
            c = _bandpass(_noise(n, sd), fc * 0.6, fc * 1.8, 2) * np.exp(-t / 0.006)
            c += 0.5 * np.sin(_TWO_PI * fc * t) * np.exp(-t / 0.004)
            _put(out, _fade(c * np.minimum(t / 0.002, 1.0), 0.002, 0.01), dt, g)
        n = int(0.4 * SR); t = np.arange(n) / SR
        _put(out, _lowpass(_noise(n, 44), 500, 2) * np.sin(np.pi * t / 0.4) ** 2, 0.12, 0.12)
        n = int(0.35 * SR); t = np.arange(n) / SR
        f = 70 + 90 * np.exp(-t * 60)
        thud = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t / 0.05)
        body = _bandpass(_noise(n, 45), 250, 1600, 2) * np.exp(-t / 0.035) * 0.8
        s = np.tanh((thud + body) * 1.4) * np.minimum(t / 0.002, 1.0)
        _put(out, _fade(s, 0.002, 0.05), 0.58, 1.0)
        n = int(0.04 * SR); t = np.arange(n) / SR
        latch = _bandpass(_noise(n, 46), 1800, 5000, 2) * np.exp(-t / 0.005)
        _put(out, _fade(latch * np.minimum(t / 0.002, 1.0), 0.002, 0.01), 0.63, 0.35)
        return _norm(_reverb(out, 0.1, 0.25), -18.5, 0.6)
    if name == "hammer":
        # とんかち 3 回（コン、コン、コン）: 木の短い共鳴 2 本＋高い金属成分＋打撃ノイズ
        out = np.zeros(int(0.8 * SR))
        for i, t0 in enumerate((0.0, 0.26, 0.52)):
            n = int(0.16 * SR); t = np.arange(n) / SR
            k = 1 + 0.03 * ((i * 7) % 3 - 1)   # 打つたびに少しだけピッチを変える
            s = (np.sin(_TWO_PI * 1250 * k * t) * np.exp(-t / 0.02) + 0.8 * np.sin(_TWO_PI * 520 * k * t) * np.exp(-t / 0.045)
                 + 0.35 * np.sin(_TWO_PI * 2900 * k * t) * np.exp(-t / 0.008))
            s += _bandpass(_noise(n, 51 + i), 900, 6000, 2) * np.exp(-t / 0.004) * 0.9
            _put(out, _fade(s * np.minimum(t / 0.0015, 1.0), 0.002, 0.03), t0, (1.0, 0.92, 1.0)[i])
        return _norm(_reverb(out, 0.12, 0.25), -18.0, 0.6)
    if name == "cash":
        # レジの「チャリーン」＋お札: キーのカチ → ベルの長い鳴り（非整数倍音、2 打）→ 紙のこすれ
        out = np.zeros(int(1.15 * SR))
        n = int(0.05 * SR); t = np.arange(n) / SR
        key = _bandpass(_noise(n, 61), 1500, 6000, 2) * np.exp(-t / 0.005) + 0.4 * np.sin(_TWO_PI * 3000 * t) * np.exp(-t / 0.004)
        _put(out, _fade(key * np.minimum(t / 0.002, 1.0), 0.002, 0.01), 0.0, 0.5)
        n = int(0.75 * SR); t = np.arange(n) / SR; f0 = 2350.0
        bell = (np.sin(_TWO_PI * f0 * t) * np.exp(-t / 0.28) + 0.55 * np.sin(_TWO_PI * f0 * 1.48 * t + 0.4) * np.exp(-t / 0.16)
                + 0.3 * np.sin(_TWO_PI * f0 * 2.21 * t) * np.exp(-t / 0.09) + 0.2 * np.sin(_TWO_PI * f0 * 0.5 * t) * np.exp(-t / 0.3))
        bell = _fade(bell * np.minimum(t / 0.002, 1.0), 0.002, 0.05)
        _put(out, bell, 0.04, 0.7); _put(out, bell, 0.10, 0.5)
        n = int(0.6 * SR); t = np.arange(n) / SR
        env = sum(np.exp(-((t - c) / w) ** 2) for c, w in ((0.05, 0.03), (0.14, 0.04), (0.25, 0.03), (0.33, 0.05), (0.45, 0.03)))
        paper = _bandpass(_noise(n, 62), 1800, 9000, 2) * env * (1 + 0.4 * np.sin(_TWO_PI * 37 * t))
        _put(out, _fade(paper, 0.01, 0.05), 0.45, 0.22)
        return _norm(_reverb(out, 0.15, 0.3), -18.5, 0.6)
    if name == "stamp":
        # ハンコ（ドン）: 低いピッチ下降＋中域の「パシッ」を軽く tanh で潰す
        n = int(0.35 * SR); t = np.arange(n) / SR
        f = 55 + 160 * np.exp(-t * 70)
        thud = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t / 0.07)
        smack = _bandpass(_noise(n, 71), 180, 2500, 2) * np.exp(-t / 0.018) * 1.2
        s = np.tanh((thud * 1.3 + smack) * 1.5) * np.minimum(t / 0.0015, 1.0)
        return _norm(_fade(_reverb(s, 0.1, 0.25), 0.002, 0.05), -17.5, 0.65)
    if name == "boing":
        # ずっこけ（ぽよん）: 三角波のピッチが揺れながら下がる
        n = int(0.6 * SR); t = np.arange(n) / SR
        f = (640 * np.exp(-t / 0.18) + 140) * (1 + 0.06 * np.sin(_TWO_PI * 14 * t) * np.exp(-t / 0.25))
        ph = _TWO_PI * np.cumsum(f) / SR
        tri = 2 * np.abs(2 * ((ph / _TWO_PI) % 1) - 1) - 1
        s = (tri * 0.7 + 0.3 * np.sin(2 * ph) * np.exp(-t / 0.12)) * np.exp(-t / 0.22)
        s = _lowpass(s, 2500, 1) * np.minimum(t / 0.004, 1.0)
        return _norm(_fade(s, 0.003, 0.05), -18.0, 0.6)
    if name == "sad":
        # しょぼん: 柔らかい 2 音（E4 → C4）がそれぞれ語尾で下がる。小さめ
        out = np.zeros(int(0.95 * SR))
        for i, (nm, t0, ln) in enumerate((("E4", 0.0, 0.45), ("C4", 0.42, 0.53))):
            f0 = _nf(nm); n = int(ln * SR); t = np.arange(n) / SR
            bend = 2 ** (-(t / ln) ** 1.5 * (1.5 / 12))       # 終わりに向けて 1.5 半音下がる
            ph = _TWO_PI * np.cumsum(f0 * bend) / SR
            s = np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
            env = np.minimum(t / 0.03, 1.0) * np.exp(-t / 0.25) * np.minimum(1.0, np.maximum(0.0, (ln - t) / 0.08))
            _put(out, _fade(_lowpass(s * env, 1800, 1), 0.01, 0.05), t0, 1.0 if i == 0 else 0.7)
        return _norm(_reverb(out, 0.2, 0.3), -24.0, 0.4)
    if name == "shock":
        # びっくり（ジャン）: 短いオーケストラヒット風。短調の鋸波スタブ＋ティンパニ風の低音＋シンバルのノイズ
        n = int(0.7 * SR); t = np.arange(n) / SR
        out = np.zeros(n)
        for i, nm in enumerate(("C3", "G3", "C4", "Eb4", "G4", "C5", "Eb5")):
            f = _nf(nm)
            for det in (-0.006, 0.006):
                out += (2 * ((t * f * (1 + det) + i * 0.23) % 1) - 1) * 0.5 * (1.0 - 0.07 * i)
        env = np.minimum(t / 0.012, 1.0) * (np.exp(-t / 0.16) * 0.8 + 0.2 * np.exp(-t / 0.4))
        out = _lowpass(out * env, 3500, 1) / 7
        f = 60 + 40 * np.exp(-t * 25)
        out += np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t / 0.18) * 0.8
        out += _highpass(_noise(n, 81), 2500, 2) * np.exp(-t / 0.09) * 0.35
        out *= np.minimum(t / 0.003, 1.0)
        out = _reverb(out, 0.3, 0.35) * np.minimum(1.0, np.maximum(0.0, (0.7 - t) / 0.12))
        return _norm(_fade(out, 0.003, 0.05), -17.0, 0.65)
    if name == "jingle_open":
        # 冒頭ジングル 1.5 秒: 上昇 3 音（プラック、オクターブ下を薄く重ねる）→ パッドが膨らむ → キラキラ
        n = int(1.5 * SR); t = np.arange(n) / SR
        out = np.zeros(n)
        for i, nm in enumerate(("C5", "E5", "G5")):
            _put(out, _pluck(_nf(nm), 0.7, bright=1.2, seed=90 + i), i * 0.14, 1.0)
            _put(out, _pluck(_nf(nm) / 2, 0.7, bright=0.8, seed=95 + i), i * 0.14, 0.5)
        _put(out, _pad_chord([_nf(x) for x in ("C4", "E4", "G4", "C5")], 1.2, seed=1), 0.28, 0.9)
        for i, nm in enumerate(("C6", "E6", "G6", "C7", "E7", "G7", "C7", "E7")):
            f = _nf(nm); m = int(0.4 * SR); tt = np.arange(m) / SR
            s = (np.sin(_TWO_PI * f * tt) + 0.3 * np.sin(_TWO_PI * f * 2 * tt) * np.exp(-tt / 0.06)) * np.exp(-tt / 0.12)
            _put(out, _fade(s * np.minimum(tt / 0.002, 1.0), 0.002, 0.03), 0.5 + i * 0.055, 0.35 + 0.03 * i)
        out = _reverb(out, 0.3, 0.4) * np.minimum(1.0, np.maximum(0.0, (1.5 - t) / 0.2))
        return _norm(_fade(out, 0.003, 0.08), -18.0, 0.6)
    if name == "jingle_end":
        # 締めジングル 2 秒: 下がって落ち着く 3 音 → 主和音（丸いプラック＋低いパッド＋ベース）、長めの残響
        n = int(2.0 * SR); t = np.arange(n) / SR
        out = np.zeros(n)
        for i, nm in enumerate(("G5", "E5", "D5")):
            _put(out, _pluck(_nf(nm), 0.6, bright=0.6, seed=100 + i), i * 0.22, 0.9 - 0.1 * i)
        for i, nm in enumerate(("C4", "E4", "G4", "C5")):
            _put(out, _pluck(_nf(nm), 1.3, bright=0.5, seed=110 + i), 0.66 + i * 0.03, 0.8)
        _put(out, _lowpass(_pad_chord([_nf(x) for x in ("C3", "G3", "C4", "E4")], 1.3, seed=2), 900, 1), 0.62, 1.2)
        _put(out, _bass_note(_nf("C2"), 1.2), 0.66, 0.6)
        out = _reverb(out, 0.35, 0.45) * np.minimum(1.0, np.maximum(0.0, (2.0 - t) / 0.35))
        return _norm(_fade(out, 0.003, 0.1), -19.0, 0.55)
    raise ValueError(name)

# ---------------------------------------------------------------- 環境音（ループ素材）
def ambience(name: str, seconds: float, seed: int = 1) -> np.ndarray:
    """指定秒数の環境音。末尾→頭がつながるループ素材（約 -30 LUFS、小さめ）。
    長い尺（数分以上）は、十数秒ぶんを作って np.tile で繰り返すほうがメモリも時間も軽い"""
    n = int(seconds * SR)
    if n <= 0: return np.zeros(0)
    xf = min(1.0, seconds / 2)
    m = n + int(xf * SR)                     # 背景はクロスフェードぶん長めに作る
    rng = np.random.default_rng(seed * 1000 + len(name))
    tm = np.arange(m) / SR
    if name == "street":
        # 風の低いノイズがゆっくり膨らみ、木の葉のざわめきが薄く乗る。ときどき鳥
        bg = _lowpass(_noise(m, seed), 260, 2) * _slow_lfo(m, 0.25, seed + 1, 0.7)
        bg += _bandpass(_noise(m, seed + 2), 300, 1200, 2) * _slow_lfo(m, 0.4, seed + 3, 0.9) * 0.15
        out = _loop(bg, n, xf)
        t_ev = rng.uniform(0.0, 1.5)
        while t_ev < seconds:
            _put_wrap(out, _bird(rng), t_ev, rng.uniform(0.5, 1.0) * 0.12)
            t_ev += rng.uniform(1.2, 3.5)
    elif name == "night":
        # 遠くの車（低い唸り＋ときどき通り過ぎる膨らみ）＋虫の音（リーン、リーン）2 匹
        rumble = _lowpass(_noise(m, seed), 140, 2) * (0.5 + 0.5 * _slow_lfo(m, 0.2, seed + 1))
        road = _bandpass(_noise(m, seed + 2), 150, 900, 2)
        env = np.full(m, 0.12); t_ev = rng.uniform(0.0, 4.0)
        while t_ev < seconds + 1:
            env += np.exp(-((tm - t_ev) / rng.uniform(1.5, 3.0)) ** 2) * rng.uniform(0.4, 1.0)
            t_ev += rng.uniform(5.0, 12.0)
        out = _loop(rumble * 0.8 + road * env * 0.5, n, xf)
        for j in range(2):
            f0 = rng.uniform(3800, 4600); trem = rng.uniform(26, 36); dur = rng.uniform(0.55, 0.8); gap = rng.uniform(0.3, 0.6)
            tt = rng.uniform(0.0, 1.0)
            while tt < seconds:
                k = int(dur * SR); t = np.arange(k) / SR
                s = np.sin(_TWO_PI * f0 * t) * (0.55 + 0.45 * np.sin(_TWO_PI * trem * t)) * np.sin(np.pi * t / dur) ** 0.5
                s += 0.15 * np.sin(_TWO_PI * f0 * 2 * t) * np.sin(np.pi * t / dur)
                _put_wrap(out, s, tt, (0.05, 0.03)[j])
                tt += dur + gap * rng.uniform(0.9, 1.3)
    elif name == "rain":
        # 雨: 高域寄りの広いノイズがゆっくり強弱＋遠くの低い層。ときどき大きめの雫（ピチョン／ポツ）
        bg = _bandpass(_noise(m, seed), 400, 9000, 1) * (0.75 + 0.25 * _slow_lfo(m, 0.3, seed + 1))
        bg += _lowpass(_noise(m, seed + 2), 300, 2) * 0.35
        out = _loop(bg, n, xf)
        t_ev = rng.uniform(0.0, 0.5); i = 0; since_big = 0
        while t_ev < seconds:
            d = rng.uniform(0.03, 0.08); k = int(d * SR); t = np.arange(k) / SR
            f0 = rng.uniform(900, 2600)
            f = f0 * (1 + 0.6 * np.exp(-t / 0.01)) if rng.random() < 0.5 else f0 * (1 + 0.5 * t / d)
            s = np.sin(_TWO_PI * np.cumsum(f) / SR) * np.exp(-t / (d * 0.35))
            s += _bandpass(_noise(k, seed + 100 + i), 1500, 7000, 2) * np.exp(-t / 0.004) * 0.6
            big = rng.random() < 0.25 or since_big >= 4          # 4〜5 粒に 1 つは大きめ
            since_big = 0 if big else since_big + 1
            _put_wrap(out, _fade(s, 0.002, 0.01), t_ev, rng.uniform(2.5, 3.5) if big else rng.uniform(0.5, 1.0))
            t_ev += rng.uniform(0.15, 0.9); i += 1
    elif name == "room":
        # 静かな室内: 50 Hz のハム（倍音 2 本）がわずかに揺れる＋空気感のノイズ＋ごく小さい時計（チッ・タッ）
        hum = np.sin(_TWO_PI * 50 * tm) + 0.35 * np.sin(_TWO_PI * 100 * tm + 0.3) + 0.12 * np.sin(_TWO_PI * 150 * tm + 1.1)
        hum *= 0.6 + 0.4 * _slow_lfo(m, 0.15, seed, 1.0)
        air = _lowpass(_noise(m, seed + 1), 180, 2) * 1.0 + _bandpass(_noise(m, seed + 2), 200, 2000, 2) * 0.07
        out = _loop(hum * 0.35 + air, n, xf)
        k = max(1, int(round(seconds))); step = seconds / k     # ループが割り切れるよう 1 秒前後に調整
        for i in range(k):
            q = int(0.025 * SR); t = np.arange(q) / SR; fc = 3200 if i % 2 == 0 else 2600
            s = _bandpass(_noise(q, seed + 10 + i), fc * 0.6, fc * 1.8, 2) * np.exp(-t / 0.003) + 0.4 * np.sin(_TWO_PI * fc * t) * np.exp(-t / 0.003)
            _put_wrap(out, _fade(s, 0.002, 0.006), i * step + 0.3, 0.09)
    elif name == "site":
        # 工事現場: 低い唸り＋遠くの電動工具（鋸波、立ち上がりと負荷でピッチが揺れ、数秒で止む）＋ときどき金属音（カーン）
        rumble = _lowpass(_noise(m, seed), 200, 2) * (0.6 + 0.4 * _slow_lfo(m, 0.3, seed + 1))
        tool = np.zeros(m); t_ev = rng.uniform(0.0, 2.0)
        while t_ev < seconds + 1:
            d = rng.uniform(1.2, 3.0); k = int(d * SR); t = np.arange(k) / SR
            f0 = rng.uniform(95, 170)
            f = f0 * (1 - 0.25 * np.exp(-t / 0.15)) * (1 + 0.05 * np.sin(_TWO_PI * rng.uniform(0.6, 1.5) * t + rng.uniform(0, 6)))
            f *= 1 - 0.3 * np.maximum(0.0, (t - (d - 0.25)) / 0.25)
            ph = np.cumsum(f) / SR
            s = _lowpass((2 * (ph % 1) - 1) + 0.3 * (2 * ((ph * 2.01) % 1) - 1), 1400, 2)
            env = np.minimum(t / 0.15, 1.0) * np.minimum(1.0, np.maximum(0.0, (d - t) / 0.3))
            _put(tool, s * env, t_ev, rng.uniform(0.5, 1.0))
            t_ev += d + rng.uniform(0.8, 3.0)
        out = _loop(rumble * 0.9 + tool * 0.4, n, xf)
        t_ev = rng.uniform(0.3, 2.5); i = 0
        while t_ev < seconds:
            k = int(0.45 * SR); t = np.arange(k) / SR; f0 = rng.uniform(700, 1500)
            s = sum(a * np.sin(_TWO_PI * f0 * r * t + rng.uniform(0, 6)) * np.exp(-t / dc)
                    for r, a, dc in ((1.0, 1.0, 0.18), (1.58, 0.6, 0.12), (2.32, 0.4, 0.08), (3.4, 0.25, 0.05)))
            s += _bandpass(_noise(k, seed + 200 + i), 1500, 6000, 2) * np.exp(-t / 0.004) * 0.7
            s = _highpass(_fade(s * np.minimum(t / 0.002, 1.0), 0.002, 0.05), 400, 1)
            _put_wrap(out, _reverb(s, 0.3, 0.35), t_ev, rng.uniform(0.25, 0.6) * 0.3)
            t_ev += rng.uniform(1.5, 4.5); i += 1
    else:
        raise ValueError(name)
    return _norm(out, -30.0, 0.35)

def _sheet(out_dir, gap: float = 0.4, amb_seconds: float = 6.0) -> str:
    """検査用: 全効果音を gap 秒おきに並べた sfx_sheet.wav と、各環境音 amb_*.wav（と個別の sfx_*.wav）を書き出し、
    長さ・ピーク・LUFS の表を文字列で返す"""
    from pathlib import Path
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rows = []; parts = []
    for nm in SFX_NAMES:
        x = sfx(nm); parts += [x, np.zeros(int(gap * SR))]
        rows.append((nm, len(x) / SR, float(np.max(np.abs(x))), _lufs(x)))
        write_wav(out_dir / f"sfx_{nm}.wav", x)
    sheet = np.concatenate(parts)
    write_wav(out_dir / "sfx_sheet.wav", sheet)
    for nm in AMBIENCE_NAMES:
        x = ambience(nm, amb_seconds)
        rows.append((f"amb:{nm}", len(x) / SR, float(np.max(np.abs(x))), _lufs(x)))
        write_wav(out_dir / f"amb_{nm}.wav", x)
    lines = [f"{'name':12s} {'sec':>6s} {'peak':>6s} {'LUFS':>6s}"]
    lines += [f"{nm:12s} {sec:6.2f} {pk:6.3f} {lu:6.1f}" + ("  CLIP!" if pk > 1 else "") for nm, sec, pk, lu in rows]
    lines.append(f"wrote {out_dir / 'sfx_sheet.wav'} ({len(sheet) / SR:.1f}s), amb_*.wav ({amb_seconds:g}s each), sfx_*.wav")
    return "\n".join(lines)

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
    args = sys.argv[1:]
    if args and args[0] == "sheet":
        # python audio_synth.py sheet out_dir  → 全効果音を 0.4 秒おきに並べた wav と各環境音 6 秒の wav、ラウドネス表
        print(_sheet(Path(args[1] if len(args) > 1 else ".")))
    else:
        out = Path(args[0] if args else ".")
        out.mkdir(parents=True, exist_ok=True)
        for n in SFX_NAMES:
            write_wav(out / f"sfx_{n}.wav", sfx(n))
        for n in AMBIENCE_NAMES:
            write_wav(out / f"amb_{n}.wav", ambience(n, 6))
        write_wav(out / "bgm_synth.wav", bgm(60))
        print("wrote", out)
