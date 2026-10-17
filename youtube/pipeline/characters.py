# -*- coding: utf-8 -*-
"""
characters.py ― チャンネル「小規模な大家」の原作キャラクター（SVG）
  ユイさん : 解説役。不動産の仕入れと販売をしている大家のお姉さん（こげ茶のボブ・メガネ・紺のジャケット・金の鍵）。
  ソウタ   : 聞き役。皮算用が得意な新人会社員（明るい茶髪・紺のスーツ・青いネクタイ）。視聴者の疑問・驚きを言う。
  （旧）コツさん・ぽん太 : 亀とたぬき。v6 までの台本のために残している。
表情: normal / happy / surprised / doubt / calm / fire   口: open/closed   目: blink
ポーズ act: stand / walk / point / think / cheer / sit / shock / bow（docs/12 の語彙）
  facing: "right"（既定）/ "left" ― point の指す向き・bow / shock の傾く向き。顔の位置は変えない。
  walk の手足には class leg-a / leg-b / arm-a / arm-b が付き、scenes.py の CSS がそれを上下させる。
"""
INK = "#1F2A44"
SKIN_K = "#9CCC65"   # コツさんの肌
FUR = "#8D6E63"      # ぽん太の毛
FUR_D = "#4E342E"
SWEAT = "#4FC3F7"
ACTS = ("stand", "walk", "point", "think", "cheer", "sit", "shock", "bow")

# ---------------------------------------------------------------- ポーズの部品
def _ell(cx, cy, rx, ry, rot=0, fill=SKIN_K, cls="", sw=5):
    e = f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{INK}" stroke-width="{sw}"/>'
    if cls:
        e = f'<g class="{cls}">{e}</g>'
    if rot:
        e = f'<g transform="rotate({rot} {cx} {cy})">{e}</g>'
    return e

def _arm(sx, sy, ang, length, fill, ry=11, hand=True, finger=False, cls=""):
    """肩 (sx,sy) から角度 ang（0=右, 90=下, -90=上）へ伸びる腕。先に手（丸）。"""
    inner = f'<ellipse cx="{length/2:.0f}" cy="0" rx="{length/2+4:.0f}" ry="{ry}" fill="{fill}" stroke="{INK}" stroke-width="5"/>'
    if hand:
        inner += f'<circle cx="{length}" cy="0" r="{ry+2}" fill="{fill}" stroke="{INK}" stroke-width="5"/>'
    if finger:
        inner += f'<rect x="{length+2}" y="-6" width="30" height="12" rx="6" fill="{fill}" stroke="{INK}" stroke-width="4"/>'
    if cls:
        inner = f'<g class="{cls}">{inner}</g>'
    return f'<g transform="translate({sx} {sy}) rotate({ang})">{inner}</g>'

def _drop(x, y, s=1.0):
    return (f'<path transform="translate({x} {y}) scale({s})" d="M0 -16 C -11 2 -11 14 0 16 C 11 14 11 2 0 -16 Z" '
            f'fill="{SWEAT}" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>')

def _dots(x, y):
    return "".join(f'<circle cx="{x + i*22}" cy="{y}" r="6" fill="{INK}"/>' for i in range(3))

def _mirror(svg, facing):
    return f'<g transform="matrix(-1 0 0 1 300 0)">{svg}</g>' if facing == "left" else svg

def _eyes(cx_l, cx_r, cy, expr, blink, r=11):
    if blink:
        return (f'<path d="M{cx_l-12} {cy} q12 8 24 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>'
                f'<path d="M{cx_r-12} {cy} q12 8 24 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>')
    if expr == "happy":   # にっこり（^ ^）
        return (f'<path d="M{cx_l-13} {cy+3} q13 -16 26 0" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>'
                f'<path d="M{cx_r-13} {cy+3} q13 -16 26 0" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>')
    if expr == "calm":    # 半目
        return (f'<path d="M{cx_l-12} {cy-2} h24" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>'
                f'<path d="M{cx_r-12} {cy-2} h24" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>')
    rr = r + 5 if expr == "surprised" else r
    pr = 6 if expr != "surprised" else 7
    out = ""
    for cx in (cx_l, cx_r):
        out += f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="#fff" stroke="{INK}" stroke-width="3"/><circle cx="{cx+2}" cy="{cy+1}" r="{pr}" fill="{INK}"/><circle cx="{cx+5}" cy="{cy-3}" r="2.5" fill="#fff"/>'
    return out

