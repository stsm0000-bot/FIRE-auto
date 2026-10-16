# -*- coding: utf-8 -*-
"""
scenes.py ― 物語シーン（layout: scene）の描画。docs/12_物語シーンの書き方.md の語彙を全部実装する。

  render_scene(data, step, prev_step, anim, kind, faces, talking, variant, script_dir) -> {{BODY}} に入れる HTML 断片
    data     : YAML の場面（bg, time, weather, camera, chars, props, steps …）
    kind     : "long"(1920x1080) / "short"(1080x1920)
    faces    : {"ぽん太": "surprised", ...} その台詞でのキャラの表情
    talking  : 話している側のキャラ名（None なら誰も話していない）
    variant  : "closed"（全員口を閉じる）/ "open"（talking の口を開く）/ "blink"（全員まばたき）
               3 変種で口と目以外は 1 ピクセルも変わらない（乱数は場面 id で seed 固定）
    anim     : True のとき、prev_step < step で新しく出る小道具に .enter.pop を付け、場面の最初（prev_step==0）なら
               camera の動きと walk の歩き（画面外 → at へ）を CSS animation で 1.3 秒ぶん付ける。False は最終状態の静止画。

  CSS の正本は templates/slide.html の「/* ---- scene ---- */」節。SCENE_CSS はそれを読み出したもの。

  見本:  python scenes.py preview out_dir      背景13×time3 / 天気 / ポーズ8×2 / 小道具全種 / カメラ6 の sheet PNG を書き出す
          （Chrome: /usr/bin/chromium か CHROME_PATH、無ければ which chromium chromium-browser google-chrome）
"""
from __future__ import annotations

import hashlib, html as _html, math, os, platform, random, re, shutil, subprocess, sys
from pathlib import Path

import characters

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "slide.html"

INK = "#1F2A44"; PAPER = "#FFF8E7"; ACCENT = "#FF7A1A"; GREEN = "#1FA463"; GOLD = "#F2B705"; BLUE = "#2F80ED"
RED = "#D7263D"; MUTE = "#6E6A5E"

# ---------------------------------------------------------------- 語彙（docs/12 と同じ。増やさない）
BGS = ("street", "house_old", "house_new", "room_old", "room_new", "office", "desk", "bank", "bankbook", "site", "night", "sky", "blank")
TIMES = ("day", "evening", "night")
WEATHERS = ("sun", "cloud", "rain")
CAMERAS = ("still", "in", "out", "pan_left", "pan_right", "shake")
ACTS = characters.ACTS
PROPS = ("headline", "price", "sign", "bubble", "arrow", "calendar", "stamp", "coins", "money", "cross", "check",
         "sweat", "exclaim", "question", "heart", "zzz", "star", "photo", "counter")
HEAD_MARKS = ("sweat", "exclaim", "question", "heart", "zzz", "star")
EXTERIOR = ("street", "house_old", "house_new", "night", "sky")      # 天気（雲・雨）を重ねる背景
COUNTER_BG = {"desk": 70, "office": 70, "bank": 70}                  # カウンターの奥に立つ分、キャラを上げる px

# ---------------------------------------------------------------- 画面の寸法（slide.html の .body 領域）
AREA = {"long": (1920, 1080 - 124 - 288), "short": (1080, 1920 - 124 - 778)}   # 上ピル帯 124 / 下は字幕帯＋58
CHAR_SIZE = {"long": 420, "short": 520}
CHAR_SIZE_2 = {"long": 420, "short": 440}            # ショートで 2 人のとき
def _final_at(at) -> str:
    """offleft / offright は「画面外から歩いて入る」の指定。止まる位置は left / right"""
    return {"offleft": "left", "offright": "right"}.get(str(at), str(at))

AT_X = {"long": {"left": 20, "center": 50, "right": 80, "offleft": -16, "offright": 116},
        "short": {"left": 25, "center": 50, "right": 75, "offleft": -30, "offright": 130}}
PROP_X = {"long": {"left": 22, "center": 50, "right": 78, "offleft": -20, "offright": 120},
          "short": {"left": 25, "center": 50, "right": 75, "offleft": -30, "offright": 130}}

def geometry(kind: str) -> tuple[int, int, int]:
    """(幅, 高さ, 地面の y) px"""
    W, H = AREA[kind]
    return W, H, round(H * 0.82)

def esc(s) -> str:
    return (str(s).replace("★", "").rstrip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("\n", "<br>"))

def attr(s) -> str:
    return str(s).replace("★", "").rstrip().replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;").replace("\n", "&#10;")

def _pct(at, kind: str, table) -> float:
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return float(str(at).rstrip("%"))
    except ValueError:
        return table[kind].get(str(at), 50)

# ---------------------------------------------------------------- 色（time / weather）
def palette(time: str, weather: str) -> dict:
    P = dict(time=time, weather=weather,
             sky_top="#BEE3FF", sky_bot="#EEF8FF", sun=GOLD, cloud="#FFFFFF", cloud_sh="#D9E6F0",
             window="#CFEFFF", hill="#BFE3A6", hill2="#A8D48C", grass="#C5E6A4", road="#9AA3B0", curb="#E2DCCB",
             wall="#F4F1E8", floor="#DCCDB0", door="#2F80ED", tint=None, glow=False)
    if weather == "cloud":
        P.update(sky_top="#C9D3DC", sky_bot="#E8EDF1", cloud="#D9DFE6", cloud_sh="#B9C2CC", sun=None)
    elif weather == "rain":
        P.update(sky_top="#8F9CAB", sky_bot="#C4CDD6", cloud="#AEB7C2", cloud_sh="#8F99A6", sun=None, road="#7F8A99")
    if time == "evening":
        P.update(sky_top="#FF9A4D", sky_bot="#FFE3B0", sun=ACCENT, tint="rgba(255,110,20,.16)", window="#FFE9B8")
        if weather != "sun":
            P.update(sky_top="#B07A5E", sky_bot="#E8C9AE")
    elif time == "night":
        P.update(sky_top="#121C44", sky_bot="#2B3B74", sun=None, tint="rgba(14,22,66,.42)", window="#FFE082", glow=True,
                 cloud="#4C5A86", cloud_sh="#38456C")
    return P

