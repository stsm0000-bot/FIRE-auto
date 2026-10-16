# -*- coding: utf-8 -*-
"""
characters.py ― チャンネル「小規模な大家」の原作キャラクター（SVG）
  コツさん : 家を背負った亀の大家。コツコツ積み上げる本人役。
  ぽん太   : 皮算用が得意なたぬきの会社員。視聴者の疑問・驚きを言う役。
表情: normal / happy / surprised / doubt / calm / fire   口: open/closed   目: blink
"""
INK = "#1F2A44"

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

def kotsu(expr="normal", mouth_open=False, blink=False) -> str:
    """コツさん（亀の大家）。viewBox 0 0 300 300"""
    face_y = 232
    return f'''
    <!-- 甲羅＝家 -->
    <ellipse cx="150" cy="172" rx="118" ry="78" fill="#1FA463" stroke="{INK}" stroke-width="6"/>
    <path d="M62 190 q88 -40 176 0" stroke="#2EC27A" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <path d="M90 150 q60 -30 120 0" stroke="#2EC27A" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <path d="M150 48 L272 130 H28 Z" fill="#FF7A1A" stroke="{INK}" stroke-width="6" stroke-linejoin="round"/>
    <rect x="212" y="66" width="24" height="44" fill="{INK}"/>
    <rect x="128" y="160" width="44" height="58" rx="8" fill="#FFF8E7" stroke="{INK}" stroke-width="5"/>
    <circle cx="163" cy="190" r="4" fill="{INK}"/>
    <!-- 手足 -->
    <ellipse cx="62" cy="258" rx="26" ry="18" fill="#9CCC65" stroke="{INK}" stroke-width="5"/>
    <ellipse cx="238" cy="258" rx="26" ry="18" fill="#9CCC65" stroke="{INK}" stroke-width="5"/>
    <!-- 頭 -->
    <circle cx="150" cy="{face_y}" r="50" fill="#9CCC65" stroke="{INK}" stroke-width="6"/>
    <circle cx="124" cy="{face_y+14}" r="7" fill="#F48FB1" opacity=".6"/><circle cx="176" cy="{face_y+14}" r="7" fill="#F48FB1" opacity=".6"/>
    {_brows(133, 167, face_y-16, expr)}
    {_eyes(133, 167, face_y-6, expr, blink)}
    {_mouth(150, face_y+18, expr, mouth_open)}
    <!-- 鍵のチャーム -->
    <circle cx="258" cy="200" r="11" fill="none" stroke="#F2B705" stroke-width="6"/><path d="M258 211 v28 l10 0 M258 230 l8 0" stroke="#F2B705" stroke-width="6" stroke-linecap="round"/>
    '''

def ponta(expr="normal", mouth_open=False, blink=False) -> str:
    """ぽん太（たぬきの会社員）。viewBox 0 0 300 300"""
    return f'''
    <!-- しっぽ -->
    <ellipse cx="248" cy="252" rx="42" ry="22" transform="rotate(-30 248 252)" fill="#8D6E63" stroke="{INK}" stroke-width="5"/>
    <path d="M232 262 l16 -10 M248 252 l16 -10" stroke="#4E342E" stroke-width="7" stroke-linecap="round"/>
    <!-- 体とネクタイ -->
    <path d="M90 300 V250 q60 -40 120 0 V300 Z" fill="#FFF8E7" stroke="{INK}" stroke-width="5"/>
    <path d="M150 232 l-12 18 l12 50 l12 -50 Z" fill="#2F80ED" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>
    <!-- 耳 -->
    <circle cx="92" cy="92" r="28" fill="#8D6E63" stroke="{INK}" stroke-width="5"/><circle cx="92" cy="94" r="14" fill="#4E342E"/>
    <circle cx="208" cy="92" r="28" fill="#8D6E63" stroke="{INK}" stroke-width="5"/><circle cx="208" cy="94" r="14" fill="#4E342E"/>
    <!-- 顔 -->
    <circle cx="150" cy="150" r="92" fill="#8D6E63" stroke="{INK}" stroke-width="6"/>
    <ellipse cx="150" cy="172" rx="68" ry="54" fill="#F5E6CC"/>
    <ellipse cx="116" cy="146" rx="27" ry="21" fill="#4E342E"/><ellipse cx="184" cy="146" rx="27" ry="21" fill="#4E342E"/>
    {_brows(116, 184, 118, expr)}
    {_eyes(116, 184, 146, expr, blink)}
    <ellipse cx="150" cy="176" rx="12" ry="9" fill="{INK}"/>
    {_mouth(150, 196, expr, mouth_open)}
    '''

CHARACTERS = {
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
    html.append('</body></html>')
    (out / "sheet.html").write_text("\n".join(html), encoding="utf-8")
    print(out / "sheet.html")