def _brows(cx_l, cx_r, cy, expr):
    if expr == "fire":
        return (f'<path d="M{cx_l-14} {cy-4} l28 10" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>'
                f'<path d="M{cx_r+14} {cy-4} l-28 10" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>')
    if expr == "doubt":
        return (f'<path d="M{cx_l-14} {cy+2} l28 -6" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>'
                f'<path d="M{cx_r-14} {cy-10} h28" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>')
    if expr == "surprised":
        return (f'<path d="M{cx_l-13} {cy-6} q13 -10 26 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>'
                f'<path d="M{cx_r-13} {cy-6} q13 -10 26 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>')
    if expr == "calm":
        return (f'<path d="M{cx_l-13} {cy-8} q13 6 26 0" stroke="{INK}" stroke-width="4" fill="none" stroke-linecap="round"/>'
                f'<path d="M{cx_r-13} {cy-8} q13 6 26 0" stroke="{INK}" stroke-width="4" fill="none" stroke-linecap="round"/>')
    return ""

def _mouth(cx, cy, expr, open_):
    if open_:
        w, h = (16, 18) if expr in ("normal", "calm", "doubt") else (22, 24)
        return f'<ellipse cx="{cx}" cy="{cy+4}" rx="{w}" ry="{h}" fill="#C8321E" stroke="{INK}" stroke-width="4"/><ellipse cx="{cx}" cy="{cy+12}" rx="{w-6}" ry="{h/2.2:.0f}" fill="#FF8A80"/>'
    if expr == "happy" or expr == "fire":
        return f'<path d="M{cx-24} {cy-4} q24 30 48 0" stroke="{INK}" stroke-width="5" fill="#C8321E"/>'
    if expr == "surprised":
        return f'<ellipse cx="{cx}" cy="{cy+2}" rx="11" ry="14" fill="#C8321E" stroke="{INK}" stroke-width="4"/>'
    if expr == "doubt":
        return f'<path d="M{cx-18} {cy+4} q18 -8 36 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>'
    if expr == "calm":
        return f'<path d="M{cx-16} {cy} q16 8 32 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>'
    return f'<path d="M{cx-18} {cy-2} q18 14 36 0" stroke="{INK}" stroke-width="5" fill="none" stroke-linecap="round"/>'

