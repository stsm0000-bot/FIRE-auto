#!/usr/bin/env python3
"""make_channel_art.py ― チャンネルの見た目（バナー・アイコン・動画の透かし）を作る。

使い方（youtube フォルダで）:
  python pipeline/make_channel_art.py            → youtube/channel/ に書き出す
  python pipeline/make_channel_art.py --out 別の場所

出力:
  banner.png          2560x1440（YouTube の推奨。どの端末でも見える中央 1546x423 に文字とキャラを収める）
  banner_確認用.png   どの端末でも見える範囲を赤枠で示したもの（アップロードしない）
  icon.png            800x800（丸く切り抜かれる前提。ユイさんの顔）
  watermark.png       150x150（動画の右下に出る登録ボタンの透かし）
文言は下の TEXT を直す。キャラの絵は characters.py（ユイさん・ソウタ）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import characters  # noqa: E402
from make_video import default_font, find_chrome, render_png  # noqa: E402

TEXT = {
    "name": "小規模な大家",
    "tagline": "安い戸建ての数字を、モデルケースで",
    "points": ["買値", "直し", "家賃", "管理費", "手残り"],
    "schedule": "毎週土曜 7:00 更新",
    "note": "探し方・買い方は note で",
}

INK, ACCENT, GOLD, PAPER = "#1F2A44", "#FF7A1A", "#F2B705", "#FFF8E7"


def char_svg(name: str, expr: str, act: str, facing: str = "right", view: str = "0 0 300 300") -> str:
    body = characters.CHARACTERS[name]["svg"](expr, False, False, act, facing)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="100%" height="100%">{body}</svg>'


def banner_html(guide: bool) -> str:
    pts = "".join(f'<span>{p}</span>' + ('<i>→</i>' if i < len(TEXT["points"]) - 1 else "") for i, p in enumerate(TEXT["points"]))
    houses = "".join('<b class="h"></b>' for _ in range(26))
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:2560px;height:1440px;overflow:hidden;background:{PAPER};font-family:"{default_font()}","Noto Sans JP","BIZ UDPGothic","Meiryo",sans-serif;color:{INK}}}
body::before{{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(255,122,26,.16) 4px,transparent 4.5px);background-size:56px 56px}}
/* 上下の帯（パソコン・テレビでだけ見える所） */
.band{{position:absolute;left:0;right:0;height:300px;background:{INK}}}
.band.top{{top:0}} .band.bot{{bottom:0}}
.row{{position:absolute;left:0;right:0;bottom:300px;height:120px;display:flex;justify-content:space-around;align-items:flex-end;opacity:.22}}
.h{{width:70px;height:56px;background:{ACCENT};position:relative;display:block}}
.h::before{{content:"";position:absolute;left:-12px;top:-40px;border:47px solid transparent;border-bottom:40px solid {INK};border-top:0}}
/* どの端末でも見える範囲 1546x423（中央） */
.safe{{position:absolute;left:507px;top:508px;width:1546px;height:424px;display:flex;align-items:center;justify-content:center}}
.c{{position:absolute;bottom:-6px;width:340px;height:410px}}
.c.l{{left:0}} .c.r{{right:0}}
.c svg{{filter:drop-shadow(5px 0 0 #fff) drop-shadow(-5px 0 0 #fff) drop-shadow(0 -5px 0 #fff) drop-shadow(0 8px 0 rgba(0,0,0,.18))}}
.mid{{text-align:center;display:flex;flex-direction:column;align-items:center;gap:14px}}
.name{{font-size:138px;font-weight:900;letter-spacing:.02em;line-height:1;-webkit-text-stroke:8px #fff;paint-order:stroke fill;
  text-shadow:0 10px 0 rgba(31,42,68,.16)}}
.tag{{font-size:50px;font-weight:900;color:#fff;background:{ACCENT};padding:10px 36px;border-radius:999px;box-shadow:0 6px 0 rgba(31,42,68,.22)}}
.pts{{font-size:40px;font-weight:800;display:flex;gap:10px;align-items:center}}
.pts span{{background:#fff;border:4px solid {INK};border-radius:12px;padding:2px 16px}}
.pts i{{font-style:normal;color:{ACCENT}}}
.info{{display:flex;gap:16px;font-size:30px;font-weight:900}}
.sch{{color:{INK};background:{GOLD};padding:4px 18px;border-radius:10px}}
.nt{{color:#fff;background:{INK};padding:4px 18px;border-radius:10px}}
{'.safe{outline:6px dashed red}' if guide else ''}
</style></head><body>
<div class="band top"></div><div class="row">{houses}</div><div class="band bot"></div>
<div class="safe">
  <div class="c l">{char_svg("ソウタ", "surprised", "cheer")}</div>
  <div class="mid"><div class="name">{TEXT["name"]}</div><div class="tag">{TEXT["tagline"]}</div><div class="pts">{pts}</div>
    <div class="info"><span class="sch">{TEXT["schedule"]}</span><span class="nt">{TEXT["note"]}</span></div></div>
  <div class="c r">{char_svg("ユイさん", "happy", "cheer", "left")}</div>
</div></body></html>"""


def icon_html(size: int, ring: int) -> str:
    # 顔の中心は viewBox (150,116)。顔と肩が丸に収まるよう切り出す
    face = char_svg("ユイさん", "happy", "stand", view="52 22 196 196")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0}} html,body{{width:{size}px;height:{size}px;overflow:hidden;background:transparent}}
.o{{width:{size}px;height:{size}px;border-radius:50%;background:{ACCENT};display:flex;align-items:center;justify-content:center}}
.i{{width:{size - 2 * ring}px;height:{size - 2 * ring}px;border-radius:50%;background:{PAPER};overflow:hidden;display:flex;align-items:flex-end;justify-content:center}}
.i svg{{width:92%;height:92%}}
</style></head><body><div class="o"><div class="i">{face}</div></div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="チャンネルのバナー・アイコン・透かしを作る")
    ap.add_argument("--out", default=str(HERE.parent / "channel"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"; work.mkdir(exist_ok=True)
    chrome = find_chrome()
    jobs = [("banner", banner_html(False), (2560, 1440)), ("banner_確認用", banner_html(True), (2560, 1440)),
            ("icon", icon_html(800, 40), (800, 800)), ("watermark", icon_html(600, 40), (600, 600))]
    for name, html, size in jobs:
        png = render_png(chrome, html, work / f"{name}.png", size)
        im = Image.open(png).convert("RGB")
        if name == "watermark":
            im = im.resize((150, 150), Image.LANCZOS)
        im.save(out / f"{name}.png")
        print("書き出し:", out / f"{name}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