# ---------------------------------------------------------------- SVG の部品
def _rect(x, y, w, h, fill, rx=0, sw=0, stroke=INK, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if sw else ""
    return f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="{rx}" fill="{fill}"{s}{extra}/>'

def _circ(cx, cy, r, fill, sw=0, stroke=INK, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if sw else ""
    return f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{fill}"{s}{extra}/>'

def _ellipse(cx, cy, rx, ry, fill, sw=0, stroke=INK, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if sw else ""
    return f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" ry="{ry:.0f}" fill="{fill}"{s}{extra}/>'

def _path(d, fill="none", sw=0, stroke=INK, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"' if sw else ""
    return f'<path d="{d}" fill="{fill}"{s}{extra}/>'

def _text(x, y, t, size, fill=INK, anchor="middle", extra="", outline=None):
    o = f' stroke="{outline}" stroke-width="{size*.18:.0f}" paint-order="stroke" stroke-linejoin="round"' if outline else ""
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" font-weight="900" fill="{fill}" text-anchor="{anchor}"{o}{extra}>'
            f'{_html.escape(str(t))}</text>')

def _vtext(x, y, t, size, fill, extra=""):
    return "".join(_text(x, y + i * size * 1.05, ch, size, fill, extra=extra) for i, ch in enumerate(t))

def cloud(cx, cy, s, fill, shade):
    parts = []
    for col, dy in ((shade, 10 * s), (fill, 0)):
        parts.append(_rect(cx - 90 * s, cy - 10 * s + dy, 190 * s, 44 * s, col, 22 * s))
        for dx, ddy, r in ((-58, 0, 34), (-12, -30, 48), (44, -12, 40), (84, 8, 28)):
            parts.append(_circ(cx + dx * s, cy + ddy * s + dy, r * s, col))
    return "".join(parts)

def sun(cx, cy, r, col):
    rays = "".join(f'<line x1="{cx + math.cos(a) * (r + 14):.0f}" y1="{cy + math.sin(a) * (r + 14):.0f}" '
                   f'x2="{cx + math.cos(a) * (r + 40):.0f}" y2="{cy + math.sin(a) * (r + 40):.0f}" stroke="{col}" stroke-width="10" stroke-linecap="round"/>'
                   for a in [i * math.pi / 6 for i in range(12)])
    return _circ(cx, cy, r + 26, col, extra=' opacity=".25"') + rays + _circ(cx, cy, r, col, 6, "#E0A400")

def moon(cx, cy, r):
    return (_circ(cx, cy, r + 30, "#FFF3B0", extra=' opacity=".15"') + _circ(cx, cy, r, "#FFF3B0") +
            _circ(cx + r * .45, cy - r * .2, r * .82, "#1B2755"))

def stars(seed, W, ymax, n=60):
    rnd = random.Random(seed); out = []
    for _ in range(n):
        x = rnd.uniform(-160, W + 160); y = rnd.uniform(10, ymax); r = rnd.choice((2, 2, 3, 3, 4))
        out.append(_circ(x, y, r, "#FFFFFF", extra=f' opacity="{rnd.uniform(.5, 1):.2f}"'))
    for _ in range(5):
        x = rnd.uniform(0, W); y = rnd.uniform(20, ymax * .8); s = rnd.uniform(8, 14)
        out.append(_path(f"M{x:.0f} {y - s:.0f} L{x + s * .3:.0f} {y - s * .3:.0f} L{x + s:.0f} {y:.0f} L{x + s * .3:.0f} {y + s * .3:.0f} "
                         f"L{x:.0f} {y + s:.0f} L{x - s * .3:.0f} {y + s * .3:.0f} L{x - s:.0f} {y:.0f} L{x - s * .3:.0f} {y - s * .3:.0f} Z", "#FFFFFF"))
    return "".join(out)

def hills(W, G, c1, c2):
    return (_ellipse(W * .18, G + 40, W * .45, 190, c2) + _ellipse(W * .85, G + 60, W * .5, 210, c2) +
            _ellipse(W * .5, G + 80, W * .62, 180, c1))

def tree(x, g, s=1.0, leaf="#5BAE5B", trunk="#8B5A2B"):
    return (_rect(x - 12 * s, g - 90 * s, 24 * s, 90 * s, trunk, 6, 5) + _circ(x - 34 * s, g - 110 * s, 40 * s, leaf, 5) +
            _circ(x + 34 * s, g - 110 * s, 40 * s, leaf, 5) + _circ(x, g - 150 * s, 50 * s, leaf, 5))

def fence(x1, x2, g, h=70, col="#FFFFFF", lean=0, gap=40):
    parts = [_rect(x1, g - h + 14, x2 - x1, 10, col, 3, 4), _rect(x1, g - h * .45, x2 - x1, 10, col, 3, 4)]
    x = x1
    while x < x2:
        parts.append(_path(f"M{x} {g} V{g - h + 10} L{x + 11} {g - h} L{x + 22} {g - h + 10} V{g} Z", col, 4))
        x += gap
    s = "".join(parts)
    return f'<g transform="rotate({lean} {(x1 + x2) / 2:.0f} {g})">{s}</g>' if lean else s

def weeds(x, g, s=1.0, col="#5B8C3A"):
    return _path(f"M{x} {g} q{-10 * s:.0f} {-30 * s:.0f} {-20 * s:.0f} {-44 * s:.0f} M{x} {g} q{2 * s:.0f} {-36 * s:.0f} {6 * s:.0f} {-54 * s:.0f} "
                 f"M{x} {g} q{12 * s:.0f} {-26 * s:.0f} {24 * s:.0f} {-40 * s:.0f} M{x} {g} q{-4 * s:.0f} {-16 * s:.0f} {-14 * s:.0f} {-24 * s:.0f}", sw=5 * s, stroke=col)

def pole(x, g, h):
    return (_rect(x - 9, g - h, 18, h, "#9E968A", 4, 5) + _rect(x - 56, g - h + 26, 112, 12, "#9E968A", 3, 5) +
            _rect(x - 56, g - h + 56, 112, 10, "#9E968A", 3, 4) + _circ(x - 40, g - h + 22, 7, "#DDD") + _circ(x + 40, g - h + 22, 7, "#DDD"))

def wires(x1, x2, y, sag=36):
    return _path(f"M{x1} {y} q{(x2 - x1) / 2:.0f} {sag} {x2 - x1} 0 M{x1} {y + 30} q{(x2 - x1) / 2:.0f} {sag} {x2 - x1} 0", sw=3, stroke="#5A6473")

def plant(x, g, s=1.0):
    return (_path(f"M{x - 34 * s:.0f} {g - 70 * s:.0f} h{68 * s:.0f} l{-10 * s:.0f} {70 * s:.0f} h{-48 * s:.0f} Z", "#C86B3C", 5) +
            _path(f"M{x} {g - 70 * s:.0f} q{-50 * s:.0f} {-40 * s:.0f} {-40 * s:.0f} {-110 * s:.0f} q{30 * s:.0f} {50 * s:.0f} {40 * s:.0f} {110 * s:.0f} "
                  f"q{50 * s:.0f} {-40 * s:.0f} {40 * s:.0f} {-110 * s:.0f} q{-30 * s:.0f} {50 * s:.0f} {-40 * s:.0f} {110 * s:.0f} "
                  f"q{-6 * s:.0f} {-80 * s:.0f} 0 {-130 * s:.0f} q{6 * s:.0f} {50 * s:.0f} 0 {130 * s:.0f}", "#4CAF50", 5))

def rain(seed, W, H, n):
    rnd = random.Random(seed); out = []
    for _ in range(n):
        x = rnd.uniform(-160, W + 160); y = rnd.uniform(-20, H); L = rnd.uniform(26, 54)
        out.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - L * .18:.0f}" y2="{y + L:.0f}" stroke="#DCE9F5" stroke-width="3" stroke-linecap="round" opacity=".75"/>')
    return "".join(out)

def puddle(x, y, w):
    return (_ellipse(x, y, w, w * .22, "#AFCDE6", extra=' opacity=".9"') +
            _ellipse(x - w * .25, y - w * .04, w * .3, w * .06, "#FFFFFF", extra=' opacity=".7"'))

# ---------------------------------------------------------------- 背景の組み立て
class BG:
    """far / mid / near / glow（夜の明かり）/ fore（キャラの前）/ weather（雨）の層に分けて SVG を貯める"""
    def __init__(self, name: str, kind: str, P: dict, uid: str):
        self.name, self.kind, self.P, self.uid = name, kind, P, uid
        self.W, self.H, self.G = geometry(kind)
        self.sky: list[str] = []; self.far: list[str] = []; self.mid: list[str] = []; self.near: list[str] = []
        self.glow: list[str] = []; self.fore: list[str] = []; self.weather: list[str] = []
        self.night = P["time"] == "night"
        self.short = kind == "short"

    # 窓。夜は明かりを glow 層に描く（tint の上に乗る）
    def win(self, x, y, w, h, layer=None, cross=True, broken=False, rx=4, sw=5, pane=None):
        lst = self.mid if layer is None else layer
        lst.append(_rect(x, y, w, h, pane or self.P["window"], rx, sw))
        bars = _path(f"M{x + w / 2:.0f} {y} v{h} M{x} {y + h / 2:.0f} h{w}", sw=max(3, sw - 1)) if cross else ""
        lst.append(bars)
        if broken:
            lst.append(_path(f"M{x + w * .32:.0f} {y} l{w * .14:.0f} {h * .34:.0f} l{-w * .2:.0f} {h * .3:.0f} l{w * .12:.0f} {h * .36:.0f}", sw=3))
            lst.append(_path(f"M{x + w * .46:.0f} {y + h * .34:.0f} l{w * .3:.0f} {-h * .12:.0f} M{x + w * .26:.0f} {y + h * .64:.0f} l{-w * .26:.0f} {h * .1:.0f}", sw=3))
        if self.night:
            self.glow.append(_rect(x - 12, y - 12, w + 24, h + 24, "#FFE082", rx + 10, extra=' opacity=".28"'))
            self.glow.append(_rect(x, y, w, h, "#FFE082", rx, extra=' opacity=".92"'))
            self.glow.append(bars)

    def house(self, cx, base, w, h, wall, roof, door=True, nwin=2, chimney=False, lean=0, layer=None, roof_h=None, broken=False, roof_style="plain"):
        lst = self.mid if layer is None else layer
        x = cx - w / 2; y = base - h; rh = roof_h or h * .5
        g = [_rect(x, y, w, h, wall, 6, 6)]
        if roof_style == "tin":   # 錆びたトタン屋根（縞）
            g.append(_path(f"M{x - 34} {y} L{cx} {y - rh} L{x + w + 34} {y} Z", "#A0522D", 6))
            for k in range(1, 9):
                t = k / 9; g.append(f'<line x1="{x - 34 + (cx - x + 34) * t:.0f}" y1="{y - rh * t:.0f}" x2="{x + w + 34 - (x + w + 34 - cx) * t:.0f}" y2="{y - rh * t:.0f}" stroke="#C27A4A" stroke-width="6"/>')
            g.append(_path(f"M{x - 34} {y} L{cx} {y - rh} L{x + w + 34} {y}", sw=6))
        else:
            g.append(_path(f"M{x - 34} {y} L{cx} {y - rh} L{x + w + 34} {y} Z", roof, 6))
        if chimney:
            g.append(_rect(cx + w * .24, y - rh * .78, 40, rh * .55, INK))
        if door:
            g.append(_rect(cx - 36, base - h * .52, 72, h * .52, self.P["door"] if not broken else "#6D4C41", 8, 5))
            g.append(_circ(cx + 20, base - h * .26, 6, GOLD))
        ww, wh = w * .19, h * .3
        for i in range(nwin):
            wx = x + w * (.14 if i == 0 else .67); self.win(wx, y + h * .18, ww, wh, layer=g, broken=(broken and i == 1))
        s = "".join(g)
        lst.append(f'<g transform="rotate({lean} {cx:.0f} {base:.0f})">{s}</g>' if lean else s)

    # ---- 空・地面・天気
    def sky_rect(self, top=None, bot=None):
        P = self.P
        self.sky.append(f'<defs><linearGradient id="sky_{self.uid}" x1="0" y1="0" x2="0" y2="1">'
                        f'<stop offset="0" stop-color="{top or P["sky_top"]}"/><stop offset="1" stop-color="{bot or P["sky_bot"]}"/></linearGradient></defs>'
                        f'<rect x="-160" y="0" width="{self.W + 320}" height="{self.H}" fill="url(#sky_{self.uid})"/>')

    def celestial(self):
        P, W, G = self.P, self.W, self.G
        if P["time"] == "night":
            self.far.append(stars(self.uid, W, G * .7)); self.far.append(moon(W - (240 if not self.short else 170), 120, 58))
        elif P["time"] == "evening":
            self.far.append(sun(W * .74, G - 150, 74, P["sun"]) if P["sun"] else "")
        elif P["sun"]:
            self.far.append(sun(W - (260 if not self.short else 180), 118, 60, P["sun"]))

    def clouds(self, force=False):
        P, W = self.P, self.W
        if P["weather"] == "sun" and not force:
            return
        rnd = random.Random(self.uid + "c")
        n = 4 if not self.short else 3
        for i in range(n):
            cx = -40 + (W + 80) * (i + .5) / n + rnd.uniform(-60, 60); cy = rnd.uniform(70, 170); s = rnd.uniform(.8, 1.3)
            self.far.append(cloud(cx, cy, s, P["cloud"], P["cloud_sh"]))

    def rainfall(self):
        if self.P["weather"] != "rain":
            return
        self.weather.append(rain(self.uid + "r", self.W, self.H, 150 if not self.short else 110))

    def puddles(self, y=None):
        if self.P["weather"] != "rain":
            return
        y = self.G + 48 if y is None else y
        for fx, w in ((.18, 150), (.56, 190), (.84, 120)):
            self.near.append(puddle(self.W * fx, y, w if not self.short else w * .7))

    def ground(self, col, y=None):
        y = self.G if y is None else y
        self.near.append(_rect(-160, y, self.W + 320, self.H - y + 20, col))

    # ---- 出力
    def layer(self, cls, parts):
        body = "".join(p for p in parts if p)
        return (f'<svg class="layer {cls}" viewBox="-160 0 {self.W + 320} {self.H}" preserveAspectRatio="none" aria-hidden="true">{body}</svg>'
                if body else "")

    def render(self) -> tuple[str, str]:
        """(キャラの後ろ, キャラの前) の HTML"""
        back = [self.layer("sky", self.sky), self.layer("far", self.far), self.layer("mid", self.mid), self.layer("near", self.near)]
        if self.P["tint"]:
            back.append(f'<div class="layer tint" style="background:{self.P["tint"]}"></div>')
        back.append(self.layer("glow", self.glow))
        front = [self.layer("fore", self.fore), self.layer("weather", self.weather)]
        return "".join(back), "".join(front)

# ---------------------------------------------------------------- 背景 13 種
def bg_street(b: BG):
    W, G, P = b.W, b.G, b.P
    b.sky_rect(); b.celestial(); b.clouds()
    b.far.append(hills(W, G - 30, P["hill"], P["hill2"]))
    base = G - 34
    walls = ("#FFFFFF", "#FFF1DC", "#E8F5E9", "#FFF8E7"); roofs = (ACCENT, INK, GREEN, "#C86B3C")
    step = 520 if not b.short else 440
    k = 0; x = -120
    while x < W + 200:
        b.house(x, base, 360, 215, walls[k % 4], roofs[k % 4], nwin=2, chimney=(k % 3 == 1), roof_h=110)
        if k % 2 == 0:
            b.mid.append(tree(x + step * .5, base, .8))
        x += step; k += 1
    b.mid.append(fence(-160, W + 160, base, 54, "#E9E2CF", gap=36))
    for px in (W * .16, W * .62) if not b.short else (W * .2,):
        b.mid.append(pole(px, base, G - 60))
    if not b.short:
        b.mid.append(wires(W * .16, W * .62, 60)); b.mid.append(wires(W * .62, W + 160, 60, 20)); b.mid.append(wires(-160, W * .16, 60, 20))
    else:
        b.mid.append(wires(W * .2, W + 160, 70)); b.mid.append(wires(-160, W * .2, 70, 14))
    b.ground(P["road"], G - 34)
    b.near.append(_rect(-160, G - 34, W + 320, 20, P["curb"]))
    b.near.append(_path(" ".join(f"M{x} {G + 56} h70" for x in range(-160, W + 200, 150)), sw=8, stroke="#F2F2EA"))
    b.puddles()

def _old_new_house(b: BG, old: bool):
    W, G, P = b.W, b.G, b.P
    b.sky_rect(); b.celestial(); b.clouds()
    b.far.append(hills(W, G - 10, P["hill"], P["hill2"]))
    base = G - 8; w = 700 if not b.short else 600; h = 300 if not b.short else 280
    cx = W / 2
    if old:
        b.house(cx, base, w, h, "#D9CBA3", "#A0522D", lean=-2.5, roof_h=150, broken=True, roof_style="tin")
        x = cx - w / 2
        b.mid.append(_path(f"M{x + w * .36:.0f} {base - h + 10} l-18 60 l24 40 l-14 48 M{x + w * .9:.0f} {base - 40} l-30 -50 l10 -40", sw=4, stroke="#8C7B5A"))
        b.mid.append(_rect(x + w * .12, base - h * .07, w * .14, 14, "#8C7B5A", 3, 0, extra=' opacity=".7"'))   # 汚れ
        b.mid.append(fence(-160, cx - w / 2 - 50, base, 64, "#B9AE95", lean=5, gap=44))
        b.mid.append(fence(cx + w / 2 + 50, W + 160, base, 64, "#B9AE95", lean=-6, gap=44))
        b.mid.append(_rect(cx + w / 2 + 90, base - 150, 50, 70, "#8E8E8E", 6, 5) + _rect(cx + w / 2 + 109, base - 80, 12, 80, "#7A7A7A"))  # 錆びたポスト
        b.ground("#C9BA8E")
        for fx in (.05, .2, .34, .5, .66, .8, .93):
            b.near.append(weeds(W * fx, G + 6, 1.1 if fx not in (.34, .66) else 1.5))
        for fx in (.28, .72):
            b.mid.append(weeds(W * fx, base + 2, 1.4, "#6B8E3D"))
    else:
        b.house(cx, base, w, h, "#FFFFFF", ACCENT, roof_h=150, chimney=True)
        x = cx - w / 2
        for wx in (x + w * .14, x + w * .67):   # 窓下の花
            b.mid.append(_rect(wx - 6, base - h + h * .48, w * .19 + 12, 18, "#7CB342", 5, 4))
            b.mid.append("".join(_circ(wx + 14 + i * 26, base - h + h * .48 - 2, 9, c) for i, c in enumerate(("#FF5C8A", "#FFD54F", "#FF5C8A", "#F48FB1", "#FFD54F")[: int(w * .19 / 26)])))
        b.mid.append(fence(-160, cx - w / 2 - 50, base, 64, "#FFFFFF", gap=40))
        b.mid.append(fence(cx + w / 2 + 50, W + 160, base, 64, "#FFFFFF", gap=40))
        b.mid.append(_rect(cx + w / 2 + 90, base - 160, 54, 74, RED, 8, 5) + _rect(cx + w / 2 + 110, base - 86, 14, 86, "#555", 3) +
                     _rect(cx + w / 2 + 100, base - 148, 34, 10, "#FFF", 2))   # 赤いポスト
        b.mid.append(tree(cx - w / 2 - 150, base, 1.0))
        b.ground(P["grass"])
        b.near.append(_path(f"M{cx - 120} {G + 140} Q{cx - 30} {G + 40} {cx - 60} {G - 8} L{cx + 60} {G - 8} Q{cx + 30} {G + 60} {cx + 160} {G + 140} Z", "#EADFC3"))
        for fx in (.08, .3, .7, .92):
            b.near.append(_circ(W * fx, G + 30, 10, "#FF5C8A") + _circ(W * fx + 24, G + 40, 8, "#FFD54F") + weeds(W * fx + 10, G + 48, .7, "#5BAE5B"))
    b.puddles()

def bg_house_old(b: BG): _old_new_house(b, True)
def bg_house_new(b: BG): _old_new_house(b, False)

def bg_room_old(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#E3D5A8", "#D2C38F")
    b.far.append(_rect(-160, G - 36, W + 320, 20, "#9C8A5E"))   # 巾木
    for fx, r in ((.18, 90), (.7, 70), (.86, 120)):   # 染み
        b.far.append(_ellipse(W * fx, 120 + r * .3, r, r * .6, "#B9A373", extra=' opacity=".55"'))
    # 破れた襖（右）
    fx, fy, fw, fh = W * .66, 40, 330 if not b.short else 280, G - 80
    b.far.append(_rect(fx, fy, fw, fh, "#EFE6C8", 4, 6))
    b.far.append(_path(f"M{fx + fw * .5:.0f} {fy} V{fy + fh} M{fx} {fy + fh * .5:.0f} H{fx + fw}", sw=4))
    b.far.append(_path(f"M{fx + fw * .22:.0f} {fy + fh * .25:.0f} l40 30 l-26 36 l50 28 l-20 40 l36 22", "#6D5B3B", 5))
    b.far.append(_path(f"M{fx + fw * .22:.0f} {fy + fh * .25:.0f} l40 30 l-26 36 l50 28 l-20 40 l36 22 l30 -10 l-12 -50 l24 -40 l-40 -30 l10 -40 Z", "#5A4A2E"))
    # 裸電球
    b.far.append(_path(f"M{W * .4:.0f} 0 V70", sw=4) + _circ(W * .4, 94, 26, "#FFF6CC", 4) + _rect(W * .4 - 14, 62, 28, 16, "#8E8E8E", 3, 3))
    if b.night:
        b.glow.append(_circ(W * .4, 94, 26, "#FFE082") + _circ(W * .4, 94, 70, "#FFE082", extra=' opacity=".22"'))
    # 残置物
    bx = W * .03 if not b.short else W * .02
    b.mid.append(_rect(bx, G - 110, 150, 110, "#C9A26B", 6, 5) + _rect(bx, G - 110, 150, 22, "#B08B52") + _rect(bx + 60, G - 110, 30, 110, "#E0CDA4"))
    b.mid.append(_rect(bx + 40, G - 190, 110, 80, "#C9A26B", 6, 5) + _rect(bx + 40, G - 190, 110, 18, "#B08B52"))
    kx = W * .93 if not b.short else W * .9
    b.mid.append(_path(f"M{kx:.0f} {G - 100} l-14 100 h90 l-14 -100 Z", "#8FA6B8", 5) + _path(f"M{kx - 10:.0f} {G - 100} q45 -60 90 0", sw=5))   # バケツ
    b.mid.append(_path(f"M{W * .6:.0f} {G} l20 -140 l40 -10 l-40 150 Z", "#9E9E9E", 4))   # 立てかけた板
    # 畳
    b.ground("#B9B46A")
    for x in range(-160, W + 320, 300):
        b.near.append(_rect(x, G, 300, H - G + 20, "#C2BC72" if (x // 300) % 2 else "#B3AE62"))
        b.near.append(_path(f"M{x} {G} V{H + 20}", sw=5, stroke="#4E6B2E"))
    b.near.append(_path(" ".join(f"M{x} {G + k * 24 + 10} h{W + 320}" for k in range(5) for x in (-160,)), sw=2, stroke="#9C9A4D"))
    tx = W * .52
    b.near.append(_path(f"M{tx:.0f} {G + 30} l60 -14 l50 22 l40 -8 l30 40 l-70 12 l-40 -10 l-60 14 l-30 -34 Z", "#8C6A3C", 4))   # 破れ
    b.near.append(_path(f"M{tx + 30:.0f} {G + 40} l10 -16 M{tx + 110:.0f} {G + 36} l12 18 M{tx + 60:.0f} {G + 70} l-8 14", sw=4, stroke="#D8C78A"))

def bg_room_new(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#FDFCF8", "#F2EFE6")
    b.far.append(_rect(-160, G - 30, W + 320, 18, "#E0D5C0"))
    # 窓とカーテン
    wx, wy, ww, wh = W * .5 - (240 if not b.short else 200), 70, 480 if not b.short else 400, G - 190
    b.win(wx, wy, ww, wh, layer=b.far, pane=(P := b.P)["window"], rx=6, sw=6)
    if not b.night and b.P["weather"] == "sun":
        b.far.append(_circ(wx + ww * .25, wy + wh * .3, 34, GOLD, extra=' opacity=".9"'))
    for cx_, flip in ((wx - 30, 1), (wx + ww + 30, -1)):
        b.far.append(_path(f"M{cx_:.0f} {wy - 16} h{90 * flip} q{-30 * flip} {wh * .5:.0f} {20 * flip} {wh + 40:.0f} h{-110 * flip} Z", "#BFD9FF", 5))
    b.far.append(_rect(wx - 130, wy - 26, ww + 260, 16, "#8D6E63", 6, 4))
    # ペンダントライト
    lx = W * .5
    b.far.append(_path(f"M{lx:.0f} 0 V48", sw=4) + _path(f"M{lx - 50:.0f} 96 l20 -48 h60 l20 48 Z", "#FFF1DC", 5))
    if b.night:
        b.glow.append(_path(f"M{lx - 50:.0f} 96 l20 -48 h60 l20 48 Z", "#FFE082") + _ellipse(lx, 110, 110, 40, "#FFE082", extra=' opacity=".25"'))
    # 棚と観葉植物
    sx = W * .95 if not b.short else W * .93
    b.mid.append(_rect(sx - 70, G - 150, 140, 14, "#8D6E63", 4, 4) + _rect(sx - 44, G - 196, 30, 46, BLUE, 4, 4) + _rect(sx - 6, G - 190, 26, 40, GREEN, 4, 4) + _rect(sx + 26, G - 200, 20, 50, ACCENT, 4, 4))
    b.mid.append(plant(W * .05 if not b.short else W * .07, G, 1.1))
    # フローリング
    b.ground("#EAD2AE")
    for k in range(6):
        y = G + k * 26
        b.near.append(_path(f"M-160 {y} H{W + 160}", sw=3, stroke="#D2B48C"))
        for x in range(-160 + (k % 2) * 160, W + 320, 320):
            b.near.append(_path(f"M{x} {y} v26", sw=3, stroke="#D2B48C"))

def _counter(b: BG, top_col, front_col, line_col):
    W, H, G = b.W, b.H, b.G
    top = G - 100
    b.fore.append(_rect(-160, top + 26, W + 320, H - top + 20, front_col, 0, 0))
    b.fore.append(_rect(-160, top + 26, W + 320, 14, line_col))
    b.fore.append(_rect(-160, top, W + 320, 30, top_col, 6, 5))
    return top

def bg_office(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#F6F3EA", "#EDE8DA")
    b.far.append(_rect(-160, G - 30, W + 320, 18, "#CFC7B3"))
    # 間取り図のポスター
    px, py, pw, ph = W * .5 - 190, 50, 380, 300
    b.far.append(_rect(px, py, pw, ph, "#FFFFFF", 6, 6))
    b.far.append(_rect(px + 30, py + 70, 150, 110, "#FFF1DC", 2, 4) + _rect(px + 180, py + 70, 170, 70, "#E8F5E9", 2, 4) +
                 _rect(px + 180, py + 140, 80, 120, "#FFF8E7", 2, 4) + _rect(px + 260, py + 140, 90, 120, "#E3F2FD", 2, 4) + _rect(px + 30, py + 180, 150, 80, "#FFFFFF", 2, 4))
    b.far.append(_text(px + pw / 2, py + 50, "間取り 3DK", 34, INK))
    # 物件情報の掲示
    for i in range(3 if not b.short else 2):
        bx = (W * .14 + i * 200) if not b.short else (W * .1 + i * 170)
        if b.short and i > 0: bx = W * .8
        b.far.append(_rect(bx - 70, 70, 140, 180, "#FFFFFF", 4, 5) + _rect(bx - 54, 86, 108, 70, "#CFEFFF", 2, 3) +
                     "".join(_rect(bx - 54, 170 + k * 18, 108, 8, "#CFC7B3", 2) for k in range(4)))
    if not b.short:
        b.far.append(_circ(W * .86, 120, 54, "#FFFFFF", 6) + _path(f"M{W * .86:.0f} 120 V86 M{W * .86:.0f} 120 L{W * .86 + 24:.0f} 134", sw=6))
    # のぼり
    nx = W * .9 if not b.short else W * .9
    b.mid.append(_rect(nx - 5, G - 460 if not b.short else G - 420, 10, 460 if not b.short else 420, "#8E8E8E", 3, 3))
    b.mid.append(_rect(nx, G - 450 if not b.short else G - 410, 110, 330, ACCENT, 4, 5))
    b.mid.append(_vtext(nx + 55, G - 390 if not b.short else G - 350, "売物件", 56, "#FFFFFF"))
    b.mid.append(plant(W * .06, G, 1.0))
    b.ground("#DDE1E4")
    b.near.append(_path(" ".join(f"M{x} {G} V{H + 20}" for x in range(-160, W + 320, 240)) + " " + " ".join(f"M-160 {G + k * 60} H{W + 160}" for k in range(1, 4)), sw=2, stroke="#C9CED3"))
    top = _counter(b, "#C89B6D", "#F7F3EA", "#DCCDB0")
    # 電話と名札
    tx = W * .22 if not b.short else W * .18
    b.fore.append(_rect(tx - 60, top - 50, 120, 54, INK, 10) + _rect(tx - 44, top - 36, 50, 26, "#CFEFFF", 4) +
                  _path(f"M{tx - 66:.0f} {top - 60} q66 -40 132 0", sw=16, stroke=INK) + _path(f"M{tx - 66:.0f} {top - 60} q66 -40 132 0", sw=6, stroke="#6E7A94"))
    b.fore.append(_rect(W * .5 - 90, top - 44, 180, 46, "#FFFFFF", 6, 5) + _text(W * .5, top - 10, "受付", 32, INK))

def bg_desk(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#F1E9DA", "#E4D9C4")
    b.far.append(_rect(-160, G - 30, W + 320, 18, "#C8B99A"))
    # 窓（夜は外が紺）
    wx, wy, ww, wh = W * .5 - 180, 50, 360, 260
    pane = "#1B2755" if b.night else ("#FFD9A8" if b.P["time"] == "evening" else "#CFEFFF")
    b.far.append(_rect(wx, wy, ww, wh, pane, 6, 6))
    if b.night:
        b.far.append(moon(wx + ww * .72, wy + wh * .32, 30) + stars(b.uid + "w", 0, 0, 0))
        b.far.append("".join(_circ(wx + 40 + i * 53, wy + 40 + (i * 37) % 150, 3, "#FFFFFF") for i in range(6)))
    elif b.P["weather"] == "sun":
        b.far.append(_circ(wx + ww * .72, wy + wh * .3, 30, GOLD))
    b.far.append(_path(f"M{wx + ww / 2:.0f} {wy} v{wh} M{wx} {wy + wh / 2:.0f} h{ww}", sw=5))
    # 本棚
    sx = W * .84 if not b.short else W * .86
    b.far.append(_rect(sx - 110, 80, 220, 16, "#8D6E63", 4, 4) + _rect(sx - 110, 230, 220, 16, "#8D6E63", 4, 4))
    cols = (BLUE, GREEN, ACCENT, GOLD, RED, BLUE)
    b.far.append("".join(_rect(sx - 96 + i * 34, 96 - (i % 3) * 8 - 110 + 110, 28, 134 - (i % 3) * 8 - 0, cols[i], 3, 4) for i in range(6)))
    b.far.append("".join(_rect(sx - 96 + i * 34, 246 - 120 + (i % 2) * 10 + 0, 28, 120 - (i % 2) * 10, cols[(i + 2) % 6], 3, 4) for i in range(6)))
    b.ground("#D9CBB0")
    top = _counter(b, "#D7B98A", "#C9A97A", "#B48E62")
    # 机の上: スタンド（左）・ノート・電卓・コーヒー（右）
    lx = W * .06 if not b.short else W * .11
    b.fore.append(_rect(lx - 50, top - 10, 100, 12, "#555", 4, 4) + _rect(lx - 7, top - 150, 14, 142, "#555", 4, 4) +
                  _path(f"M{lx - 70:.0f} {top - 150} l40 -70 h110 l40 70 Z", "#2F80ED" if not b.night else "#FFE082", 5))
    if b.night:
        b.glow.append(_path(f"M{lx - 70:.0f} {top - 150} l100 110 h0 Z", "#FFE082", extra=' opacity=".0"') +
                      _path(f"M{lx - 80:.0f} {top - 150} L{lx + 140:.0f} {top - 150} L{lx + 240:.0f} {top + 10} L{lx - 180:.0f} {top + 10} Z", "#FFE082", extra=' opacity=".22"'))
    nx = W * .34 if not b.short else W * .36
    b.fore.append(f'<g transform="rotate(-6 {nx:.0f} {top - 20})">' + _rect(nx - 90, top - 70, 180, 64, "#FFFFFF", 6, 5) + _path(f"M{nx:.0f} {top - 70} v64", sw=4, stroke="#C8C8C8") +
                  "".join(_path(f"M{nx - 72:.0f} {top - 54 + k * 14} h56 M{nx + 16:.0f} {top - 54 + k * 14} h56", sw=3, stroke="#BBB") for k in range(4)) + '</g>')
    cx = W * .64 if not b.short else W * .68
    b.fore.append(_rect(cx - 60, top - 90, 120, 84, "#3B4A66", 8, 5) + _rect(cx - 46, top - 78, 92, 22, "#CFEFFF", 3) +
                  "".join(_rect(cx - 46 + (k % 3) * 32, top - 48 + (k // 3) * 20, 26, 14, "#DDE3EE", 3) for k in range(6)))
    mx = W * .94 if not b.short else W * .9
    b.fore.append(_path(f"M{mx - 34:.0f} {top - 60} h68 l-8 56 h-52 Z", "#FFFFFF", 5) + _path(f"M{mx + 34:.0f} {top - 50} q30 0 24 30 q-4 14 -30 12", sw=5) +
                  _path(f"M{mx - 12:.0f} {top - 76} q-8 -16 0 -30 M{mx + 10:.0f} {top - 78} q-8 -16 0 -30", sw=4, stroke="#B5B5B5"))

def bg_bank(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#EEF3F8", "#E1E8F0")
    b.far.append(_rect(-160, G - 30, W + 320, 18, "#B7C2CF"))
    # 看板・番号表示・時計・ポスター
    b.far.append(_rect(W * .5 - 260, 40, 520, 96, BLUE, 12, 6) + _text(W * .5, 108, "ご融資相談", 58, "#FFFFFF"))
    b.far.append(_rect(W * .5 - 90, 160, 180, 90, INK, 8) + _text(W * .5, 228, "12", 64, "#FF4D4D", extra=' font-family="monospace"'))
    if not b.short:
        b.far.append(_circ(W * .88, 110, 54, "#FFFFFF", 6) + _path(f"M{W * .88:.0f} 110 V76 M{W * .88:.0f} 110 L{W * .88 + 26:.0f} 120", sw=6))
        b.far.append(_rect(W * .12 - 110, 60, 220, 280, "#FFFFFF", 6, 5) + _rect(W * .12 - 90, 80, 180, 120, "#CFEFFF", 4, 3) +
                     "".join(_rect(W * .12 - 90, 220 + k * 24, 180, 10, "#B7C2CF", 3) for k in range(4)))
    # 仕切り（ガラス）
    for fx in (.33, .67):
        b.mid.append(_rect(W * fx - 6, G - 420 if not b.short else G - 400, 12, 420 if not b.short else 400, "#9FB3C8", 4, 3))
    b.mid.append(_rect(-160, G - 420 if not b.short else G - 400, W + 320, 14, "#9FB3C8", 3, 3))
    b.mid.append(plant(W * .06, G, 1.0))
    b.ground("#E3E8EE")
    b.near.append(_path(" ".join(f"M{x} {G} V{H + 20}" for x in range(-160, W + 320, 240)) + " " + " ".join(f"M-160 {G + k * 60} H{W + 160}" for k in range(1, 4)), sw=2, stroke="#CBD3DC"))
    top = _counter(b, "#6E8FB3", "#FFFFFF", "#BFD1E3")
    b.fore.append(_rect(W * .5 - 110, top - 50, 220, 52, "#FFFFFF", 8, 5) + _text(W * .5, top - 12, "融資窓口", 34, BLUE))
    b.fore.append(_rect(W * .78 - 80, top - 20, 160, 22, "#8E8E8E", 6, 4))   # トレー

def bg_bankbook(b: BG, step: int = 1, prev_step: int = 0, anim: bool = False):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#F3EBD9", "#E6DCC5")
    b.near.append(_rect(-160, G + 20, W + 320, H - G, "#D7B98A"))
    bw = 1000 if not b.short else 980; bh = H - 50
    bx, by = W / 2 - bw / 2, 24
    b.mid.append(_rect(bx + 10, by + 14, bw, bh, "#C9BFA6", 16))   # 影
    b.mid.append(_rect(bx, by, bw, bh, "#FFFFFF", 16, 6))
    b.mid.append(_path(f"M{bx + bw / 2:.0f} {by + 8} V{by + bh - 8}", sw=4, stroke="#C9C2B0"))
    b.mid.append(_rect(bx, by, bw, 70, "#E8F5E9", 16) + _rect(bx, by + 50, bw, 20, "#E8F5E9") + _path(f"M{bx} {by + 70} H{bx + bw}", sw=5))
    cols = (("日付", .12), ("おとりひき", .34), ("お預り金額", .62), ("残高", .88))
    for t, fx in cols:
        b.mid.append(_text(bx + bw * fx, by + 50, t, 32, INK if not b.short else INK))
    rows = min(max(step, 1), 7)
    rh = (bh - 110) / 7
    for i in range(7):
        y = by + 70 + rh * (i + 1)
        b.mid.append(_path(f"M{bx + 20} {y:.0f} H{bx + bw - 20}", sw=2, stroke="#D9D4C7"))
    for i in range(rows):
        y = by + 70 + rh * (i + .72)
        new = anim and prev_step < i + 1
        g = (_text(bx + bw * .12, y, f"{i + 1}月", 40, INK) + _text(bx + bw * .34, y, "ヤチン", 40, INK) +
             _rect(bx + bw * .54, y - 30, bw * .16, 42, "#E8F5E9", 8) + _text(bx + bw * .62, y, "入金", 40, GREEN) +
             _rect(bx + bw * .80, y - 14, bw * .16, 14, "#D9D4C7", 6))
        b.mid.append(f'<g class="row{" enter" if new else ""}" style="--i:{max(0, i - prev_step)}">{g}</g>')

def bg_site(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect("#E6DCC0", "#D9CDAE")
    # 壁: 右半分は塗り終わり（白）
    sx = W * .5
    b.far.append(_rect(sx, 0, W + 200, G - 20, "#FBFBF8"))
    b.far.append(_path(f"M{sx:.0f} 0 q30 60 -10 120 q-30 70 20 130 q30 60 0 120 q-20 60 10 {G - 390}", "#FBFBF8", 0))
    b.far.append(_path(f"M{sx:.0f} 0 q30 60 -10 120 q-30 70 20 130 q30 60 0 120 q-20 60 10 {G - 390}", sw=4, stroke="#D9CDAE"))
    b.far.append(_rect(-160, G - 36, W + 320, 20, "#B9A982"))
    b.far.append(_rect(-160, G - 36, W + 320, 20, BLUE, 0, 0, extra=' opacity=".0"'))
    # マスキング（青テープ）
    b.far.append(_rect(-160, G - 44, W + 320, 10, "#4FA3E0"))
    # 脚立（左）
    lx = W * .06 if not b.short else W * .12
    b.mid.append(_path(f"M{lx - 60:.0f} {G} L{lx - 24:.0f} {G - 300} H{lx + 24:.0f} L{lx + 60:.0f} {G} M{lx - 50:.0f} {G - 70} h100 M{lx - 42:.0f} {G - 140} h84 M{lx - 34:.0f} {G - 210} h68", sw=10, stroke="#A7AEB7"))
    b.mid.append(_path(f"M{lx - 60:.0f} {G} L{lx - 24:.0f} {G - 300} H{lx + 24:.0f} L{lx + 60:.0f} {G} M{lx - 50:.0f} {G - 70} h100 M{lx - 42:.0f} {G - 140} h84 M{lx - 34:.0f} {G - 210} h68", sw=4))
    # ペンキ缶・ローラー・工具箱（右）
    px = W * .91 if not b.short else W * .86
    for dx, col, label in ((0, "#FFFFFF", ACCENT), (110, "#FFFFFF", GREEN)):
        b.mid.append(_rect(px + dx - 44, G - 96, 88, 96, col, 6, 5) + _rect(px + dx - 44, G - 70, 88, 34, label) + _path(f"M{px + dx - 48:.0f} {G - 92} q48 -40 96 0", sw=5))
    b.mid.append(_path(f"M{px - 120:.0f} {G - 30} l-60 -150", sw=8, stroke="#8E8E8E") + _rect(px - 214, G - 214, 70, 36, ACCENT, 10, 5))   # ローラー
    tx = W * .62 if not b.short else W * .56
    b.mid.append(_rect(tx, G - 70, 150, 70, RED, 8, 5) + _rect(tx + 50, G - 90, 50, 24, RED, 6, 5) + _path(f"M{tx:.0f} {G - 40} h150", sw=4))   # 工具箱
    b.mid.append(_path(f"M{W * .36:.0f} {G - 10} l80 -40", sw=10, stroke="#8D6E63") + _rect(W * .36 + 70, G - 70, 44, 36, "#777", 6, 4))   # かなづち
    b.mid.append(_rect(W * .46, G - 46, 120, 40, "#555", 10, 5) + _rect(W * .46 + 120, G - 36, 40, 10, "#999", 3, 3) + _rect(W * .46 + 30, G - 10, 40, 12, "#555", 3))   # ドリル
    # 床: 合板＋養生シート
    b.ground("#D9C9A8")
    b.near.append(_path(" ".join(f"M{x} {G} V{H + 20}" for x in range(-160, W + 320, 220)), sw=3, stroke="#C5B48E"))
    b.near.append(_path(f"M-160 {G + 30} L{W * .62:.0f} {G + 50} L{W * .7:.0f} {H + 20} H-160 Z", "#3F7BD9", extra=' opacity=".9"'))
    b.near.append(_path(f"M-160 {G + 30} L{W * .62:.0f} {G + 50} L{W * .7:.0f} {H + 20}", sw=4, stroke="#2F5FB0"))

def bg_night(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect(); b.far.append(stars(b.uid, W, G * .6, 80)); b.far.append(moon(W - (300 if not b.short else 180), 110, 62))
    b.clouds()
    # ビルの影と明かり（far）
    rnd = random.Random(b.uid + "b"); x = -160
    while x < W + 160:
        bw = rnd.choice((120, 160, 200, 240)); bh = rnd.uniform(200, G * .75)
        b.far.append(_rect(x, G - 30 - bh, bw, bh + 30, "#232D5A", 4))
        for wy in range(int(G - 30 - bh + 24), int(G - 60), 44):
            for wx in range(int(x + 16), int(x + bw - 30), 40):
                if rnd.random() < .55:
                    b.glow.append(_rect(wx, wy, 22, 26, "#FFE082", 3, extra=f' opacity="{rnd.uniform(.6, 1):.2f}"'))
        x += bw + rnd.choice((10, 30, 60))
    # 街灯・ベンチ・自販機（mid）
    for fx in ((.12, .5, .88) if not b.short else (.15, .85)):
        lx = W * fx
        b.mid.append(_rect(lx - 8, G - 30 - 330, 16, 330, "#4A5578", 4, 3) + _rect(lx - 46, G - 30 - 360, 92, 34, "#4A5578", 8, 3))
        b.glow.append(_rect(lx - 36, G - 30 - 350, 72, 18, "#FFF3B0", 6) + _path(f"M{lx - 36:.0f} {G - 30 - 332} L{lx - 150:.0f} {G - 30} H{lx + 150:.0f} L{lx + 36:.0f} {G - 30 - 332} Z", "#FFE082", extra=' opacity=".16"'))
    vx = W * .62 if not b.short else W * .5
    b.mid.append(_rect(vx - 70, G - 30 - 230, 140, 230, "#3A4A80", 8, 4) + _rect(vx - 54, G - 30 - 210, 108, 110, "#1B2755", 4, 3))
    b.glow.append(_rect(vx - 54, G - 30 - 210, 108, 110, "#9FD8FF", 4, extra=' opacity=".85"') + "".join(_circ(vx - 36 + i * 24, G - 30 - 160, 9, c) for i, c in enumerate((RED, ACCENT, GREEN, BLUE))))
    b.mid.append(_rect(vx - 120 - 100, G - 90, 150, 14, "#8D6E63", 4, 3) + _rect(vx - 120 - 90, G - 76, 10, 46, "#8D6E63") + _rect(vx - 120 - 40, G - 76, 10, 46, "#8D6E63"))   # ベンチ
    b.mid.append(_rect(-160, G - 48, W + 320, 20, "#3C4870"))   # 歩道の縁
    b.ground("#2F3A5C", G - 30)
    b.near.append(_path(" ".join(f"M{x} {G + 56} h70" for x in range(-160, W + 200, 150)), sw=8, stroke="#8E97B3", extra=' opacity=".8"'))
    for fx in ((.12, .5, .88) if not b.short else (.15, .85)):
        b.near.append(_ellipse(W * fx, G + 50, 90, 24, "#FFF3B0", extra=' opacity=".18"'))
    b.puddles()

def bg_sky(b: BG):
    W, H, G = b.W, b.H, b.G
    b.sky_rect(); b.celestial(); b.clouds(force=True)
    rnd = random.Random(b.uid + "s"); P = b.P
    for i in range(3 if not b.short else 2):
        b.mid.append(cloud(W * (.2 + i * .3) + rnd.uniform(-80, 80), G - 260 + rnd.uniform(-60, 60), rnd.uniform(.9, 1.3), P["cloud"], P["cloud_sh"]))
    # 足場の雲（地面）
    x = -200
    while x < W + 200:
        b.near.append(cloud(x, G + 30, 1.6, P["cloud"], P["cloud_sh"]))
        x += 260
    b.near.append(_rect(-160, G + 30, W + 320, H - G, P["cloud"]))

def bg_blank(b: BG):
    b.sky_rect(PAPER, "#F6ECD6")

def build_bg(name: str, kind: str, P: dict, uid: str, step: int, prev_step: int, anim: bool) -> tuple[str, str]:
    b = BG(name, kind, P, uid)
    if name == "bankbook":
        bg_bankbook(b, step, prev_step, anim)
    else:
        globals().get(f"bg_{name}", bg_blank)(b)
    if name in EXTERIOR:
        b.rainfall()
    return b.render()

# ---------------------------------------------------------------- 小道具
def outlined(text: str, extra_cls: str = "") -> str:
    return f'<span class="ot {extra_cls}" data-t="{attr(text)}">{esc(text)}</span>'

def _mark_svg(kind: str) -> str:
    if kind == "sweat":
        inner = (characters._drop(44, 40, 1.9) + characters._drop(82, 78, 1.4))
    elif kind == "exclaim":
        inner = _text(60, 108, "！", 118, "#FF3B3B", outline="#fff")
    elif kind == "question":
        inner = _text(60, 108, "？", 118, BLUE, outline="#fff")
    elif kind == "heart":
        inner = _path("M60 104 C 20 76 6 52 18 32 C 30 12 54 16 60 36 C 66 16 90 12 102 32 C 114 52 100 76 60 104 Z", "#FF5C8A", 6, extra=' stroke="#fff" paint-order="stroke"') + \
                _path("M60 104 C 20 76 6 52 18 32 C 30 12 54 16 60 36 C 66 16 90 12 102 32 C 114 52 100 76 60 104 Z", "#FF5C8A", 5)
    elif kind == "zzz":
        inner = (_text(30, 104, "z", 54, "#7E57C2", outline="#fff") + _text(62, 72, "z", 66, "#7E57C2", outline="#fff") +
                 _text(98, 40, "z", 78, "#7E57C2", outline="#fff"))
    else:  # star
        def star(cx, cy, r):
            pts = []
            for i in range(10):
                a = -math.pi / 2 + i * math.pi / 5; rr = r if i % 2 == 0 else r * .45
                pts.append(f"{cx + math.cos(a) * rr:.0f} {cy + math.sin(a) * rr:.0f}")
            return _path("M" + " L".join(pts) + " Z", GOLD, 5)
        inner = star(56, 56, 44) + star(100, 24, 18) + star(104, 96, 14)
    return f'<svg class="hm-svg" viewBox="0 0 120 120">{inner}</svg>'

def _arrow_svg(d: str) -> str:
    pts = [(0, 45), (150, 45), (150, 5), (255, 75), (150, 145), (150, 105), (0, 105)]
    if d == "left":
        pts = [(255 - x, y) for x, y in pts]
        vb = (260, 150)
    elif d in ("up", "down"):
        pts = [(y, x) if d == "down" else (y, 255 - x) for x, y in pts]
        vb = (150, 260)
    else:
        vb = (260, 150)
    path = "M" + " L".join(f"{x} {y}" for x, y in pts) + " Z"
    return (f'<svg viewBox="-6 -6 {vb[0] + 12} {vb[1] + 12}" style="width:{vb[0] + 12}px;height:{vb[1] + 12}px">'
            f'{_path(path, ACCENT, 8)}</svg>')

def _coins_svg(count: int) -> str:
    count = max(1, min(int(count), 40)); per = 8
    cols = math.ceil(count / per); cw = 110; ch = 14
    W = cols * cw + 20; H = per * ch + 50
    out = []
    for i in range(count):
        c, r = divmod(i, per)
        cx = 60 + c * cw; cy = H - 20 - r * ch
        out.append(_ellipse(cx, cy + 4, 48, 16, "#B88600") + _ellipse(cx, cy, 48, 16, "#FFD84D", 4, "#B88600"))
        if r == per - 1 or i == count - 1:
            out.append(_ellipse(cx, cy, 30, 9, "#FFF3B0") + _text(cx, cy + 6, "¥", 18, "#B88600"))
    return f'<svg viewBox="0 0 {W} {H}" style="width:{W}px;height:{H}px">{"".join(out)}</svg>'

def _money_svg(seed: str) -> str:
    rnd = random.Random(seed); out = []
    for i, (x, y, r) in enumerate(((60, 150, -18), (200, 70, 10), (330, 160, -6), (150, 230, 22), (280, 40, -30))):
        out.append(f'<g transform="translate({x} {y}) rotate({r})">' + _rect(-80, -44, 160, 88, "#D6EBC9", 10, 5) +
                   _rect(-66, -32, 132, 64, "none", 6, 3, "#8BB07F") + _circ(0, 0, 22, "#BFE0AE", 3, "#8BB07F") + _text(0, 9, "¥", 26, "#5E8A52") + '</g>')
    return f'<svg viewBox="-40 -40 500 340" style="width:500px;height:340px">{"".join(out)}</svg>'

def _photo_html(p: dict, script_dir: Path | None, kind: str) -> str:
    src = p.get("image")
    img = ""
    if src:
        sp = Path(str(src))
        if not sp.is_absolute() and script_dir is not None:
            sp = Path(script_dir) / sp
        if sp.exists():
            img = f'<img src="{sp.resolve().as_uri()}">'
        else:
            img = f'<div class="ph-empty">写真が見つかりません<br>{esc(sp.name)}</div>'
    else:
        img = '<div class="ph-empty">ここに写真</div>'
    cap = f'<div class="cap">{esc(p["caption"])}</div>' if p.get("caption") else ""
    return f'<div class="photo">{img}{cap}</div>'

def _counter_html(p: dict, anim_new: bool) -> str:
    raw = str(p.get("value", 0)).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        val = 0.0
    dec = len(raw.split(".")[1]) if "." in raw else 0
    v = (f'<span data-count-from="0" data-count-to="{val}" data-count-dur="1100" data-count-dec="{dec}">0</span>'
         if anim_new else f'{val:,.{dec}f}')
    lb = f'<div class="lb">{esc(p["label"])}</div>' if p.get("label") else ""
    return f'<div class="cnt">{lb}<div class="v">{v}<small>{esc(p.get("unit", ""))}</small></div></div>'

def _est_width(k: str, text: str, kind: str) -> float:
    """小道具のおおよその幅（px）。画面端で切れないように横位置を寄せる判断に使う"""
    n = max(1, len(text))
    if k == "price":
        fs = 124 if n <= 4 else (112 if n <= 7 else 96)
        if kind == "short" and n > 6: fs = 84
        return fs * n * 0.98 + 120
    if k == "sign":
        return min(560, (74 if n <= 6 else 60) * n + 90)
    if k == "arrow":
        return max(220, 60 * n + 40)
    if k == "money":
        return max(300, 72 * n)
    return {"calendar": 340, "stamp": 320, "coins": 260, "cross": 360, "check": 360, "photo": 600, "counter": 440}.get(k, 300)

def _clamp_x(x_pct: float, width_px: float, W: int, margin: int = 24) -> float:
    half = width_px / 2 + margin
    lo, hi = half / W * 100, 100 - half / W * 100
    if lo >= hi:
        return 50.0
    return min(max(x_pct, lo), hi)

def prop_html(p: dict, kind: str, new: bool, idx: int, script_dir: Path | None, uid: str, stack: int = 0) -> str:
    """キャラに付かない小道具 1 つの HTML（headline / bubble / 頭上の印は別）"""
    k = str(p.get("kind", ""))
    W, H, G = geometry(kind)
    text = str(p.get("text", ""))
    x = _clamp_x(_pct(p.get("at", p.get("x", "center")), kind, PROP_X), _est_width(k, text, kind), W)
    cls = ["prop", f"p-{k}"]
    if new:
        cls.append("enter pop")
    style = [f"--x:{x:.1f}%", f"--i:{idx}"]
    if stack:
        style.append(f"--stack:{stack}")
    if k == "price":
        cls.append("hang")
        n = len(text)
        fs = 124 if n <= 4 else (112 if n <= 7 else 96)
        if kind == "short" and n > 6:
            fs = 84
        inner = f'<div class="price"><div class="string"></div><div class="tag" style="font-size:{fs}px">{esc(text)}</div></div>'
    elif k == "sign":
        cls.append("ground")
        fs = 74 if len(text) <= 6 else 60
        inner = f'<div class="sign"><div class="board" style="font-size:{fs}px">{esc(text)}</div><div class="post"></div></div>'
    elif k == "arrow":
        d = str(p.get("dir", "right"))
        d = d if d in ("up", "down", "left", "right") else "right"
        lbl = f'<div class="lbl">{outlined(text)}</div>' if text else ""
        inner = f'<div class="arrow">{lbl}{_arrow_svg(d)}</div>'
    elif k == "calendar":
        fs = 92 if len(text) <= 3 else (72 if len(text) <= 5 else 56)
        inner = f'<div class="cal"><div class="top"></div><div class="d" style="font-size:{fs}px">{esc(text)}</div></div>'
    elif k == "stamp":
        n = len(text); fs = 104 if n <= 2 else (84 if n <= 3 else 62)
        inner = f'<div class="stamp" style="font-size:{fs}px"><span>{esc(text)}</span></div>'
    elif k == "coins":
        cls.append("ground")
        inner = f'<div class="coins-prop">{_coins_svg(p.get("count", 5))}</div>'
    elif k == "money":
        lbl = f'<div class="lbl">{outlined(text)}</div>' if text else ""
        inner = f'<div class="money">{_money_svg(uid)}{lbl}</div>'
    elif k == "cross":
        inner = ('<svg class="big-mark" viewBox="0 0 360 360">'
                 f'{_path("M50 50 L310 310 M310 50 L50 310", sw=74, stroke="#fff")}{_path("M50 50 L310 310 M310 50 L50 310", sw=46, stroke=RED)}</svg>')
    elif k == "check":
        inner = ('<svg class="big-mark" viewBox="0 0 360 360">'
                 f'{_path("M50 196 L146 290 L316 76", sw=74, stroke="#fff")}{_path("M50 196 L146 290 L316 76", sw=46, stroke=GREEN)}</svg>')
    elif k == "photo":
        inner = _photo_html(p, script_dir, kind)
    elif k == "counter":
        inner = _counter_html(p, new)
    else:
        return ""
    return f'<div class="{" ".join(cls)}" style="{";".join(style)}">{inner}</div>'

# ---------------------------------------------------------------- キャラ
def char_html(c: dict, idx: int, n_chars: int, faces: dict, talking, variant: str, kind: str, start: bool,
              attached: list[str], others: list[float], bg: str) -> str:
    who = str(c.get("who", ""))
    ch = characters.CHARACTERS.get(who)
    if ch is None:
        return ""
    W, H, G = geometry(kind)
    x = float(c["x"]) if c.get("x") is not None else _pct(_final_at(c.get("at", "center")), kind, AT_X)   # offleft/offright は left/right で止まる
    act = str(c.get("act", "stand"))
    if act not in ACTS:
        act = "stand"
    expr = faces.get(who) or c.get("face") or "normal"
    if expr not in characters.EXPRS:
        expr = "normal"
    mouth = (variant == "open") and (talking == who)
    blink = variant == "blink"
    facing = "left" if x > 50 else "right"
    if abs(x - 50) < 1 and others:        # 中央なら、相手のいない側ではなく相手の方を向く
        facing = "left" if others[0] < 50 else "right"
    size = CHAR_SIZE[kind] if n_chars <= 1 else CHAR_SIZE_2[kind]
    body = ch["svg"](expr, mouth, blink, act=act, facing=facing)
    svg = (f'<svg class="chsvg" viewBox="0 0 300 300"><defs><filter id="chsh{idx}" x="-20%" y="-20%" width="140%" height="140%">'
           f'<feDropShadow dx="0" dy="6" stdDeviation="0" flood-color="{INK}" flood-opacity=".18"/></filter></defs>'
           f'<g filter="url(#chsh{idx})">{body}</g></svg>')
    cls = ["ch", f"act-{act}", f"who-{idx}"]
    style = [f"left:{x:.2f}%", f"--cs:{size}px"]
    lift = COUNTER_BG.get(bg, 0)
    if act == "sit":
        lift -= 40 if who == "ぽん太" else 20
        lift = max(lift, 0) if bg not in COUNTER_BG else lift
    if lift:
        style.append(f"--lift:{lift}px")
    if start and act == "walk":
        from_left = x <= 50 and str(c.get("at")) != "offright"
        if str(c.get("at")) == "offleft":
            from_left = True
        final_px = x * W / 100
        start_px = (-size * .6) if from_left else (W + size * .6)
        cls.append("walkin"); style.append(f"--from:{start_px - final_px:.0f}px")
    if start and act in ("bow", "shock", "cheer"):
        cls.append("posein")
        lean = {"bow": 12, "shock": -8}.get(act, 0) * (-1 if facing == "left" else 1)
        style.append(f"--lean:{lean}deg")
    side = "c" if abs(x - 50) < 1 else ("l" if x < 50 else "r")
    att = "".join(a.replace("{SIDE}", side) for a in attached)
    return f'<div class="{" ".join(cls)}" style="{";".join(style)}"><div class="bob">{svg}</div>{att}</div>'

# ---------------------------------------------------------------- 場面
def render_scene(data: dict, step: int, prev_step: int, anim: bool, kind: str,
                 faces: dict[str, str], talking: str | None, variant: str, script_dir: Path | None) -> str:
    kind = "short" if kind == "short" else "long"
    W, H, G = geometry(kind)
    bg = str(data.get("bg", "blank"))
    if bg not in BGS:
        bg = "blank"
    time = str(data.get("time") or "day")
    time = time if time in TIMES else "day"
    if bg == "night":          # 夜の街は time に関わらず夜
        time = "night"
    weather = str(data.get("weather", "sun")); weather = weather if weather in WEATHERS else "sun"
    cam = str(data.get("camera", "still")); cam = cam if cam in CAMERAS else "still"
    start = bool(anim) and int(prev_step) <= 0
    uid = hashlib.md5(str(data.get("id", bg)).encode("utf-8")).hexdigest()[:6]
    faces = faces or {}
    P = palette(time, weather)
    back, front = build_bg(bg, kind, P, uid, step, prev_step, anim)

    # 小道具（step で出す）。キャラに付くもの（bubble / 頭上の印）は who ごとに集める
    attached: dict[str, list[str]] = {}
    free: list[str] = []
    headline = ""
    n_new = 0
    has_hl = any(isinstance(p, dict) and str(p.get("kind", "")) == "headline" for p in (data.get("props") or []))
    at_count: dict[str, int] = {}
    for p in data.get("props") or []:
        if not isinstance(p, dict):
            continue
        ps = int(p.get("step", 1) or 1)
        if ps > step:
            continue
        new = bool(anim) and int(prev_step) < ps
        ent = " enter pop" if new else ""
        k = str(p.get("kind", ""))
        if new:
            n_new += 1
        idx = n_new - 1 if new else 0
        if k == "headline":
            t = str(p.get("text", ""))
            fs = 88 if (len(t) <= 16 or kind == "short") else 76
            headline = f'<div class="hl{ent}" style="--i:{idx};font-size:{fs}px">{outlined(t)}</div>'
        elif k == "bubble":
            t = str(p.get("text", "")); who = str(p.get("who", ""))
            wrap = " wrap" if len(t) > 10 else ""
            attached.setdefault(who, []).append(f'<div class="bub {{SIDE}}{wrap}{ent}" style="--i:{idx}">{esc(t)}</div>')
        elif k in HEAD_MARKS:
            who = str(p.get("who", ""))
            attached.setdefault(who, []).append(f'<div class="hm {{SIDE}} hm-{k}{ent}" style="--i:{idx}">{_mark_svg(k)}</div>')
        else:
            akey = str(p.get("at", p.get("x", "center")))
            stack = at_count.get(akey, 0)
            if k not in ("sign", "coins"):
                at_count[akey] = stack + 1
            free.append(prop_html(p, kind, new, idx, script_dir, uid, stack))

    chars = [c for c in (data.get("chars") or []) if isinstance(c, dict)]
    xs = [float(c["x"]) if c.get("x") is not None else _pct(_final_at(c.get("at", "center")), kind, AT_X) for c in chars]
    ch_html = []
    for i, c in enumerate(chars[:2]):
        others = [xx for j, xx in enumerate(xs[:2]) if j != i]
        ch_html.append(char_html(c, i, len(chars[:2]), faces, talking, variant, kind, start, attached.get(str(c.get("who", "")), []), others, bg))

    return (f'<div class="scene bg-{bg}{" has-hl" if has_hl else ""}" data-bg="{bg}" data-time="{time}" data-weather="{weather}" data-cam="{cam}" data-anim="{1 if start else 0}">'
            f'<div class="cam">{back}<div class="chars">{"".join(ch_html)}</div>{front}<div class="props">{"".join(free)}</div></div>'
            f'{headline}</div>')

# ---------------------------------------------------------------- CSS（正本は slide.html）
def _read_scene_css() -> str:
    try:
        s = TEMPLATE.read_text(encoding="utf-8")
        a = s.index("/* ---- scene ---- */"); b = s.index("/* ---- /scene ---- */")
        return s[a:b + len("/* ---- /scene ---- */")]
    except (OSError, ValueError):
        return ""

SCENE_CSS: str = _read_scene_css()

# ---------------------------------------------------------------- 見本（preview）
def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    if Path("/usr/bin/chromium").exists():
        return "/usr/bin/chromium"
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    for c in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")):
        return str(c)
    if platform.system() == "Windows":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")]:
            for c in (Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe"):
                if c.exists():
                    return str(c)
    sys.exit("Chrome が見つかりません。CHROME_PATH を指定してください。")

SIZES = {"long": (1920, 1080), "short": (1080, 1920)}

def page_html(kind: str, body: str, font: str | None = None, question: str = "物語シーンの見本") -> str:
    w, h = SIZES[kind]
    tpl = TEMPLATE.read_text(encoding="utf-8")
    font = font or ("BIZ UDPGothic" if platform.system() == "Windows" else "IPAPGothic")
    html = (tpl.replace("{{W}}", str(w)).replace("{{H}}", str(h)).replace("{{KIND}}", kind).replace("{{FONT}}", font)
            .replace("{{QUESTION}}", esc(question)).replace("{{CHAPTER}}", "1/3")
            .replace("{{DISCLAIMER}}", "登場人物・数字・例文は説明のための架空の設定です").replace("{{BODY}}", body))
    # ?t=ms で途中のコマを撮れるようにする（slide.html の __seek を使う）
    return html.replace("</body>", '<script>(function(){var m=/[?&]t=(\\d+)/.exec(location.search);if(m)window.__seek(+m[1]);})();</script></body>')

def shoot(chrome: str, html_path: Path, png: Path, size: tuple[int, int], t: int | None = None) -> Path:
    url = html_path.resolve().as_uri() + ("?static" if t is None else f"?t={t}")
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={size[0]},{size[1] + 240}", "--virtual-time-budget=1500", f"--screenshot={png}", url],
                   capture_output=True)
    from PIL import Image
    im = Image.open(png)
    if im.size != size:
        im.convert("RGB").crop((0, 0, size[0], size[1])).save(png)
    return png

def _sample_scene(bg, time="day", weather="sun", camera="still", chars=None, props=None, sid=None):
    return {"id": sid or f"pv_{bg}_{time}_{weather}_{camera}", "bg": bg, "time": time, "weather": weather, "camera": camera,
            "chars": chars if chars is not None else [{"who": "ぽん太", "at": "left", "act": "stand", "face": "normal"},
                                                      {"who": "コツさん", "at": "right", "act": "stand", "face": "happy"}],
            "props": props or []}

def preview(out_dir: Path):
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw, ImageFont
    out = Path(out_dir); (out / "png").mkdir(parents=True, exist_ok=True); (out / "html").mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    jobs: list[tuple[str, str, str, int | None]] = []   # (name, kind, html, t)

    def add(name, kind, data, step=1, prev=0, anim=True, faces=None, talking=None, variant="closed", t=None):
        body = render_scene(data, step, prev, anim, kind, faces or {}, talking, variant, None)
        jobs.append((name, kind, page_html(kind, body), t))

    # 1) 背景 13 × time 3（長尺、2 人立ち）
    for bg in BGS:
        for tm in TIMES:
            add(f"bg_{bg}_{tm}", "long", _sample_scene(bg, tm, props=[{"kind": "headline", "text": f"{bg} / {tm}"}]))
    # 2) 天気 13 × 2
    for bg in BGS:
        for wt in ("cloud", "rain"):
            add(f"wt_{bg}_{wt}", "long", _sample_scene(bg, "day", wt, props=[{"kind": "headline", "text": f"{bg} / {wt}"}]))
    # 3) ポーズ 8 × 2 キャラ（＋向き左）: 1 ページ
    rows = []
    for name, c in characters.CHARACTERS.items():
        for facing in ("right", "left"):
            cells = "".join(f'<div class="cell">{characters.svg_document(c["svg"]("normal", act=a, facing=facing), 220)}<div>{a}</div></div>' for a in ACTS)
            rows.append(f'<div class="prow"><div class="lbl">{name}<br>{facing}</div>{cells}</div>')
    pose_html = ('<!doctype html><html><head><meta charset="utf-8"><style>body{background:#FFF8E7;margin:0;padding:16px;font-family:IPAPGothic,sans-serif;font-weight:700}'
                 '.prow{display:flex;align-items:flex-end;gap:6px;margin-bottom:8px}.lbl{width:110px;font-size:22px}.cell{text-align:center;font-size:20px}svg{overflow:visible}</style></head><body>'
                 + "".join(rows) + '</body></html>')
    jobs.append(("poses", "poses", pose_html, None))
    # 4) 小道具（長尺 5 枚・ショート 3 枚）
    P1 = [{"kind": "headline", "text": "買値50万円の家"}, {"kind": "price", "text": "50万円", "at": "center"},
          {"kind": "sign", "text": "売地", "x": 36}, {"kind": "coins", "count": 14, "x": 64},
          {"kind": "bubble", "text": "安っ！", "who": "ぽん太"}, {"kind": "exclaim", "who": "コツさん"}]
    add("props_1", "long", _sample_scene("blank", props=P1, sid="props1"))
    P2 = [{"kind": "calendar", "text": "4か月", "x": 36}, {"kind": "stamp", "text": "空室", "at": "center"},
          {"kind": "arrow", "text": "家賃7万円", "dir": "up", "x": 64}, {"kind": "sweat", "who": "ぽん太"}, {"kind": "question", "who": "コツさん"}]
    add("props_2", "long", _sample_scene("blank", props=P2, sid="props2",
                                          chars=[{"who": "ぽん太", "at": "left", "act": "think"}, {"who": "コツさん", "at": "right", "act": "point"}]))
    P3 = [{"kind": "money", "text": "150万円", "x": 37}, {"kind": "cross", "at": "center"}, {"kind": "check", "x": 63},
          {"kind": "heart", "who": "ぽん太"}, {"kind": "zzz", "who": "コツさん"}]
    add("props_3", "long", _sample_scene("blank", props=P3, sid="props3",
                                          chars=[{"who": "ぽん太", "at": "left", "act": "cheer"}, {"who": "コツさん", "at": "right", "act": "shock"}]))
    P4 = [{"kind": "photo", "caption": "直す前の外観", "at": "left"}, {"kind": "counter", "value": 1000, "unit": "万円", "label": "年の家賃", "at": "center"},
          {"kind": "star", "who": "コツさん"}, {"kind": "bubble", "text": "数字は買値、直し、家賃の順に見ます", "who": "コツさん"}]
    add("props_4", "long", _sample_scene("blank", props=P4, sid="props4",
                                          chars=[{"who": "コツさん", "at": "right", "act": "bow"}]))
    P5 = [{"kind": "headline", "text": "融資は断られました"}, {"kind": "cross", "at": "center"}, {"kind": "sweat", "who": "ぽん太"},
          {"kind": "arrow", "text": "次へ", "dir": "right", "at": "right"}]
    add("props_5", "long", _sample_scene("bank", props=P5, sid="props5",
                                          chars=[{"who": "ぽん太", "at": "left", "act": "sit", "face": "doubt"}]))
    add("short_1", "short", _sample_scene("house_old", props=[P1[0], P1[1], {"kind": "sign", "text": "再建築不可", "x": 50, "step": 1}, {"kind": "bubble", "text": "ボロい…", "who": "ぽん太"}], sid="s1"))
    add("short_2", "short", _sample_scene("street", "evening", props=[{"kind": "headline", "text": "物件を探して歩く"}, {"kind": "price", "text": "1,000万円／年", "at": "center"}],
                                            sid="s2", chars=[{"who": "ぽん太", "at": "center", "act": "walk"}]))
    add("short_3", "short", _sample_scene("desk", "night", props=[{"kind": "calendar", "text": "4か月", "at": "right"}, {"kind": "zzz", "who": "ぽん太"},
                                                                 {"kind": "counter", "value": 7, "unit": "万円", "label": "月の家賃", "at": "left"}],
                                            sid="s3", chars=[{"who": "ぽん太", "at": "center", "act": "sit", "face": "calm"}]))
    add("bankbook_s4", "long", _sample_scene("bankbook", chars=[{"who": "コツさん", "at": "right", "act": "point"}],
                                               props=[{"kind": "counter", "value": 7, "unit": "万円", "label": "月の家賃", "at": "left"}], sid="bb4"),
        step=4, prev=2, t=350)
    # 5) カメラ 6 × 4 コマ（walk / 出現アニメ入り）
    for cam in CAMERAS:
        sc = _sample_scene("street", camera=cam, sid=f"cam_{cam}",
                           chars=[{"who": "ぽん太", "at": "left", "act": "walk"}, {"who": "コツさん", "at": "right", "act": "cheer"}],
                           props=[{"kind": "headline", "text": f"camera: {cam}"}, {"kind": "price", "text": "50万円", "at": "center", "step": 1}])
        for t in (0, 300, 700, 1300):
            add(f"cam_{cam}_{t:04d}", "long", sc, t=t)
    # anim=False の静止画と、anim=True の最終コマ（t=1e7）が同じ絵であること
    sc = _sample_scene("street", camera="in", sid="cam_in",
                       chars=[{"who": "ぽん太", "at": "left", "act": "walk"}, {"who": "コツさん", "at": "right", "act": "cheer"}],
                       props=[{"kind": "headline", "text": "camera: in"}, {"kind": "price", "text": "50万円", "at": "center", "step": 1}])
    add("end_anim", "long", sc, t=None); add("end_static", "long", sc, anim=False, t=None)
    # 6) 口パク 3 変種（差分の確認用）
    vs = _sample_scene("office", props=[{"kind": "headline", "text": "口パクの確認"}, {"kind": "bubble", "text": "えっ！？", "who": "ぽん太"}], sid="var",
                       chars=[{"who": "ぽん太", "at": "left", "act": "point"}, {"who": "コツさん", "at": "right", "act": "stand"}])
    for v in ("closed", "open", "blink"):
        add(f"var_{v}", "long", vs, faces={"ぽん太": "surprised"}, talking="ぽん太", variant=v, t=700)

    # 描画
    def work(job):
        name, kind, html, t = job
        hp = out / "html" / f"{name}.html"; hp.write_text(html, encoding="utf-8")
        png = out / "png" / f"{name}.png"
        size = SIZES.get(kind, (1920, 1080)) if kind != "poses" else (1900, 1200)
        shoot(chrome, hp, png, size, t)
        return name
    with ThreadPoolExecutor(max_workers=max(2, min(6, (os.cpu_count() or 2)))) as ex:
        for i, _ in enumerate(ex.map(work, jobs), 1):
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}")
    print(f"  {len(jobs)}/{len(jobs)} 枚")

    # sheet にまとめる
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 26)
    except OSError:
        font = ImageFont.load_default()

    def sheet(name, items, cols, tw):
        ims = []
        for lbl, pn in items:
            im = Image.open(out / "png" / f"{pn}.png").convert("RGB")
            th = round(im.height * tw / im.width); ims.append((lbl, im.resize((tw, th), Image.LANCZOS)))
        th = max(i.height for _, i in ims)
        rows = math.ceil(len(ims) / cols)
        sh = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 40) + 10), (60, 60, 70)); dr = ImageDraw.Draw(sh)
        for i, (lbl, im) in enumerate(ims):
            r, c = divmod(i, cols); x = 10 + c * (tw + 10); y = 10 + r * (th + 40)
            sh.paste(im, (x, y + 30)); dr.text((x, y + 2), lbl, fill=(255, 255, 255), font=font)
        p = out / f"sheet_{name}.png"; sh.save(p); print("  sheet:", p)
        return p

    sheet("bg_1", [(f"{bg}/{tm}", f"bg_{bg}_{tm}") for bg in BGS[:7] for tm in TIMES], 3, 620)
    sheet("bg_2", [(f"{bg}/{tm}", f"bg_{bg}_{tm}") for bg in BGS[7:] for tm in TIMES], 3, 620)
    sheet("weather", [(f"{bg}/{wt}", f"wt_{bg}_{wt}") for bg in BGS for wt in ("cloud", "rain")], 2, 760)
    sheet("poses", [("poses", "poses")], 1, 1900)
    sheet("props", [(f"props_{i}", f"props_{i}") for i in range(1, 6)] + [("bankbook step 2→4 (t=350ms)", "bankbook_s4")], 2, 940)
    sheet("short", [(f"short_{i}", f"short_{i}") for i in range(1, 4)], 3, 600)
    sheet("camera", [(f"{cam} t={t}ms", f"cam_{cam}_{t:04d}") for cam in CAMERAS for t in (0, 300, 700, 1300)], 4, 470)
    sheet("variants", [(v, f"var_{v}") for v in ("closed", "open", "blink")], 3, 620)
    check_variants(out / "png", "var")
    check_static(out / "png")

def check_static(png_dir: Path):
    """anim=False の静止画と anim=True の最終コマ（t=1e7）が同じ絵か。
    camera: in の最終状態は scale(1.1) で、Chrome は animated transform をコンポジタで拡大するため縁の画素に小さなラスタ差が出る。
    位置・内容が同じなら「強い差分（>24）」は面積の 2% 未満に収まる。"""
    from PIL import Image, ImageChops
    a = Image.open(Path(png_dir) / "end_anim.png").convert("RGB"); b = Image.open(Path(png_dir) / "end_static.png").convert("RGB")
    d = ImageChops.difference(a, b).convert("L")
    hist = d.histogram(); total = a.width * a.height
    strong = sum(hist[25:]); mx = max(i for i, n in enumerate(hist) if n) if any(hist) else 0
    ok = strong < total * .02
    print(f"  anim=False の静止画 と anim=True の最終コマ: 強い差分 {strong} px ({strong / total * 100:.2f}%), 最大 {mx} → "
          f"{'OK（ラスタ差のみ）' if ok else 'NG（内容が違う）'}")
    return ok

def check_variants(png_dir: Path, prefix: str):
    """closed / open / blink の差分が顔の位置だけにあることを確かめる"""
    from PIL import Image, ImageChops
    ims = {v: Image.open(Path(png_dir) / f"{prefix}_{v}.png").convert("RGB") for v in ("closed", "open", "blink")}
    W, H, G = geometry("long"); size = CHAR_SIZE_2["long"]
    # ぽん太（left=20%）の顔の中心（viewBox 150,150）。.scene は top 124px から始まる
    fx = AT_X["long"]["left"] * W / 100; top = 124 + G - size
    face = {"ぽん太": (fx, top + size * 150 / 300), "コツさん": (AT_X["long"]["right"] * W / 100, top + size * 232 / 300)}
    ok = True
    for a, b, who in (("closed", "open", "ぽん太"), ("closed", "blink", None)):
        d = ImageChops.difference(ims[a], ims[b]).convert("L").point(lambda v: 255 if v > 24 else 0)
        bbox = d.getbbox()
        if not bbox:
            print(f"  差分なし: {a} vs {b}（口や目が描かれていない？）"); ok = False; continue
        try:
            import numpy as np
            arr = np.asarray(d) > 0; ys, xs = np.nonzero(arr); n = len(xs); cx, cy = float(xs.mean()), float(ys.mean())
        except ImportError:
            n = -1; cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if who:
            ex, ey = face[who]; dist = math.hypot(cx - ex, cy - ey); good = dist < size * .35
            print(f"  {a} vs {b}: 差分 {n} px, bbox={bbox}, 重心=({cx:.0f},{cy:.0f}) {who}の顔=({ex:.0f},{ey:.0f}) 距離 {dist:.0f}px → {'OK' if good else 'NG'}")
            ok &= good
        else:
            # blink は 2 人の目: bbox の高さが顔の範囲（size*0.25）に収まり、それ以外の領域に差分が無い
            inside = all(any(math.hypot(x - face[w][0], y - face[w][1]) < size * .3 for w in face) for x, y in ((bbox[0], bbox[1]), (bbox[2], bbox[3])))
            print(f"  {a} vs {b}: 差分 {n} px, bbox={bbox} → {'OK（2 人の目の範囲）' if inside else 'NG'}")
            ok &= inside
    print("  3 変種の差分チェック:", "OK" if ok else "NG")
    return ok

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "preview":
        preview(Path(sys.argv[2]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "check":
        check_variants(Path(sys.argv[2]), "var"); check_static(Path(sys.argv[2]))
    else:
        print(__doc__)