def kotsu(expr="normal", mouth_open=False, blink=False, act="stand", facing="right") -> str:
    """コツさん（亀の大家）。viewBox 0 0 300 300。act 省略時は従来どおりの絵。"""
    face_y = 232
    sign = -1 if facing == "left" else 1
    # 手（既定の 2 つの楕円）・後ろ足・頭の上の印・体の傾き・頭のずれ
    hands = (f'<ellipse cx="62" cy="258" rx="26" ry="18" fill="#9CCC65" stroke="{INK}" stroke-width="5"/>\n'
             f'    <ellipse cx="238" cy="258" rx="26" ry="18" fill="#9CCC65" stroke="{INK}" stroke-width="5"/>')
    feet = ""; over = ""; lean = 0; head_shift = ""
    if act == "walk":
        hands = _ell(56, 250, 26, 18, 18, cls="arm-a") + _ell(244, 266, 26, 18, -18, cls="arm-b")
        feet = _ell(108, 291, 20, 9, cls="leg-a") + _ell(192, 291, 20, 9, cls="leg-b")
    elif act == "point":
        hands = _ell(62, 258, 26, 18) + _ell(272, 232, 32, 16, -22) + \
                f'<rect transform="translate(300 220) rotate(-22)" x="0" y="-6" width="30" height="12" rx="6" fill="{SKIN_K}" stroke="{INK}" stroke-width="4"/>'
    elif act == "think":
        hands = _ell(62, 258, 26, 18) + _ell(196, 270, 22, 16, -35)
        over = _dots(196, 26)
    elif act == "cheer":
        hands = _ell(34, 168, 20, 32, 30) + _ell(266, 168, 20, 32, -30)
        feet = _ell(108, 291, 20, 9) + _ell(192, 291, 20, 9)
    elif act == "sit":
        hands = _ell(98, 284, 26, 15) + _ell(202, 284, 26, 15)
    elif act == "shock":
        hands = _ell(36, 224, 18, 28, 48) + _ell(264, 224, 18, 28, -48)
        over = _drop(214, 190, .95) + _drop(232, 222, .75)
        lean = -8
    elif act == "bow":
        hands = _ell(112, 284, 24, 15, -12) + _ell(188, 284, 24, 15, 12)
        lean = 12; head_shift = "translate(5 14)"
    if act != "stand":
        hands = _mirror(hands, facing); feet = _mirror(feet, facing); over = _mirror(over, facing)
    head = f'''<circle cx="150" cy="{face_y}" r="50" fill="#9CCC65" stroke="{INK}" stroke-width="6"/>
    <circle cx="124" cy="{face_y+14}" r="7" fill="#F48FB1" opacity=".6"/><circle cx="176" cy="{face_y+14}" r="7" fill="#F48FB1" opacity=".6"/>
    {_brows(133, 167, face_y-16, expr)}
    {_eyes(133, 167, face_y-6, expr, blink)}
    {_mouth(150, face_y+18, expr, mouth_open)}'''
    if head_shift:
        head = f'<g transform="{head_shift if sign > 0 else head_shift.replace("translate(5", "translate(-5")}">{head}</g>'
    body = f'''
    <!-- 甲羅＝家 -->
    <ellipse cx="150" cy="172" rx="118" ry="78" fill="#1FA463" stroke="{INK}" stroke-width="6"/>
    <path d="M62 190 q88 -40 176 0" stroke="#2EC27A" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <path d="M90 150 q60 -30 120 0" stroke="#2EC27A" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <path d="M150 48 L272 130 H28 Z" fill="#FF7A1A" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>
    <rect x="212" y="66" width="24" height="44" fill="{INK}"/>
    <rect x="128" y="160" width="44" height="58" rx="8" fill="#FFF8E7" stroke="{INK}" stroke-width="5"/>
    <circle cx="163" cy="190" r="4" fill="{INK}"/>
    <!-- 手足 -->
    {feet}{hands}
    <!-- 頭 -->
    {head}
    <!-- 鍵のチャーム -->
    <circle cx="258" cy="200" r="11" fill="none" stroke="#F2B705" stroke-width="6"/><path d="M258 211 v28 l10 0 M258 230 l8 0" stroke="#F2B705" stroke-width="6" stroke-linecap="round"/>
    {over}'''
    if lean:
        body = f'<g transform="rotate({lean * sign} 150 292)">{body}</g>'
    return body

def ponta(expr="normal", mouth_open=False, blink=False, act="stand", facing="right") -> str:
    """ぽん太（たぬきの会社員）。viewBox 0 0 300 300。act 省略時は従来どおりの絵。"""
    sign = -1 if facing == "left" else 1
    arms = ""; feet = ""; over = ""; lean = 0; head_shift = ""
    L, R = (92, 262), (208, 262)   # 肩
    if act == "walk":
        arms = _arm(*L, 112, 40, FUR, cls="arm-a") + _arm(*R, 62, 40, FUR, cls="arm-b")
        feet = _ell(124, 293, 19, 8, fill=FUR_D, cls="leg-a") + _ell(176, 293, 19, 8, fill=FUR_D, cls="leg-b")
    elif act == "point":
        arms = _arm(*L, 96, 36, FUR) + _arm(*R, -14, 58, FUR, finger=True)
    elif act == "think":
        arms = _arm(*L, 96, 36, FUR) + _arm(*R, -128, 36, FUR, ry=10)
        over = _dots(236, 40)
    elif act == "cheer":
        arms = _arm(*L, -122, 60, FUR) + _arm(*R, -58, 60, FUR)
    elif act == "sit":
        arms = _arm(*L, 64, 34, FUR) + _arm(*R, 116, 34, FUR)
    elif act == "shock":
        arms = _arm(*L, -150, 54, FUR) + _arm(*R, -30, 54, FUR)
        over = _drop(254, 92, .95) + _drop(266, 126, .75)
        lean = -9
    elif act == "bow":
        arms = _arm(*L, 78, 40, FUR) + _arm(*R, 102, 40, FUR)
        lean = 12; head_shift = "translate(6 14)"
    if act != "stand":
        arms = _mirror(arms, facing); feet = _mirror(feet, facing); over = _mirror(over, facing)
    head = f'''<circle cx="92" cy="92" r="28" fill="#8D6E63" stroke="{INK}" stroke-width="5"/><circle cx="92" cy="94" r="14" fill="#4E342E"/>
    <circle cx="208" cy="92" r="28" fill="#8D6E63" stroke="{INK}" stroke-width="5"/><circle cx="208" cy="94" r="14" fill="#4E342E"/>
    <!-- 顔 -->
    <circle cx="150" cy="150" r="92" fill="#8D6E63" stroke="{INK}" stroke-width="6"/>
    <ellipse cx="150" cy="172" rx="68" ry="54" fill="#F5E6CC"/>
    <ellipse cx="116" cy="146" rx="27" ry="21" fill="#4E342E"/><ellipse cx="184" cy="146" rx="27" ry="21" fill="#4E342E"/>
    {_brows(116, 184, 118, expr)}
    {_eyes(116, 184, 146, expr, blink)}
    <ellipse cx="150" cy="176" rx="12" ry="9" fill="{INK}"/>
    {_mouth(150, 196, expr, mouth_open)}'''
    if head_shift:
        head = f'<g transform="{head_shift if sign > 0 else head_shift.replace("translate(6", "translate(-6")}">{head}</g>'
    body = f'''
    <!-- しっぽ -->
    <ellipse cx="248" cy="252" rx="42" ry="22" transform="rotate(-30 248 252)" fill="#8D6E63" stroke="{INK}" stroke-width="5"/>
    <path d="M232 262 l16 -10 M248 252 l16 -10" stroke="#4E342E" stroke-width="7" stroke-linecap="round"/>
    <!-- 体とネクタイ -->
    <path d="M90 300 V250 q60 -40 120 0 V300 Z" fill="#FFF8E7" stroke="{INK}" stroke-width="5"/>
    <path d="M150 232 l-12 18 l12 50 l12 -50 Z" fill="#2F80ED" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>{feet}{arms}
    <!-- 耳 -->
    {head}
    {over}'''
    if lean:
        body = f'<g transform="rotate({lean * sign} 150 300)">{body}</g>'
    return body

# ---------------------------------------------------------------- 人型（ユイさん・ソウタ）
SKIN = "#FFE3CC"
SKIN_S = "#F6C6A6"     # 首の影
CHEEK = "#FF8FA3"
HAIR_Y = "#3A2621"     # ユイさん: こげ茶のボブ
HAIR_Y2 = "#6A473B"
JKT_Y = "#22325A"      # ユイさん: 紺のジャケット
HAIR_S = "#D9893E"     # ソウタ: 明るい茶髪
HAIR_S2 = "#F2AE63"
SUIT_S = "#2A3E73"     # ソウタ: 紺のスーツ
TIE = "#2F80ED"
GOLD = "#F2B705"
FACE_CX, FACE_CY = 150, 116     # 顔の中心（viewBox 300）。scenes.py の確認でも使う
EYE_L, EYE_R, EYE_Y = 124, 176, 124


def _aeye(x, cy, expr, blink, iris, big=1.0, side="l"):
    """アニメ調の目 1 つ。doubt は左だけ半目にして片目で疑う"""
    if blink:
        return f'<path d="M{x-15} {cy} q15 9 30 0" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>'
    if expr == "happy":
        return f'<path d="M{x-15} {cy+5} q15 -20 30 0" stroke="{INK}" stroke-width="7" fill="none" stroke-linecap="round"/>'
    if expr == "calm" or (expr == "doubt" and side == "l"):
        return (f'<path d="M{x-12} {cy} a12 12 0 0 0 24 0 Z" fill="{iris}" stroke="{INK}" stroke-width="3"/>'
                f'<circle cx="{x}" cy="{cy+5}" r="4" fill="{INK}"/>'
                f'<path d="M{x-16} {cy} h32" stroke="{INK}" stroke-width="7" stroke-linecap="round"/>')
    rx, ry = 14 * big, 18 * big
    if expr == "surprised":
        rx, ry = 16 * big, 21 * big
        return (f'<ellipse cx="{x}" cy="{cy}" rx="{rx:.0f}" ry="{ry:.0f}" fill="#fff" stroke="{INK}" stroke-width="4"/>'
                f'<circle cx="{x}" cy="{cy+1}" r="7" fill="{INK}"/><circle cx="{x+3}" cy="{cy-3}" r="2.5" fill="#fff"/>')
    out = (f'<ellipse cx="{x}" cy="{cy}" rx="{rx:.0f}" ry="{ry:.0f}" fill="#fff" stroke="{INK}" stroke-width="3"/>'
           f'<ellipse cx="{x}" cy="{cy+3}" rx="{rx-3:.0f}" ry="{ry-3:.0f}" fill="{iris}"/>'
           f'<ellipse cx="{x}" cy="{cy+5}" rx="{rx-8:.0f}" ry="{ry-8:.0f}" fill="{INK}"/>'
           f'<circle cx="{x+5}" cy="{cy-5}" r="5" fill="#fff"/><circle cx="{x-5}" cy="{cy+9}" r="2.5" fill="#fff"/>'
           f'<path d="M{x-rx-2:.0f} {cy-ry+5:.0f} q{rx+2:.0f} -14 {2*rx+4:.0f} 0" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>')
    if expr == "fire":   # 目に光
        out += f'<path d="M{x-4} {cy+2} l4 -8 l4 8 l-4 8 Z" fill="#fff" opacity=".9"/>'
    return out


def _abrows(expr, color):
    l, r, y = EYE_L, EYE_R, EYE_Y - 28

    def ln(d, w=6):
        return f'<path d="{d}" stroke="{color}" stroke-width="{w}" fill="none" stroke-linecap="round"/>'
    if expr == "fire":
        return ln(f"M{l-15} {y-4} L{l+14} {y+6}") + ln(f"M{r+15} {y-4} L{r-14} {y+6}")
    if expr == "doubt":
        return ln(f"M{l-15} {y+6} L{l+14} {y+2}") + ln(f"M{r-14} {y-8} q14 -8 28 2")
    if expr == "surprised":
        return ln(f"M{l-14} {y-6} q14 -12 28 0") + ln(f"M{r-14} {y-6} q14 -12 28 0")
    if expr == "calm":
        return ln(f"M{l-14} {y+2} q14 -6 28 2", 5) + ln(f"M{r-14} {y+4} q14 -8 28 -2", 5)
    return ln(f"M{l-14} {y} q14 -7 28 0", 5) + ln(f"M{r-14} {y} q14 -7 28 0", 5)


def _amouth(expr, open_):
    cx, cy = FACE_CX, 156
    return f'<g transform="translate({cx} {cy}) scale(.72) translate({-cx} {-cy})">{_mouth(cx, cy, expr, open_)}</g>'


def _harm(sx, sy, ang, length, sleeve, finger=False, cls="", cuff="#fff"):
    """肩から伸びる腕（袖＋袖口＋手）。ang: 0=右 90=下 -90=上"""
    inner = (f'<rect x="-6" y="-13" width="{length}" height="26" rx="13" fill="{sleeve}" stroke="{INK}" stroke-width="5"/>'
             f'<rect x="{length-14}" y="-12" width="9" height="24" rx="3" fill="{cuff}" stroke="{INK}" stroke-width="3"/>'
             f'<circle cx="{length+5}" cy="0" r="13" fill="{SKIN}" stroke="{INK}" stroke-width="5"/>')
    if finger:
        inner += f'<rect x="{length+10}" y="-5" width="26" height="10" rx="5" fill="{SKIN}" stroke="{INK}" stroke-width="4"/>'
    if cls:
        inner = f'<g class="{cls}">{inner}</g>'
    return f'<g transform="translate({sx} {sy}) rotate({ang})">{inner}</g>'


def _legs(walk, pants, shoe, skirt=False):
    """足 2 本。walk のときは leg-a / leg-b（scenes.py の CSS が上下させる）"""
    def leg(x, cls):
        top, h = (268, 20) if skirt else (264, 24)
        g = (f'<rect x="{x-11}" y="{top}" width="22" height="{h}" rx="6" fill="{pants}" stroke="{INK}" stroke-width="5"/>'
             f'<ellipse cx="{x+3}" cy="291" rx="18" ry="9" fill="{shoe}" stroke="{INK}" stroke-width="5"/>')
        return f'<g class="{cls}">{g}</g>' if walk else g
    return leg(128, "leg-a") + leg(172, "leg-b")


def _pose_arms(act, L, R, sleeve):
    """8 ポーズの腕。戻り値 (腕, 頭上の印, 傾き, 頭のずれ)"""
    over = ""; lean = 0; shift = ""
    if act == "walk":
        arms = _harm(*L, 118, 46, sleeve, cls="arm-a") + _harm(*R, 62, 46, sleeve, cls="arm-b")
    elif act == "point":
        arms = _harm(*L, 100, 44, sleeve) + _harm(*R, -16, 58, sleeve, finger=True)
    elif act == "think":
        arms = _harm(*L, 100, 44, sleeve) + _harm(*R, -128, 44, sleeve)
        over = _dots(214, 22)
    elif act == "cheer":
        arms = _harm(*L, -128, 58, sleeve) + _harm(*R, -52, 58, sleeve)
    elif act == "sit":
        arms = _harm(*L, 62, 40, sleeve) + _harm(*R, 118, 40, sleeve)
    elif act == "shock":
        arms = _harm(*L, -156, 52, sleeve) + _harm(*R, -24, 52, sleeve)
        over = _drop(238, 74, .95) + _drop(252, 108, .75)
        lean = -8
    elif act == "bow":
        arms = _harm(*L, 70, 42, sleeve) + _harm(*R, 110, 42, sleeve)
        lean = 12; shift = "translate(6 14)"
    else:   # stand
        arms = _harm(*L, 104, 44, sleeve) + _harm(*R, 76, 44, sleeve)
    return arms, over, lean, shift


def _human(face_inner, hair_back, hair_front, torso, arms, legs, over, lean, shift, facing):
    """人型の組み立て。facing=left は全体を左右反転（顔の位置は中央のまま）"""
    head = (f'{hair_back}'
            f'<ellipse cx="{FACE_CX - 68}" cy="{FACE_CY + 8}" rx="10" ry="14" fill="{SKIN}" stroke="{INK}" stroke-width="5"/>'
            f'<ellipse cx="{FACE_CX + 68}" cy="{FACE_CY + 8}" rx="10" ry="14" fill="{SKIN}" stroke="{INK}" stroke-width="5"/>'
            f'<ellipse cx="{FACE_CX}" cy="{FACE_CY}" rx="66" ry="64" fill="{SKIN}" stroke="{INK}" stroke-width="6"/>'
            f'<ellipse cx="{FACE_CX - 42}" cy="148" rx="13" ry="8" fill="{CHEEK}" opacity=".55"/>'
            f'<ellipse cx="{FACE_CX + 42}" cy="148" rx="13" ry="8" fill="{CHEEK}" opacity=".55"/>'
            f'{hair_front}{face_inner}')
    if shift:
        head = f'<g transform="{shift}">{head}</g>'
    body = (f'{legs}<path d="M136 172 h28 v18 h-28 Z" fill="{SKIN_S}" stroke="{INK}" stroke-width="4"/>'
            f'{torso}{arms}{head}{over}')
    if lean:
        body = f'<g transform="rotate({lean} 150 296)">{body}</g>'
    return _mirror(body, facing)


def yui(expr="normal", mouth_open=False, blink=False, act="stand", facing="right") -> str:
    """ユイさん（大家のお姉さん。こげ茶のボブ・細いメガネ・紺のジャケット・金の鍵）。viewBox 0 0 300 300"""
    act = act if act in ACTS else "stand"
    arms, over, lean, shift = _pose_arms(act, (104, 204), (196, 204), JKT_Y)
    hair_back = (f'<path d="M74 122 C68 52 110 34 150 34 C190 34 232 52 226 122 L230 176 Q212 188 194 176 L196 150 '
                 f'L104 150 L106 176 Q88 188 70 176 Z" fill="{HAIR_Y}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>')
    hair_front = (f'<path d="M82 106 C80 58 114 40 152 40 C190 40 222 60 220 106 C208 96 200 82 194 68 '
                  f'C178 84 148 88 118 84 C106 90 94 98 82 106 Z" fill="{HAIR_Y}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>'
                  f'<path d="M118 58 q24 -12 48 -6" stroke="{HAIR_Y2}" stroke-width="7" fill="none" stroke-linecap="round"/>'
                  f'<path d="M82 108 L78 168 Q86 178 96 168 L96 116 Z" fill="{HAIR_Y}" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
                  f'<path d="M218 108 L222 168 Q214 178 204 168 L204 116 Z" fill="{HAIR_Y}" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>')
    eyes = _aeye(EYE_L, EYE_Y, expr, blink, "#8A5634", side="l") + _aeye(EYE_R, EYE_Y, expr, blink, "#8A5634", side="r")
    glasses = (f'<rect x="{EYE_L-24}" y="{EYE_Y-20}" width="48" height="40" rx="13" fill="#fff" fill-opacity=".12" stroke="{INK}" stroke-width="4"/>'
               f'<rect x="{EYE_R-24}" y="{EYE_Y-20}" width="48" height="40" rx="13" fill="#fff" fill-opacity=".12" stroke="{INK}" stroke-width="4"/>'
               f'<path d="M{EYE_L+24} {EYE_Y-6} Q150 {EYE_Y-13} {EYE_R-24} {EYE_Y-6}" stroke="{INK}" stroke-width="4" fill="none"/>')
    face = eyes + glasses + _abrows(expr, HAIR_Y) + _amouth(expr, mouth_open)
    torso = (f'<path d="M100 214 Q100 190 128 186 L172 186 Q200 190 200 214 L204 266 Q150 276 96 266 Z" fill="{JKT_Y}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>'
             f'<path d="M132 187 L150 232 L168 187 Z" fill="#fff" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
             f'<path d="M128 187 L144 216 L134 224 Z M172 187 L156 216 L166 224 Z" fill="#33477A" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
             # 鍵のネックレス（大家の印）
             f'<path d="M134 190 Q150 220 166 190" stroke="{GOLD}" stroke-width="3" fill="none"/>'
             f'<circle cx="150" cy="221" r="8" fill="none" stroke="{GOLD}" stroke-width="5"/>'
             f'<path d="M150 229 v17 h7 M150 240 h6" stroke="{GOLD}" stroke-width="5" stroke-linecap="round" fill="none"/>'
             # スカート
             f'<path d="M102 258 L198 258 L206 278 Q150 286 94 278 Z" fill="#2B2F3F" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>')
    legs = _legs(act == "walk", "#3A3F55", "#6B2E2E", skirt=True)
    return _human(face, hair_back, hair_front, torso, arms, legs, over, lean, shift, facing)


def souta(expr="normal", mouth_open=False, blink=False, act="stand", facing="right") -> str:
    """ソウタ（新人会社員。明るい茶髪のツンツン短髪・紺のスーツ・青いネクタイ・大きな目）。viewBox 0 0 300 300"""
    act = act if act in ACTS else "stand"
    arms, over, lean, shift = _pose_arms(act, (104, 204), (196, 204), SUIT_S)
    hair_back = (f'<path d="M80 120 C76 72 104 48 150 48 C196 48 224 72 220 120 L212 104 L88 104 Z" '
                 f'fill="{HAIR_S}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>')
    hair_front = (f'<path d="M80 106 L72 84 L92 88 L88 56 L112 66 L118 30 L140 56 L156 20 L170 54 L194 32 L198 64 L222 54 L214 86 L230 84 '
                  f'L220 106 C208 94 200 82 196 72 C184 86 160 90 140 84 C128 90 112 88 104 84 C98 94 90 102 80 106 Z" '
                  f'fill="{HAIR_S}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>'
                  f'<path d="M122 50 l10 18 M158 42 l6 20 M190 52 l-2 16" stroke="{HAIR_S2}" stroke-width="6" stroke-linecap="round"/>')
    eyes = _aeye(EYE_L, EYE_Y, expr, blink, "#3B6FB6", big=1.12, side="l") + _aeye(EYE_R, EYE_Y, expr, blink, "#3B6FB6", big=1.12, side="r")
    face = eyes + _abrows(expr, "#7A4A20") + _amouth(expr, mouth_open)
    torso = (f'<path d="M100 214 Q100 190 128 186 L172 186 Q200 190 200 214 L202 272 L98 272 Z" fill="{SUIT_S}" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>'
             f'<path d="M130 187 L150 236 L170 187 Z" fill="#fff" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
             f'<path d="M150 196 l-9 9 l9 44 l9 -44 Z" fill="{TIE}" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>'
             f'<path d="M141 189 h18 l-9 10 Z" fill="{TIE}" stroke="{INK}" stroke-width="3" stroke-linejoin="round"/>'
             f'<path d="M128 187 L146 224 L134 230 Z M172 187 L154 224 L166 230 Z" fill="#3A5290" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>')
    legs = _legs(act == "walk", SUIT_S, "#4A2E1E")
    return _human(face, hair_back, hair_front, torso, arms, legs, over, lean, shift, facing)


CHARACTERS = {
    "ユイさん": {"svg": yui,   "role": "答", "desc": "不動産の仕入れと販売をしている大家"},
    "ソウタ":   {"svg": souta, "role": "聞", "desc": "皮算用が得意な新人会社員"},
    # 旧キャラ（v6 までの台本用）
    "コツさん": {"svg": kotsu, "role": "答", "desc": "家を背負った亀の大家。コツコツ積み上げる本人役"},
    "ぽん太":   {"svg": ponta, "role": "聞", "desc": "皮算用が得意なたぬきの会社員。視聴者の疑問と驚きを言う役"},
}
EXPRS = ("normal", "happy", "surprised", "doubt", "calm", "fire")
STYLE_TO_EXPR = {"喜び": "happy", "あまあま": "happy", "熱血": "fire", "しっとり": "calm", "かなしみ": "calm",
                 "ツンツン": "doubt", "不機嫌": "doubt", "囁き": "calm", "ささやき": "calm", "ヒソヒソ": "calm"}

def guess_expr(st: str | None, text: str) -> str:
    if st and st in STYLE_TO_EXPR:
        return STYLE_TO_EXPR[st]
    if text.startswith(("えっ", "えー", "うわ", "おお")) or "！？" in text or "!?" in text:
        return "surprised"
    if text.endswith("！") or text.endswith("!"):
        return "happy"
    return "normal"

def svg_document(body: str, size: int = 300) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="{size}" height="{size}">'
            f'<defs><filter id="sh"><feDropShadow dx="0" dy="6" stdDeviation="0" flood-color="{INK}" flood-opacity=".18"/></filter></defs>'
            f'<g filter="url(#sh)">{body}</g></svg>')

if __name__ == "__main__":
    import sys
    from pathlib import Path
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    html = ['<html><head><meta charset="utf-8"><style>body{background:#FFF8E7;margin:0;padding:20px;font-family:sans-serif}.row{display:flex;gap:10px;align-items:center}.row span{width:90px;font-weight:700}</style></head><body>']
    for name, c in CHARACTERS.items():
        html.append(f'<div class="row"><span>{name}</span>')
        for e in EXPRS:
            html.append(svg_document(c["svg"](e), 170))
        html.append(svg_document(c["svg"]("normal", True), 170))
        html.append(svg_document(c["svg"]("normal", False, True), 170))
        html.append('</div>')
        html.append(f'<div class="row"><span>{name} ポーズ</span>')
        for a in ACTS:
            html.append(svg_document(c["svg"]("normal", act=a), 170))
        html.append('</div>')
    html.append('</body></html>')
    (out / "sheet.html").write_text("\n".join(html), encoding="utf-8")
    print(out / "sheet.html")
