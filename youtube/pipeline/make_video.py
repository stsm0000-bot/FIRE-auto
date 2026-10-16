#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_video.py  ―  YAML台本から YouTube 用 mp4 を一発で作る

  使い方:
    python make_video.py build scripts/001.yaml --out out/001            # VOICEVOX を使う（既定）
    python make_video.py build scripts/001.yaml --out out/001 --tts stub # 音声なしで画と尺だけ確認
    python make_video.py qa    out/001/001.mp4                           # 出来上がりの検査だけ

  流れ:  台本 → スライド描画(Chrome) → 音声(VOICEVOX) → 字幕(ASS) → 結合(ffmpeg) → 検査(QA) → 公開用メモ
  依存:  python3.10+, pyyaml, Pillow, ffmpeg(libass/libx264), Chrome または Chromium, VOICEVOX エンジン(任意)
"""
from __future__ import annotations

import argparse, hashlib, json, math, os, platform, re, shutil, subprocess, sys, textwrap, urllib.parse, urllib.request, wave
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import numpy as np
from PIL import Image, ImageDraw
import audio_synth
import characters
try:
    import scenes          # 物語シーン（演出部）。無くても図解だけの台本はビルドできる
except ImportError:
    scenes = None

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "slide.html"
FPS = 30
SR = 24000  # VOICEVOX の出力サンプリング周波数

# ---------------------------------------------------------------- 設定
SIZES = {"long": (1920, 1080), "short": (1080, 1920)}
PAUSE_LINE = 0.30       # 台詞のあとの間
PAUSE_SCENE = 0.60      # 場面が変わるときの間
PAUSE_CHAPTER = 0.80    # 章扉のあとの間
XFADE_FRAMES = 6        # 場面が変わるときのクロスフェードのコマ数（0.2秒）
JUMP_ZOOMS = (1.0, 1.045, 1.0, 1.07, 1.0, 1.045)   # 画が変わらない台詞が続くとき、台詞ごとに寄る倍率（ジャンプカット風）
ANIM_SEC = {            # 状態が変わったとき、何秒ぶんコマ撮りするか（レイアウト別）
    "chapter": 0.7, "title": 0.8, "list": 0.8, "flow": 0.9, "compare": 0.8, "bar": 1.3, "quote": 0.7,
    "ending": 0.9, "counter": 2.3, "portfolio": 2.4, "timeline": 0.9, "photo": 0.9, "scene": 1.3, "clip": 0.0,
}
MOUTH_STEP = 0.11       # 物語シーンの口パク: 開/閉を切り替える間隔（秒）
BLINK_EVERY, BLINK_LEN = 3.7, 0.13   # まばたきの周期と長さ（秒）
SCENE_SFX_AUTO = {      # 物語シーンで自動で鳴らす効果音（場面の頭）。台本の sfx: で上書き
    "bg": {"office": "door", "bankbook": "cash", "site": "hammer", "bank": "door"},
    "act": {"walk": "step", "shock": "shock", "cheer": "sparkle", "bow": "pop"},
    "prop": {"stamp": "stamp", "money": "coin", "coins": "coin", "cross": "boing", "check": "ding", "price": "pop",
             "headline": "reveal", "photo": "whoosh", "calendar": "tick", "sign": "pop", "counter": "coin"},
}
SCENE_AMBIENCE = {      # 背景 → 環境音
    "street": "street", "house_old": "street", "house_new": "street", "site": "site", "night": "night",
    "room_old": "room", "room_new": "room", "office": "room", "desk": "room", "bank": "room", "bankbook": "room",
}
RENDER_JS = HERE / "render_frames.js"
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
STUB_SEC_PER_CHAR = 0.17  # スタブ音声: 1文字あたりの秒数（VOICEVOX 標準速の目安）

def default_font() -> str:
    if platform.system() == "Windows":
        return "BIZ UDPGothic"
    return "IPAPGothic"

def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    cands = []
    if platform.system() == "Windows":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")]:
            cands += [Path(base) / "Google/Chrome/Application/chrome.exe",
                      Path(base) / "Microsoft/Edge/Application/msedge.exe"]
    else:
        for name in ["google-chrome", "chromium", "chromium-browser", "chrome"]:
            p = shutil.which(name)
            if p:
                return p
        cands += sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    for c in cands:
        if Path(c).exists():
            return str(c)
    sys.exit("Chrome/Edge が見つかりません。環境変数 CHROME_PATH に実行ファイルの場所を指定してください。")

def run(cmd: list[str], cwd: Path | None = None, quiet=True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"コマンド失敗: {' '.join(map(str, cmd[:3]))} ...")
    return r

# ---------------------------------------------------------------- 台本
@dataclass
class Line:
    sp: str
    text: str
    step: int
    mark: int | None = None
    pause: float = PAUSE_LINE
    prev_step: int = 0
    st: str | None = None          # VOICEVOX のスタイル名（喜び・熱血 など）
    speed: float | None = None
    intonation: float | None = None
    face: str | None = None        # キャラの表情（normal/happy/surprised/doubt/calm/fire）

@dataclass
class Scene:
    id: str
    layout: str
    data: dict
    lines: list[Line]
    steps: int
    chapter_no: int | None = None

def load_script(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc.setdefault("kind", "long")
    doc.setdefault("speakers", {
        "聞": {"speaker": "ずんだもん", "style": "ノーマル", "name": "ぽん太", "color": "#2F80ED", "char": "ぽん太"},
        "答": {"speaker": "青山龍星", "style": "ノーマル", "name": "コツさん", "color": "#FF7A1A", "char": "コツさん"},
    })
    for key, sp in doc["speakers"].items():
        sp.setdefault("char", "コツさん" if key == "答" else "ぽん太")
    doc.setdefault("voice", {})
    doc["voice"] = {"speed": 1.08, "intonation": 1.25, "pitch": 0.0} | doc["voice"]
    scenes: list[Scene] = []
    chapter_no = 0
    for s in doc["scenes"]:
        layout = s.get("layout", "title")
        if layout == "chapter":
            chapter_no += 1
        items = s.get("items") or s.get("rows") or []
        if layout in ("list", "flow", "bar", "timeline"):
            default_steps = max(1, len(items))
        elif layout == "portfolio":
            default_steps = int(s.get("count", 12))
        elif layout == "compare" or (layout == "quote" and s.get("caption")):
            default_steps = 2
        elif layout == "scene":
            default_steps = max([int(p.get("step", 1)) for p in (s.get("props") or [])] + [1])
        else:
            default_steps = 1
        if layout == "scene" and scenes is None:
            raise SystemExit("layout: scene を使うには pipeline/scenes.py が必要です")
        steps = int(s.get("steps", default_steps))
        lines, cur, prev = [], 1, 0
        for ln in s.get("lines", []):
            cur = min(int(ln.get("step", cur)), steps)
            lines.append(Line(sp=ln["sp"], text=str(ln["text"]).strip(), step=cur,
                              mark=ln.get("mark"), pause=float(ln.get("pause", PAUSE_LINE)), prev_step=prev,
                              st=ln.get("st"), speed=ln.get("speed"), intonation=ln.get("intonation"), face=ln.get("face")))
            prev = cur
        scenes.append(Scene(id=str(s["id"]), layout=layout, data=s, lines=lines, steps=steps,
                            chapter_no=chapter_no if layout == "chapter" else None))
    doc["_scenes"] = scenes
    doc["_script_dir"] = path.resolve().parent
    doc["_chapters"] = chapter_no
    return doc

# ---------------------------------------------------------------- スライド描画
def esc(s) -> str:
    # ★ は「公開前に本人が確認する数字」の目印。画面には出さない
    return (str(s).replace("★", "").rstrip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))

def house_svg(on: bool = True) -> str:
    ink = "#1F2A44" if on else "#A9A59B"; roof = "#FF7A1A" if on else "#D8D4CA"
    return ('<svg viewBox="0 0 100 90"><path d="M20 48 V84 H80 V48 Z" fill="#fff" stroke="%s" stroke-width="6" stroke-linejoin="round"/>'
            '<path d="M50 8 L94 48 H6 Z" fill="%s" stroke="%s" stroke-width="6" stroke-linejoin="round"/>'
            '<rect x="42" y="58" width="16" height="26" fill="%s"/></svg>' % (ink, roof, ink, ink))

def burst_html(n: int = 22, seed: int = 3) -> str:
    """紙吹雪（CSS アニメ）。seek で時刻を指定して撮る前提"""
    import random
    rnd = random.Random(seed); cols = ["#FF7A1A", "#1FA463", "#F2B705", "#2F80ED", "#FF4D6D"]
    out = ['<div class="burst">']
    for i in range(n):
        ang = rnd.uniform(0, 6.283); dist = rnd.uniform(260, 620)
        x = int(math.cos(ang) * dist); y = int(math.sin(ang) * dist * 0.7) - 120
        out.append(f'<i style="background:{cols[i % len(cols)]};--x:{x}px;--y:{y}px;--r:{rnd.randint(180, 720)}deg;--d:{rnd.uniform(0, .25):.2f}s"></i>')
    out.append('</div>')
    return "".join(out)

def scene_faces(doc: dict, sc: Scene, ln: Line | None) -> tuple[dict[str, str], str | None]:
    """物語シーンの各キャラの表情と、話しているキャラ名"""
    faces: dict[str, str] = {}
    for c in sc.data.get("chars") or []:
        faces[str(c.get("who", ""))] = str(c.get("face") or "normal")
    talking = None
    if ln is not None and ln.text:
        sp = doc["speakers"].get(ln.sp, {})
        talking = sp.get("name") or sp.get("char")
        if talking:
            faces[talking] = ln.face or characters.guess_expr(ln.st, ln.text)
    return faces, talking

def clip_placeholder(d: dict, missing: str | None) -> dict:
    """clip の映像ファイルが無いとき、代わりに出す物語シーン（無地＋立て札）"""
    props = [{"kind": "sign", "text": f"ここに映像\n{missing}" if missing else "ここに映像", "at": "center", "step": 1}]
    if d.get("headline"):
        props.append({"kind": "headline", "text": d["headline"], "step": 1})
    return {"bg": "blank", "props": props, "steps": 1}

def render_body(doc: dict, sc: Scene, step: int, mark: int | None, anim: bool, prev_step: int = 0,
                faces: dict | None = None, talking: str | None = None, variant: str = "closed") -> str:
    """anim=True のとき、この状態で新しく出る要素に .enter（出現アニメ）を付ける"""
    d = sc.data
    L = sc.layout
    h = []
    ent = lambda cond, extra="": (f' enter {extra}' if (anim and cond) else "")
    if L == "scene":
        return scenes.render_scene(d, step, prev_step, anim, doc["kind"], faces or {}, talking, variant, doc["_script_dir"])
    elif L == "clip":
        if scenes is not None:
            return scenes.render_scene(clip_placeholder(d, d.get("_missing")), 1, 0, anim, doc["kind"], {}, None, "closed", doc["_script_dir"])
        hd = d.get("headline") or "映像"
        h.append(f'<div class="title"><div class="big{ent(True)}">{esc(hd)}</div><div class="sub{ent(True)}" style="--i:2">ここに映像{(" / " + esc(d["_missing"])) if d.get("_missing") else ""}</div></div>')
        return "\n".join(h)
    elif L == "chapter":
        h.append(f'<div class="chapter{ent(True)}"><div class="num">{sc.chapter_no}</div><div class="ttl">{esc(d.get("heading",""))}</div></div>')
    elif L == "title":
        hd = str(d.get("heading", ""))
        longest = max((len(x) for x in hd.split("\n")), default=0)
        size_cls = " long" if longest > 18 else ""
        h.append(f'<div class="title"><div class="big{size_cls}{ent(True)}">{esc(hd)}</div>')
        if d.get("sub"):
            h.append(f'<div class="sub{ent(True)}" style="--i:2">{esc(d["sub"])}</div>')
        if d.get("cast"):
            h.append('<div class="cast">')
            for k, key in enumerate(("聞", "答")):
                sp = doc["speakers"].get(key, {}); ch = characters.CHARACTERS.get(sp.get("char", ""))
                if not ch: continue
                h.append(f'<div class="castc{ent(True, "pop")}" style="--i:{3+k*2}">{characters.svg_document(ch["svg"]("happy"), 260)}'
                         f'<div class="cname" style="background:{sp.get("color","#888")}">{esc(sp.get("name",""))}</div><div class="cdesc">{esc(ch["desc"])}</div></div>')
            h.append('</div>')
        h.append('</div>')
    elif L in ("list", "flow"):
        items = d.get("items", [])
        h.append(f'<div class="{L}">')
        if d.get("heading"):
            h.append(f'<div class="h{ent(step <= 1)}">{esc(d["heading"])}</div>')
        h.append('<div class="row">')
        for i, it in enumerate(items, 1):
            it = {"text": it} if isinstance(it, str) else it
            new = (prev_step < i <= step) if anim else False
            cls = "box" + (" on" if i <= step else " off") + (" mark" if mark == i else "") + (" sum" if it.get("sum") else "")
            cls += (" enter pop" if new else "")
            if L == "flow" and i > 1:
                op = it.get("op")
                h.append(f'<div class="{"op" if op else "arrow"}{" on" if i <= step else " off"}{" enter" if new else ""}" style="--i:{(i-prev_step-1)*2}">{esc(op) if op else "→"}</div>')
            inner = f'<span class="n">{i}</span>' if L == "list" else ""
            if it.get("value") is not None:
                inner += f'<span class="v">{esc(it["value"])}</span>'
            inner += f'<span class="t">{esc(it.get("text",""))}</span>'
            if it.get("note") and i <= step:
                inner += f'<span class="note">{esc(it["note"])}</span>'
            h.append(f'<div class="{cls}" style="--i:{(i-prev_step-1)*2+1 if new else 0}">{inner}</div>')
        h.append('</div></div>')
    elif L == "compare":
        h.append('<div class="compare">')
        for k, side in enumerate(("left", "right"), 1):
            sd = d.get(side, {})
            new = (prev_step < k <= step) if anim else False
            cls = "col" + (" on" if k <= step else " off") + f' {sd.get("tone","")}' + (" enter slide" if new else "")
            h.append(f'<div class="{cls}"><div class="ct">{esc(sd.get("title",""))}</div>')
            for j, it in enumerate(sd.get("items", [])):
                h.append(f'<div class="ci{" enter" if new else ""}" style="--i:{j+2}">{esc(it)}</div>')
            h.append('</div>')
        h.append('</div>')
    elif L == "bar":
        rows = d.get("rows", [])
        mx = max([float(r.get("value", 0)) for r in rows] + [1.0])
        h.append('<div class="bars">')
        if d.get("heading"):
            h.append(f'<div class="h{ent(step <= 1)}">{esc(d["heading"])}</div>')
        for i, r in enumerate(rows, 1):
            w = int(100 * float(r.get("value", 0)) / mx)
            new = (prev_step < i <= step) if anim else False
            cls = "brow" + (" on" if i <= step else " off") + (" mark" if mark == i else "") + (" enter" if new else "")
            h.append(f'<div class="{cls}" style="--i:{i-prev_step-1}"><div class="bl">{esc(r.get("label",""))}</div>'
                     f'<div class="bt"><div class="bf" style="width:{w}%"></div></div><div class="bv">{esc(r.get("note",""))}</div></div>')
        h.append('</div>')
    elif L == "quote":
        h.append('<div class="quote">')
        if d.get("heading"):
            h.append(f'<div class="h{ent(step <= 1)}">{esc(d["heading"])}</div>')
        h.append(f'<div class="qbox{ent(step <= 1, "pop")}">{esc(d.get("text",""))}</div>')
        if d.get("caption"):
            h.append(f'<div class="cap{" on" if step >= 2 else " off"}{ent(step >= 2 and prev_step < 2)}">{esc(d["caption"])}</div>')
        h.append('</div>')
    elif L == "ending":
        h.append(f'<div class="ending"><div class="eh{ent(True)}">今日の一歩</div>'
                 f'<div class="eb{ent(True)}" style="--i:1">{esc(d.get("heading",""))}</div>')
        if d.get("sub"):
            h.append(f'<div class="es{ent(True)}" style="--i:3">{esc(d["sub"])}</div>')
        h.append(f'<div class="ecta{ent(True)}" style="--i:5">{esc(d.get("cta", "続きは note で ▶"))}</div></div>')
    elif L == "counter":
        # 大きな数字が 0 から伸びる。value: 数値, unit: "万円" など, dur: 秒
        val = float(d.get("value", 0)); dec = int(d.get("decimals", 0))
        dur = int(float(d.get("dur", 2.0)) * 1000)
        cnt = (f'<span data-count-from="0" data-count-to="{val}" data-count-dur="{dur}" data-count-dec="{dec}" data-prefix="{esc(d.get("prefix",""))}">0</span>'
               if anim else f'{esc(d.get("prefix",""))}{val:,.{dec}f}')
        h.append(f'<div class="counter{" money" if d.get("tone") == "money" else ""}"><div class="lbl{ent(True)}">{esc(d.get("heading",""))}</div>'
                 f'<div class="num{ent(True, "pop")}">{cnt}<small>{esc(d.get("unit",""))}</small></div>')
        if d.get("sub"):
            h.append(f'<div class="sub{ent(True)}" style="--i:4">{esc(d["sub"])}</div>')
        h.append('</div>')
        if anim and d.get("burst"):
            h.append(burst_html(seed=int(val)))
    elif L == "portfolio":
        # 戸建てが 1 軒ずつ増え、右の合計（戸数・月の家賃・年の家賃）が転がる
        n = int(d.get("count", 12)); rent = float(d.get("rent", 7)); cols = int(d.get("cols", 6 if doc["kind"] == "long" else 4))
        h.append(f'<div class="portfolio"><div class="houses" style="--cols:{cols}">')
        for i in range(1, n + 1):
            new = (prev_step < i <= step) if anim else False
            on = i <= step
            h.append(f'<div class="house{" on" if on else " off"}{" enter pop" if new else ""}" style="--i:{i-prev_step-1}">'
                     f'{house_svg(on)}<span>{esc(d.get("label","戸建て"))} {i}</span></div>')
        h.append('</div><div class="totals">')
        rows = [("戸数", prev_step, step, "戸", 0), (d.get("rent_label", "月の家賃"), prev_step * rent, step * rent, d.get("unit", "万円"), 0),
                ("年の家賃", prev_step * rent * 12, step * rent * 12, d.get("unit", "万円"), 0)]
        delay = 200 + max(0, step - prev_step - 1) * 120
        for k, (lbl, frm, to, unit, dec) in enumerate(rows):
            v = (f'<span data-count-from="{frm}" data-count-to="{to}" data-count-dur="900" data-count-delay="{delay}" data-count-dec="{dec}">{frm:,.{dec}f}</span>'
                 if anim and frm != to else f'{to:,.{dec}f}')
            h.append(f'<div class="tot"><div class="tl">{esc(lbl)}</div><div class="tv">{v}<small> {esc(unit)}</small></div></div>')
        # コインの山（戸数ぶん積み上がる）
        h.append('<div class="coins"><div class="stack">')
        for i in range(1, step + 1):
            new = (prev_step < i) if anim else False
            h.append(f'<div class="coin{" enter pop" if new else ""}" style="--i:{(i-prev_step-1)+1}"></div>')
        h.append('</div></div>')
        h.append('</div>')
        if anim and step >= n:
            h.append(burst_html())
        h.append('</div>')
    elif L == "timeline":
        items = d.get("items", [])
        h.append(f'<div class="timeline">')
        if d.get("heading"):
            h.append(f'<div class="h{ent(step <= 1)}">{esc(d["heading"])}</div>')
        h.append('<div class="tl-line"></div>')
        h.append(f'<div class="tl-items" style="--n:{len(items)}">')
        for i, it in enumerate(items, 1):
            new = (prev_step < i <= step) if anim else False
            h.append(f'<div class="tl-item{" on" if i <= step else " off"}{" mark" if mark == i else ""}{" enter pop" if new else ""}" style="--i:{i-prev_step-1}">'
                     f'<div class="dot"></div><div class="when">{esc(it.get("when",""))}</div><div class="what">{esc(it.get("text",""))}</div>'
                     + (f'<div class="note">{esc(it["note"])}</div>' if it.get("note") else "") + '</div>')
        h.append('</div></div>')
    elif L == "photo":
        # before / after の写真（無ければ枠だけ）。パスは台本ファイルからの相対でも可
        h.append('<div class="photos">')
        for k, key in enumerate(("before", "after"), 1):
            ph = d.get(key, {}) or {}
            new = (prev_step < k <= step) if anim else False
            src = ph.get("image")
            if src:
                src = Path(src)
                if not src.is_absolute():
                    src = (doc["_script_dir"] / src)
                img = f'<img src="{src.resolve().as_uri()}">' if src.exists() else f'<div class="ph-empty">写真が見つかりません<br>{esc(src.name)}</div>'
            else:
                img = f'<div class="ph-empty">{esc(ph.get("placeholder", "ここに写真"))}</div>'
            h.append(f'<div class="ph {key}{" on" if k <= step else " off"}{" enter pop" if new else ""}" style="--i:{(k-prev_step-1)*3}">'
                     f'{img}<div class="tag">{esc(ph.get("tag", "ビフォー" if key == "before" else "アフター"))}</div>'
                     f'<div class="cap">{esc(ph.get("caption",""))}</div></div>')
        h.append('</div>')
    else:
        raise SystemExit(f"未対応の layout: {L}")
    return "\n".join(h)

def render_html(doc: dict, sc: Scene, step: int, mark: int | None, chapter_idx: int, anim: bool = False, prev_step: int = 0,
                faces: dict | None = None, talking: str | None = None, variant: str = "closed") -> str:
    kind = doc["kind"]
    w, hgt = SIZES[kind]
    tpl = TEMPLATE.read_text(encoding="utf-8")
    chap = f"{chapter_idx}/{doc['_chapters']}" if doc["_chapters"] and chapter_idx else ""
    return (tpl.replace("{{W}}", str(w)).replace("{{H}}", str(hgt))
            .replace("{{KIND}}", kind)
            .replace("{{FONT}}", doc.get("font", default_font()))
            .replace("{{QUESTION}}", esc(doc.get("question", "")))
            .replace("{{CHAPTER}}", chap)
            .replace("{{DISCLAIMER}}", esc(doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です")))
            .replace("{{BODY}}", render_body(doc, sc, step, mark, anim, prev_step, faces, talking, variant)))

OVERLAY_TPL = """<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:{{W}}px;height:{{H}}px;background:transparent;overflow:hidden;font-family:"{{FONT}}","Noto Sans JP","BIZ UDPGothic","Meiryo","IPAPGothic",sans-serif;font-feature-settings:"palt"}
.q{position:absolute;left:{{PAD}}px;top:36px;font-size:36px;font-weight:900;color:#1F2A44;background:#fff;border:4px solid #1F2A44;border-radius:999px;padding:12px 34px;max-width:78%;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 5px 0 rgba(31,42,68,.16)}
.hl{position:absolute;left:0;right:0;top:150px;text-align:center;font-size:92px;font-weight:900;color:#FF7A1A;line-height:1.2;
  -webkit-text-stroke:2px #fff;paint-order:stroke fill;text-shadow:0 0 0 #fff,-4px -4px 0 #fff,4px -4px 0 #fff,-4px 4px 0 #fff,4px 4px 0 #fff,0 10px 0 rgba(31,42,68,.25)}
.hl.enter{animation:pop .55s cubic-bezier(.22,.9,.3,1) both}
@keyframes pop{0%{opacity:0;transform:scale(.5)}55%{opacity:1;transform:scale(1.1)}78%{transform:scale(.96)}100%{opacity:1;transform:none}}
.foot{position:absolute;right:{{PAD}}px;bottom:{{FOOT}}px;font-size:25px;color:#fff;text-shadow:0 0 6px rgba(0,0,0,.7),0 0 2px rgba(0,0,0,.9);letter-spacing:.02em}
html[data-kind="short"] .foot{right:auto;left:0;width:100%;text-align:center}
</style></head><body data-kind="{{KIND}}"><div class="q">問い：{{QUESTION}}</div>{{HL}}<div class="foot">{{DISCLAIMER}}</div>
<script>window.__seek=function(ms){document.getAnimations().forEach(a=>{a.pause();a.currentTime=ms;});};</script></body></html>"""

def render_overlay_html(doc: dict, headline: str | None, anim: bool) -> str:
    """映像クリップに重ねる透明な層（問いのピル・大テロップ・注記）"""
    kind = doc["kind"]; w, hgt = SIZES[kind]
    hl = f'<div class="hl{" enter" if anim else ""}">{esc(headline)}</div>' if headline else ""
    return (OVERLAY_TPL.replace("{{W}}", str(w)).replace("{{H}}", str(hgt)).replace("{{KIND}}", kind)
            .replace("{{FONT}}", doc.get("font", default_font())).replace("{{PAD}}", "96" if kind == "long" else "64")
            .replace("{{FOOT}}", str(230 + 12) if kind == "long" else "90")
            .replace("{{QUESTION}}", esc(doc.get("question", ""))).replace("{{HL}}", hl)
            .replace("{{DISCLAIMER}}", esc(doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です"))))

def extract_clip_frames(src: Path, out_prefix: Path, size: tuple[int, int], nframes: int, fit: str = "cover") -> list[Path]:
    """映像クリップから FPS でコマを取り出す（足りないぶんは最後のコマを繰り返す）"""
    w, h = size
    if fit == "contain":
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x1F2A44,fps={FPS}"
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS}"
    last = out_prefix.parent / f"{out_prefix.name}_{nframes:05d}.png"
    if not last.exists():
        run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-frames:v", str(nframes), "-start_number", "1",
             str(out_prefix.parent / f"{out_prefix.name}_%05d.png")])
    frames = sorted(out_prefix.parent.glob(f"{out_prefix.name}_[0-9]*.png"))
    if not frames:
        raise SystemExit(f"クリップからコマを取り出せません: {src}")
    while len(frames) < nframes:
        frames.append(frames[-1])
    return frames[:nframes]

def render_png(chrome: str, html: str, out_png: Path, size: tuple[int, int]) -> Path:
    key = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
    out = out_png.with_name(f"{out_png.stem}_{key}.png")
    if out.exists():
        return out
    html_path = out.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={size[0]},{size[1] + 240}",   # headless の窓は上部が削れるので縦に余裕
         "--virtual-time-budget=2000", f"--screenshot={out}", html_path.resolve().as_uri() + "?static"])
    im = Image.open(out)
    if im.size != size:  # 余った下を切って寸法を揃える（引き伸ばさない）
        im = im.convert("RGB").crop((0, 0, size[0], size[1]))
        im.save(out)
    return out

def render_png_transparent(chrome: str, html: str, out_png: Path, size: tuple[int, int]) -> Path:
    """背景が透明な層を Chrome で撮る（動きなしモード用）"""
    if out_png.exists():
        return out_png
    html_path = out_png.with_suffix(".html"); html_path.write_text(html, encoding="utf-8")
    run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
         "--force-device-scale-factor=1", f"--window-size={size[0]},{size[1] + 240}", "--virtual-time-budget=2000",
         f"--screenshot={out_png}", html_path.resolve().as_uri() + "?static"])
    im = Image.open(out_png).convert("RGBA")
    if im.size != size:
        im = im.crop((0, 0, size[0], size[1])); im.save(out_png)
    return out_png

def mouth_segments(start: float, end: float, speech: float, t0: float) -> list[tuple[str, float]]:
    """物語シーンの口パク・まばたきの並び。start〜end（台詞内の相対秒）を (変種, 秒) の列にする。
    speech 秒までは MOUTH_STEP ごとに開/閉、その後は閉じて BLINK_EVERY ごとにまばたき。t0 は動画全体での開始秒（まばたきの位相用）"""
    segs: list[tuple[str, float]] = []
    a = start
    while a < end - 1e-6:
        if a < speech:
            v = "open" if int(a / MOUTH_STEP) % 2 == 0 else "closed"
            b = min(end, speech, (int(a / MOUTH_STEP) + 1) * MOUTH_STEP)
        else:
            ph = (t0 + a) % BLINK_EVERY
            if ph < BLINK_LEN:
                v = "blink"; b = min(end, a + (BLINK_LEN - ph))
            else:
                v = "closed"; b = min(end, a + (BLINK_EVERY - ph))
        if b <= a: b = a + 0.01
        if segs and segs[-1][0] == v:
            segs[-1] = (v, segs[-1][1] + (b - a))
        else:
            segs.append((v, b - a))
        a = b
    return segs

def thumb_char(th: dict) -> str:
    """サムネのキャラ。thumbnail の char（ぽん太/コツさん）・face（surprised など）・act（ポーズ）で指定。既定はコツさんの喜び"""
    ch = characters.CHARACTERS.get(str(th.get("char", "コツさん")), characters.CHARACTERS["コツさん"])
    face = str(th.get("face", "happy")); act = th.get("act")
    try:
        body = ch["svg"](face, False, False, act) if act else ch["svg"](face)
    except TypeError:      # ポーズ未対応の characters.py
        body = ch["svg"](face)
    return characters.svg_document(body, 300)

def render_thumbnail(chrome: str, doc: dict, out_dir: Path) -> Path | None:
    th = doc.get("thumbnail")
    if not th:
        return None
    size = (1280, 720) if doc["kind"] == "long" else (1080, 1920)
    tpl = (HERE / "templates" / "thumb.html").read_text(encoding="utf-8")
    html = (tpl.replace("{{W}}", str(size[0])).replace("{{H}}", str(size[1]))
            .replace("{{FONT}}", doc.get("font", default_font()))
            .replace("{{BIG}}", esc(th.get("big", ""))).replace("{{SUB}}", esc(th.get("sub", "")))
            .replace("{{TAG}}", esc(th.get("tag", "小規模な大家")))
            .replace("{{CHAR}}", thumb_char(th)))
    return render_png(chrome, html, out_dir / "thumb.png", size)

# ---------------------------------------------------------------- 話者キャラクター
def render_characters(chrome: str, doc: dict, work: Path, px: int) -> dict[str, dict[str, Path]]:
    """話者ごとに キャラ × 表情 × 口 の PNG を描く。戻り値 {話者: {"idle":…, "blink":…, "happy_open":…}}"""
    out: dict[str, dict[str, Path]] = {}
    for key, sp in doc["speakers"].items():
        ch = characters.CHARACTERS.get(sp.get("char", ""), None)
        if ch is None:
            continue
        variants = {"idle": ("normal", False, False, True), "blink": ("normal", False, True, True)}
        for e in characters.EXPRS:
            variants[f"{e}_closed"] = (e, False, False, False)
            variants[f"{e}_open"] = (e, True, False, False)
        out[key] = {}
        for vname, (expr, mouth, blink, dim) in variants.items():
            png = work / f"ch_{key}_{vname}.png"
            if not png.exists():
                svg = characters.svg_document(ch["svg"](expr, mouth, blink), 300)
                html = ('<!doctype html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0}html,body{width:300px;height:300px;background:transparent;overflow:hidden}</style></head>'
                        f'<body>{svg}</body></html>')
                hp = png.with_suffix(".html"); hp.write_text(html, encoding="utf-8")
                run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
                     "--window-size=300,520", f"--screenshot={png}", hp.resolve().as_uri()])
                im = Image.open(png).convert("RGBA").crop((0, 0, 300, 300))
                if dim:
                    a = im.split()[3].point(lambda v: int(v * 0.6)); im.putalpha(a)
                im.resize((px, px), Image.LANCZOS).save(png)
            out[key][vname] = png
    return out

# ---------------------------------------------------------------- 音声
def wav_duration(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()

def write_silence(p: Path, sec: float, sr=SR):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sec * sr))

_SPEAKERS_CACHE: dict | None = None
def voicevox_style_id(speaker: str, style: str) -> int:
    """話者名＋スタイル名 → id。エンジンの /speakers から引く"""
    global _SPEAKERS_CACHE
    if _SPEAKERS_CACHE is None:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/speakers", timeout=30) as r:
            _SPEAKERS_CACHE = json.loads(r.read())
    for sp in _SPEAKERS_CACHE:
        if sp["name"] == speaker:
            for st in sp["styles"]:
                if st["name"] == style:
                    return int(st["id"])
            avail = ", ".join(st["name"] for st in sp["styles"])
            raise SystemExit(f"話者「{speaker}」にスタイル「{style}」はありません。あるのは: {avail}")
    raise SystemExit(f"話者「{speaker}」が VOICEVOX にありません")

def tts_voicevox(text: str, speaker_id: int, out: Path, speed: float = 1.0, intonation: float = 1.0, pitch: float = 0.0):
    q = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": speaker_id}), method="POST")
    with urllib.request.urlopen(q, timeout=60) as r:
        query = json.loads(r.read())
    query["speedScale"] = speed
    query["intonationScale"] = intonation
    query["pitchScale"] = pitch
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.05
    query["outputSamplingRate"] = SR
    query["outputStereo"] = False
    s = urllib.request.Request(f"{VOICEVOX_URL}/synthesis?" + urllib.parse.urlencode({"speaker": speaker_id}),
                               data=json.dumps(query).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(s, timeout=120) as r:
        out.write_bytes(r.read())

def voice_key(doc: dict, ln: Line, mode: str) -> str:
    """音声キャッシュの鍵（台詞・話者・スタイル・話速・抑揚が同じなら同じ）"""
    sp = doc["speakers"][ln.sp]; v = doc["voice"]
    sig = "|".join(str(x) for x in (mode, ln.text, sp.get("speaker"), sp.get("voicevox_id"), ln.st or sp.get("style"),
                                      ln.speed or v["speed"], ln.intonation or v["intonation"], v["pitch"]))
    return hashlib.md5(sig.encode("utf-8")).hexdigest()[:8]

def tts_line(mode: str, doc: dict, ln: Line, out: Path):
    if out.exists():
        return
    if mode == "stub":
        n = len(re.sub(r"[、。！？!?,.\s]", "", ln.text))
        write_silence(out, max(0.8, n * STUB_SEC_PER_CHAR + 0.25))
        return
    sp = doc["speakers"][ln.sp]
    if "voicevox_id" in sp and not ln.st:
        sid = int(sp["voicevox_id"])
    else:
        sid = voicevox_style_id(sp.get("speaker", ""), ln.st or sp.get("style", "ノーマル"))
    v = doc["voice"]
    tts_voicevox(ln.text, sid, out, float(ln.speed or v["speed"]), float(ln.intonation or v["intonation"]), float(v["pitch"]))

def concat_wavs(parts: list[tuple[Path, float]], out: Path):
    """parts = [(wav, 後ろに足す無音秒)] を 1 本の wav に"""
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        for p, pause in parts:
            with wave.open(str(p), "rb") as r:
                assert r.getframerate() == SR and r.getnchannels() == 1, f"{p}: 24kHz mono が必要"
                w.writeframes(r.readframes(r.getnframes()))
            w.writeframes(b"\x00\x00" * int(pause * SR))

# ---------------------------------------------------------------- 字幕
def ass_color(hex6: str) -> str:
    h = hex6.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"

def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs//360000}:{(cs//6000)%60:02d}:{(cs//100)%60:02d}.{cs%100:02d}"

def wrap_jp(text: str, limit: int) -> str:
    """limit 文字を超える文に改行を入れる。行数を決めてから均等に割り、句読点の直後を優先して切る。
    libass は空白のない日本語を折り返さないので自前で行う。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    punct = "、。！？,.」）)"
    n = math.ceil(len(text) / limit)
    out, cur = [], text
    for k in range(n - 1, 0, -1):          # 残り k 行ぶんを後ろに残す
        target = round(len(cur) / (k + 1))
        best = None
        for i in range(max(2, target - 6), min(len(cur) - 2, target + 6) + 1):
            if cur[i - 1] in punct and i <= limit and (len(cur) - i) <= limit * k:
                if best is None or abs(i - target) < abs(best - target):
                    best = i
        cut = best if best is not None else min(max(target, len(cur) - limit * k), limit)
        out.append(cur[:cut]); cur = cur[cut:]
    out.append(cur)
    return "\\N".join(x for x in out if x)

def write_ass(doc: dict, events: list[tuple[float, float, str, str]], out: Path):
    w, h = SIZES[doc["kind"]]
    font = doc.get("font", default_font())
    short = doc["kind"] == "short"
    fs = 66 if short else 54
    mv = 560 if short else 40   # 下端からの距離（ショートは中央寄り）
    ml = 70 if short else 270
    styles = []
    for key, sp in doc["speakers"].items():
        styles.append(f"Style: {key},{font},{fs},&H00FFFFFF,&H00FFFFFF,&H00141414,&H38141414,-1,0,0,0,100,100,0,0,4,0,18,2,{ml},{ml},{mv},1")
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for st, en, sp, text in events:
        col = ass_color(doc["speakers"][sp]["color"])
        text = wrap_jp(text.replace("★", "").strip(), 13 if short else 24)
        text = re.sub(r"([0-9０-９,，.]+(?:万円|億円|円|戸|年目|年|か月|ヶ月|日|回|％|パーセント|人|棟|分|倍)?)",
                      r"{\\c&H05B7F2&}\1{\\c&H00FFFFFF&}", text)
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},{sp},,0,0,0,,{{\\fscx90\\fscy90\\t(0,110,\\fscx100\\fscy100)}}{{\\c{col}}}▌{{\\c&H00FFFFFF&}}{text}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- 結合
def motion_available() -> bool:
    if os.environ.get("MOTION", "1") == "0":
        return False
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, cwd=HERE)
    return r.returncode == 0

def build(script: Path, out_dir: Path, tts_mode: str, bgm: Path | None, bgm_db: float):
    doc = load_script(script)
    kind = doc["kind"]; size = SIZES[kind]
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"; (work / "slides").mkdir(parents=True, exist_ok=True); (work / "voice").mkdir(exist_ok=True)
    chrome = find_chrome()
    motion = motion_available()
    print(f"[1/5] 台詞と音声  ({kind} {size[0]}x{size[1]}  動き: {'あり(Playwright)' if motion else 'なし(静止画)'})")

    # ---- 第 1 段: 音声を作りながら、画の「状態」と表示秒を並べる
    plan: list[dict] = []        # {html, key, nframes, dur, scene, layout}
    se_events: list[tuple[float, str]] = []
    speak: dict[str, dict[str, list[tuple[float, float]]]] = {k: {} for k in doc["speakers"]}
    holds: list[tuple[str, float]] = []   # (状態キー, 同じ画が続いた秒数) QA 用
    audio_parts: list[tuple[Path, float]] = []
    sub_events: list[tuple[float, float, str, str]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    chapter_idx = 0
    last_key = None
    hide_iv: list[tuple[float, float]] = []    # 物語シーン・映像クリップの間は隅のキャラを隠す
    amb_events: list[tuple[float, float, str]] = []   # (開始, 終了, 環境音名)
    clip_scenes: dict[str, dict] = {}          # clip 場面 → {src, start, dur}
    for sc in doc["_scenes"]:
        if sc.layout == "chapter":
            chapter_idx = sc.chapter_no
            chapters.append((t, f"{chapter_idx}. " + sc.data.get("heading", "")))
        elif sc.layout == "ending":
            chapters.append((t, "今日の一歩"))
        if sc.layout == "clip":
            src = sc.data.get("file")
            p = (doc["_script_dir"] / src) if src and not Path(src).is_absolute() else (Path(src) if src else None)
            if p is None or not p.exists():
                sc.data["_missing"] = Path(src).name if src else "(file が未指定)"
            clip_scenes[sc.id] = {"src": p if p and p.exists() else None, "start": t, "dur": 0.0}
        scene_start = t
        lines = sc.lines or [Line(sp=next(iter(doc["speakers"])), text="", step=sc.steps, pause=0.0)]
        for li, ln in enumerate(lines):
            key = (sc.id, ln.step, ln.mark)
            changed = key != last_key
            story = sc.layout in ("scene", "clip")
            if sc.layout == "scene":
                faces, talking = scene_faces(doc, sc, ln)
                fkey = (sc.id, ln.step, ln.mark, tuple(sorted(faces.items())), talking)
                redraw = changed or (plan and plan[-1].get("fkey") != fkey)
                ps = ln.prev_step if changed else ln.step
                variants = {v: render_html(doc, sc, ln.step, ln.mark, chapter_idx, anim=changed, prev_step=ps, faces=faces, talking=talking, variant=v)
                            for v in ("closed", "open", "blink")}
                html = variants["closed"]
            else:
                variants = None; fkey = None; redraw = changed
                html = render_html(doc, sc, ln.step, ln.mark, chapter_idx, anim=changed, prev_step=ln.prev_step if changed else ln.step)
            if ln.text:
                wav = work / "voice" / f"{sc.id}_{li:02d}_{voice_key(doc, ln, tts_mode)}.wav"   # 台詞や声が変わればファイル名も変わる
                tts_line(tts_mode, doc, ln, wav)
                dur = wav_duration(wav)
            else:
                wav = work / "voice" / f"{sc.id}_sil.wav"; write_silence(wav, 2.0); dur = 2.0
            last = li == len(lines) - 1
            pause = (PAUSE_CHAPTER if sc.layout == "chapter" else PAUSE_SCENE) if last else ln.pause
            if ln.text:
                sub_events.append((t, t + dur + min(pause, 0.3), ln.sp, ln.text))
                expr = ln.face or characters.guess_expr(ln.st, ln.text)
                if not story:
                    speak[ln.sp].setdefault(expr, []).append((t, t + dur))
            if story:
                hide_iv.append((t, t + dur + pause))
            same_run = 0 if changed else (plan[-1]["same_run"] + 1 if plan else 0)
            # ジャンプカットのズームで台詞ごとに画が変わるので、1 台詞の長さだけを「同じ画」として数える
            holds.append((f"{sc.id}/{ln.step}/{ln.mark}", dur + pause))
            if changed and sc.layout == "scene":
                d = sc.data
                names: list[str] = list(d.get("sfx") or []) if li == 0 else []
                if li == 0 and not d.get("sfx"):
                    if d.get("bg") in SCENE_SFX_AUTO["bg"]: names.append(SCENE_SFX_AUTO["bg"][d["bg"]])
                    for c in d.get("chars") or []:
                        if c.get("act") in SCENE_SFX_AUTO["act"]: names.append(SCENE_SFX_AUTO["act"][c["act"]])
                for p in d.get("props") or []:
                    if ln.prev_step < int(p.get("step", 1)) <= ln.step and p.get("kind") in SCENE_SFX_AUTO["prop"]:
                        names.append(SCENE_SFX_AUTO["prop"][p["kind"]])
                for k, nm in enumerate(dict.fromkeys(names)):
                    se_events.append((t + 0.05 + k * 0.22, nm))
            elif changed:
                L = sc.layout
                newn = max(0, ln.step - ln.prev_step)
                if L == "chapter": se_events += [(t - 0.3, "riser"), (t + 0.05, "reveal")]
                elif L == "title": se_events.append((t + 0.05, "whoosh"))
                elif L == "ending": se_events.append((t + 0.1, "sparkle"))
                elif L == "counter":
                    cd = float(sc.data.get("dur", 2.0))
                    se_events.append((t - 0.2, "riser"))
                    se_events += [(t + 0.25 + k * 0.28, "coin") for k in range(int(cd / 0.28))]
                    se_events.append((t + cd + 0.1, "reveal" if sc.data.get("burst") else "sparkle"))
                elif L == "portfolio":
                    se_events += [(t + 0.1 + k * 0.12, "pop") for k in range(min(newn, 12))]
                    se_events.append((t + 0.3 + min(newn, 12) * 0.12, "coin"))
                    if ln.step >= sc.steps: se_events.append((t + 0.6 + min(newn, 12) * 0.12, "sparkle"))
                elif L in ("list", "flow", "bar", "timeline"):
                    items = sc.data.get("items") or sc.data.get("rows") or []
                    se_events.append((t + 0.05, "pop"))
                    se_events += [(t + 0.05 + (k + 1) * 0.24, "tick") for k in range(max(0, newn - 1))]
                    if L == "flow" and ln.step >= 1 and ln.step <= len(items) and isinstance(items[ln.step - 1], dict) and items[ln.step - 1].get("sum"):
                        se_events.append((t + 0.15, "reveal"))
                    if ln.mark: se_events.append((t + 0.3, "coin"))
                elif L == "clip":
                    se_events.append((t + 0.05, "whoosh"))
                else:
                    se_events.append((t + 0.05, "pop"))
            nframes = max(1, int(round(ANIM_SEC.get(sc.layout, 0.8) * FPS))) if (changed and motion) else 1
            pl = {"html": html, "key": key, "nframes": nframes, "dur": dur + pause, "scene": sc.id, "layout": sc.layout, "same_run": same_run,
                  "speech": dur if (ln.text and sc.layout == "scene") else 0.0, "variants": variants, "fkey": fkey, "redraw": redraw,
                  "t": t}
            if sc.layout == "clip":
                pl["clip_off"] = t - scene_start
                pl["headline"] = sc.data.get("headline")
            plan.append(pl)
            audio_parts.append((wav, pause)); t += dur + pause
            last_key = key
        if sc.layout == "clip":
            clip_scenes[sc.id]["dur"] = t - scene_start
        if sc.layout == "scene" and sc.data.get("ambience", True):
            amb = "rain" if sc.data.get("weather") == "rain" else SCENE_AMBIENCE.get(str(sc.data.get("bg", "")))
            if amb:
                amb_events.append((scene_start, t, amb))
    total = t
    print(f"      場面 {len(doc['_scenes'])} / 台詞 {len(sub_events)} / 予定尺 {total:.1f} 秒")

    print("[2/5] スライドをコマ撮り")
    jobs = []
    def want(html: str, nframes: int, tag: str, transparent: bool = False) -> Path:
        """この HTML を nframes 枚（1 なら最終状態 1 枚）撮る予約をして、ファイル名の接頭辞を返す"""
        h = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
        prefix = work / "slides" / f"{tag}_{h}"
        html_path = prefix.with_suffix(".html")
        if not html_path.exists():
            html_path.write_text(html, encoding="utf-8")
        if nframes <= 1:
            if not prefix.with_suffix(".png").exists():
                if motion:
                    jobs.append({"html": str(html_path), "out": str(prefix), "frames": 1, "transparent": transparent})
                elif transparent:
                    render_png_transparent(chrome, html, prefix.with_suffix(".png"), size)
                else:
                    render_png(chrome, html, prefix, size)
        else:
            lastf = prefix.parent / f"{prefix.name}_{nframes-1:04d}.png"
            if not lastf.exists():
                jobs.append({"html": str(html_path), "out": str(prefix), "frames": nframes, "fps": FPS, "transparent": transparent})
        return prefix
    for pl in plan:
        if pl["layout"] == "scene":
            n = pl["nframes"]
            pl["prefix"] = want(pl["variants"]["closed"], n, pl["scene"] + "_c")
            pl["prefix_open_anim"] = want(pl["variants"]["open"], n, pl["scene"] + "_o") if n > 1 else None
            pl["hold"] = {v: want(pl["variants"][v], 1, pl["scene"] + "_" + v[0]) for v in ("closed", "open", "blink")}
        elif pl["layout"] == "clip":
            pl["prefix"] = want(pl["html"], 1, pl["scene"])    # 映像が無いときの代わりの画
            cs = clip_scenes[pl["scene"]]
            if cs["src"] is not None:
                first = pl["clip_off"] < 1e-6
                pl["ov_anim"] = want(render_overlay_html(doc, pl.get("headline"), True), int(round(0.55 * FPS)), f"ov_{pl['scene']}", transparent=True) if (first and motion and pl.get("headline")) else None
                pl["ov"] = want(render_overlay_html(doc, pl.get("headline"), False), 1, f"ov_{pl['scene']}", transparent=True)
        else:
            pl["prefix"] = want(pl["html"], pl["nframes"], pl["scene"])
    if jobs:
        spec = work / "jobs.json"
        spec.write_text(json.dumps({"width": size[0], "height": size[1], "jobs": jobs}, ensure_ascii=False), encoding="utf-8")
        run(["node", str(RENDER_JS), str(spec)], cwd=HERE)
    print(f"      コマ {sum(j.get('frames',1) for j in jobs)} 枚を新規生成")
    # 映像クリップ: コマを取り出し、透明な層（問い・テロップ・注記）を重ねる
    for sid, cs in clip_scenes.items():
        if cs["src"] is None:
            continue
        (work / "clips").mkdir(exist_ok=True)
        n = int(math.ceil(cs["dur"] * FPS)) + 2
        tag = f"{sid}_{hashlib.md5(str(cs['src'].resolve()).encode()).hexdigest()[:8]}"
        raw = extract_clip_frames(cs["src"], work / "clips" / tag, size, n, str(next((p for p in plan if p["scene"] == sid), {}).get("fit", "cover")))
        pls = [p for p in plan if p["scene"] == sid]
        ov_static = Image.open(pls[0]["ov"].with_suffix(".png")).convert("RGBA")
        ov_anim = pls[0].get("ov_anim")
        comp: list[Path] = []
        for i, f in enumerate(raw):
            o = work / "clips" / f"{tag}_ov_{i:05d}.png"
            if not o.exists():
                ov = ov_static
                if ov_anim is not None and i < int(round(0.55 * FPS)):
                    ov = Image.open(ov_anim.parent / f"{ov_anim.name}_{i:04d}.png").convert("RGBA")
                Image.alpha_composite(Image.open(f).convert("RGBA"), ov).convert("RGB").save(o)
            comp.append(o)
        cs["frames"] = comp

    print("[3/5] 音声を 1 本に / 字幕 (ASS)")
    voice = work / "voice.wav"; concat_wavs(audio_parts, voice)
    write_ass(doc, sub_events, work / "subs.ass")
    se_track = np.zeros(int((total + 1) * SR))
    if doc.get("sfx", True):
        clips: dict[str, np.ndarray | None] = {}
        for at, name in se_events:
            if name not in clips:
                try:
                    clips[name] = audio_synth.sfx(name)
                except Exception:          # 音響部がまだ作っていない名前は鳴らさない
                    clips[name] = None; print(f"      注意: 効果音 {name} が無いので鳴らしません")
            c = clips[name]
            if c is None: continue
            st = int(max(0.0, at) * SR)
            if st + len(c) < len(se_track): se_track[st:st + len(c)] += c
    audio_synth.write_wav(work / "se.wav", se_track * 0.6)
    avatars = render_characters(chrome, doc, work, 230 if kind == "long" else 200) if doc.get("avatars", True) else None
    # 品質部の指摘: 同じ画が長く続く場面、写真の無い photo を警告
    warnings = []
    for key, sec in holds:
        if sec > 8.0: warnings.append(f"同じ画が {sec:.1f} 秒続く: {key}")
    for sc in doc["_scenes"]:
        if sc.layout == "photo" and not ((sc.data.get("before") or {}).get("image") and (sc.data.get("after") or {}).get("image")):
            warnings.append(f"photo に写真が入っていない（枠だけ）: {sc.id}")
        if sc.layout == "clip" and sc.data.get("_missing"):
            warnings.append(f"clip の映像ファイルが無い（枠だけ）: {sc.id} {sc.data['_missing']}")
        if sc.layout == "scene":
            for p in sc.data.get("props") or []:
                if p.get("kind") == "photo" and not (p.get("image") and (doc["_script_dir"] / str(p["image"])).exists()):
                    warnings.append(f"scene の写真が無い（枠だけ）: {sc.id} {p.get('image', '')}")
    for wmsg in warnings: print("      警告:", wmsg)

    print("[4/5] 画の並び（場面の切り替えはクロスフェード）")
    frames_txt: list[tuple[Path, float]] = []
    prev_png: Path | None = None; prev_scene = None
    def zoomed(png: Path, z: float) -> Path:
        """ジャンプカット風に z 倍に寄った画（キャッシュ）"""
        if z == 1.0:
            return png
        zf = work / "slides" / f"z_{hashlib.md5((str(png)+str(z)).encode()).hexdigest()[:10]}.png"
        if not zf.exists():
            im = Image.open(png).convert("RGB"); W, H = im.size
            cw, chh = int(W / z), int(H / z)
            im.crop(((W - cw) // 2, int((H - chh) * 0.42), (W - cw) // 2 + cw, int((H - chh) * 0.42) + chh)).resize((W, H), Image.LANCZOS).save(zf)
        return zf
    for pl in plan:
        prefix: Path = pl["prefix"]
        disp: list[tuple[Path, float]] = []     # この台詞で表示する (画, 秒) の列
        if pl["layout"] == "scene":
            z = JUMP_ZOOMS[pl["same_run"] % len(JUMP_ZOOMS)] if pl["same_run"] > 0 else 1.0
            hold = {v: zoomed(p.with_suffix(".png"), z) for v, p in pl["hold"].items()}
            n_anim = pl["nframes"] if pl["nframes"] > 1 else 0
            n_anim = min(n_anim, max(0, int(pl["dur"] * FPS) - 1))
            po = pl.get("prefix_open_anim")
            for i in range(n_anim):
                ti = i / FPS
                use_open = ti < pl["speech"] and (int(ti / MOUTH_STEP) % 2 == 0) and po is not None
                pf = (po if use_open else prefix)
                disp.append((pf.parent / f"{pf.name}_{i:04d}.png", 1 / FPS))
            for v, sec in mouth_segments(n_anim / FPS, pl["dur"], pl["speech"], pl["t"]):
                disp.append((hold[v], sec))
        elif pl["layout"] == "clip" and clip_scenes[pl["scene"]].get("frames"):
            fr = clip_scenes[pl["scene"]]["frames"]
            off = int(round(pl["clip_off"] * FPS)); n = max(1, int(pl["dur"] * FPS))
            for i in range(n):
                disp.append((fr[min(off + i, len(fr) - 1)], 1 / FPS))
            disp[-1] = (disp[-1][0], disp[-1][1] + (pl["dur"] - n / FPS))
        else:
            if pl["nframes"] == 1:
                seq = [prefix.with_suffix(".png")]
            else:
                seq = [prefix.parent / f"{prefix.name}_{i:04d}.png" for i in range(pl["nframes"])]
            remain = pl["dur"]
            if pl["same_run"] > 0 and len(seq) == 1:
                seq = [zoomed(seq[0], JUMP_ZOOMS[pl["same_run"] % len(JUMP_ZOOMS)])]
            if len(seq) > 1:
                use = seq[:max(1, min(len(seq), int(remain * FPS) - 1))]
                for f in use[:-1]:
                    disp.append((f, 1 / FPS)); remain -= 1 / FPS
                seq = [use[-1]]
            disp.append((seq[0], max(0.04, remain)))
        seq = [disp[0][0]]
        if prev_png is not None and pl["scene"] != prev_scene:   # 場面が変わる: クロスフェード／章扉はワイプ
            a = Image.open(prev_png).convert("RGB"); b = Image.open(seq[0]).convert("RGB")
            wipe = pl["layout"] == "chapter"
            nxf = 10 if wipe else XFADE_FRAMES
            for k in range(1, nxf + 1):
                f = work / "slides" / f"x_{hashlib.md5((str(prev_png)+str(seq[0])+str(k)+str(wipe)).encode()).hexdigest()[:10]}.png"
                if not f.exists():
                    if wipe:
                        W, H = a.size; pgs = k / nxf; edge = int((W + H * 0.5) * pgs) - int(H * 0.25)
                        mask = Image.new("L", (W, H), 0); dr = ImageDraw.Draw(mask)
                        dr.polygon([(0, 0), (edge, 0), (edge - H * 0.5, H), (0, H)], fill=255)
                        im = Image.composite(b, a, mask)
                        band = Image.new("L", (W, H), 0); dr2 = ImageDraw.Draw(band)
                        dr2.polygon([(edge, 0), (edge + 70, 0), (edge + 70 - H * 0.5, H), (edge - H * 0.5, H)], fill=255)
                        im = Image.composite(Image.new("RGB", (W, H), (255, 122, 26)), im, band)
                        im.save(f)
                    else:
                        Image.blend(a, b, k / (nxf + 1)).save(f)
                frames_txt.append((f, 1 / FPS))
        for f, sec in disp:
            if frames_txt and frames_txt[-1][0] == f:
                frames_txt[-1] = (f, frames_txt[-1][1] + sec)
            else:
                frames_txt.append((f, sec))
        prev_png = disp[-1][0]; prev_scene = pl["scene"]
    concat = work / "frames.txt"
    with concat.open("w", encoding="utf-8") as f:
        for p, d in frames_txt:
            f.write(f"file '{p.resolve().as_posix()}'\nduration {d:.4f}\n")
        f.write(f"file '{frames_txt[-1][0].resolve().as_posix()}'\n")

    print("[5/5] ffmpeg で結合（ゆっくりした揺れ・進捗バー・字幕・BGM・ラウドネス -14 LUFS）")
    w, h = size
    sw, sh = int(w * 1.04), int(h * 1.04)
    dx, dy = (sw - w) // 2, (sh - h) // 2
    accent = doc.get("accent", "#C8321E").lstrip("#")
    vf = (f"scale={sw}:{sh}:flags=lanczos,"
          f"crop={w}:{h}:x='{dx}+{dx*0.8:.0f}*sin(t/11)':y='{dy}+{dy*0.8:.0f}*sin(t/17)',"
          f"drawbox=x=0:y=ih-8:w='iw*t/{total:.2f}':h=8:color=0x{accent}@0.9:t=fill,"
          f"subtitles=subs.ass")
    if avatars:
        px = 230 if kind == "long" else 200
        pos = {}
        keys = [k for k in doc["speakers"].keys() if k in avatars]
        for i, k in enumerate(keys[:2]):
            if kind == "long":
                pos[k] = (20 if i == 0 else w - px - 20, h - px - 10)
            else:
                pos[k] = (50 if i == 0 else w - px - 50, h - 560 + 20)
        chain = "[v0]"
        parts = [vf + "[v0]"]
        n = 0
        # 物語シーン・映像クリップの間は隅のキャラを出さない（隣り合う区間はまとめる）
        hide: list[list[float]] = []
        for a, b in sorted(hide_iv):
            if hide and a <= hide[-1][1] + 0.05: hide[-1][1] = max(hide[-1][1], b)
            else: hide.append([a, b])
        shown = "*not(" + "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in hide) + ")" if hide else ""
        def ov(img: Path, x, y, enable: str | None = None, bob=False):
            nonlocal chain, n
            yexpr = f"'{y}+6*sin(2*PI*2.4*t)'" if bob else str(y)
            en_expr = (f"({enable}){shown}" if enable else (shown[1:] if shown else None))
            en = f":enable='{en_expr}'" if en_expr else ""
            parts.append(f"movie={img.name}[m{n}];{chain}[m{n}]overlay=x={x}:y={yexpr}{en}[v{n+1}]"); chain = f"[v{n+1}]"; n += 1
        for ki, k in enumerate(keys[:2]):
            x, y = pos[k]
            ov(avatars[k]["idle"], x, y)
            all_iv = [iv for ivs in speak.get(k, {}).values() for iv in ivs]
            if all_iv:
                en_all = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in sorted(all_iv))
                # まばたき（話していないとき、3.7 秒ごとに 0.13 秒）
                ov(avatars[k]["blink"], x, y, enable=f"not({en_all})*lt(mod(t+{ki*1.3:.1f},3.7),0.13)")
                for expr, ivs in speak[k].items():
                    en = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in ivs)
                    ov(avatars[k][f"{expr}_closed"], x, y, enable=f"({en})*gte(mod(t,0.22),0.11)", bob=True)
                    ov(avatars[k][f"{expr}_open"], x, y, enable=f"({en})*lt(mod(t,0.22),0.11)", bob=True)
            else:
                ov(avatars[k]["blink"], x, y, enable=f"lt(mod(t+{ki*1.3:.1f},3.7),0.13)")
        parts.append(f"{chain}format=yuv420p[vout]")
        vfilter = ";".join(parts); vmap = "[vout]"
    else:
        vfilter = vf + ",format=yuv420p[vout]"; vmap = "[vout]"
    # BGM: 指定が無ければ自前合成
    if not (bgm and Path(bgm).exists()):
        bgm = work / "bgm_synth.wav"
        if not bgm.exists():
            audio_synth.write_wav(bgm, audio_synth.bgm(total + 4))
    # 環境音（物語シーンの背景ごと。0.4 秒でフェード）
    amb_track = np.zeros(int((total + 1) * SR))
    amb_fn = getattr(audio_synth, "ambience", None)
    if amb_events and amb_fn is not None:
        for i, (a, b, name) in enumerate(amb_events):
            sec = b - a
            try:
                clip = np.asarray(amb_fn(name, sec + 0.5, seed=i + 1), dtype=float)[: int((sec + 0.4) * SR)]
            except Exception as e:   # 未対応の名前など
                print(f"      注意: 環境音 {name} を作れません ({e})"); continue
            fade = int(0.4 * SR); env = np.ones(len(clip))
            env[:fade] = np.linspace(0, 1, fade); env[-fade:] = np.linspace(1, 0, fade)
            st = int(a * SR); en = min(len(amb_track), st + len(clip))
            amb_track[st:en] += (clip * env)[: en - st]
    audio_synth.write_wav(work / "amb.wav", np.clip(amb_track, -1, 1))
    mix = work / "mix.wav"
    run(["ffmpeg", "-y", "-i", str(voice), "-stream_loop", "-1", "-i", str(Path(bgm).resolve()), "-i", str(work / "se.wav"), "-i", str(work / "amb.wav"),
         "-filter_complex",
         f"[1:a]aformat=sample_rates={SR}:channel_layouts=mono,volume={bgm_db}dB,atrim=0:{total:.3f},afade=t=out:st={max(0,total-2):.2f}:d=2[bg];"
         f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=600:makeup=1[duck];"
         f"[2:a]aformat=sample_rates={SR}:channel_layouts=mono,volume={doc.get('sfx_db', -10)}dB[se];"
         f"[3:a]aformat=sample_rates={SR}:channel_layouts=mono,volume={doc.get('amb_db', 0)}dB[amb];"
         f"[0:a][duck][se][amb]amix=inputs=4:duration=first:normalize=0[mix]",
         "-map", "[mix]", "-ac", "1", str(mix)], cwd=work)
    meas = subprocess.run(["ffmpeg", "-i", str(mix), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1])
    final_a = work / "final.wav"
    if tts_mode == "stub" or float(m["input_i"]) < -70:   # スタブ（無音）の場合は正規化しない
        shutil.copy(mix, final_a)
    else:
        run(["ffmpeg", "-y", "-i", str(mix), "-af",
             f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000",
             str(final_a)], cwd=work)
    out_mp4 = out_dir / f"{doc['id']}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "frames.txt", "-i", str(final_a),
         "-filter_complex", vfilter, "-map", vmap, "-map", "1:a", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out_mp4.resolve())], cwd=work)

    thumb = render_thumbnail(chrome, doc, out_dir)
    write_publish(doc, chapters, total, out_dir, thumb)
    print(f"完成: {out_mp4}")
    qa(out_mp4, kind, stub=(tts_mode == "stub"), out_json=out_dir / "qa.json", warnings=warnings)

# ---------------------------------------------------------------- 公開用メモ
def fmt_ts(t: float) -> str:
    return f"{int(t)//60}:{int(t)%60:02d}"

def write_publish(doc: dict, chapters: list[tuple[float, str]], total: float, out_dir: Path, thumb: Path | None):
    pub = doc.get("publish", {})
    desc = [pub.get("lead", doc.get("title", "")), ""]
    if doc.get("note_url"):
        desc += [f"▼この回の元になった記事（note）", doc["note_url"], ""]
    if chapters and doc["kind"] == "long":
        desc.append("▼目次")
        desc.append("0:00 はじめに")
        desc += [f"{fmt_ts(t)} {h}" for t, h in chapters]
        desc.append("")
    voices = "、".join(f"VOICEVOX:{sp.get('speaker', sp.get('name',''))}" for sp in doc["speakers"].values())
    desc += [doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です。"),
             "個別のご相談・物件のご紹介は承っておりません。",
             f"音声は合成音声です。{voices}"]
    if doc.get("bgm_credit"):
        desc.append(f"BGM: {doc['bgm_credit']}")
    tags = pub.get("tags", ["不動産投資", "大家", "一棟目", "小規模大家", "不動産", "物件探し"])
    md = [f"# 公開用メモ  {doc['id']}", "",
          f"- 種別: {'長尺' if doc['kind']=='long' else 'ショート'}  尺 {fmt_ts(total)}",
          f"- タイトル: {doc.get('title','')}",
          f"- サムネ: {thumb.name if thumb else '（thumbnail 未設定）'}",
          f"- タグ: {', '.join(tags)}"]
    if doc["kind"] == "long":
        if total >= 480:
            cands = [(t, h) for t, h in chapters if 120 <= t <= total - 90 and not h.startswith("今日の一歩")]
            md.append("- ミッドロール広告（手動で置く場所。章扉の直前＝話の切れ目）: " + ("、".join(fmt_ts(t) for t, _ in cands) if cands else "候補なし"))
        else:
            md.append(f"- ミッドロール広告: 尺が 8 分未満（{fmt_ts(total)}）なので入らない。台本を足すか、そのまま公開")
    md += ["", "## 説明文（そのまま貼る）", "```", *desc, "```"]
    (out_dir / "publish.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- 検査
def qa(mp4: Path, kind: str | None = None, stub=False, out_json: Path | None = None, warnings: list[str] | None = None) -> bool:
    pr = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
              "-of", "json", str(mp4)])
    info = json.loads(pr.stdout)
    w, h = info["streams"][0]["width"], info["streams"][0]["height"]
    dur = float(info["format"]["duration"])
    kind = kind or ("short" if h > w else "long")
    lo = subprocess.run(["ffmpeg", "-i", str(mp4), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    mI = re.findall(r"I:\s+(-?[\d.]+) LUFS", lo)
    lufs = float(mI[-1]) if mI else None
    sd = subprocess.run(["ffmpeg", "-i", str(mp4), "-af", "silencedetect=noise=-40dB:d=0.9", "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    gaps = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", sd)]
    max_gap = max(gaps) if gaps else 0.0
    checks = {
        "解像度": ((w, h) == SIZES[kind], f"{w}x{h}（期待 {SIZES[kind][0]}x{SIZES[kind][1]}）"),
        "尺": ((240 <= dur <= 600) if kind == "long" else (20 <= dur <= 59.5), f"{dur:.1f} 秒（長尺 4〜10 分 / ショート 20〜59 秒）"),
        "ラウドネス": ((lufs is not None and -15.5 <= lufs <= -12.5) or stub, f"{lufs} LUFS（目標 -14）" + ("  ※スタブ音声のため判定除外" if stub else "")),
        "無音の最大": ((max_gap <= 1.2) or stub, f"{max_gap:.2f} 秒（1.2 秒以下）" + ("  ※スタブ音声のため判定除外" if stub else "")),
    }
    if warnings is not None:
        long_holds = [x for x in warnings if "秒続く" in x]
        checks["画の変化"] = (len(long_holds) == 0, f"同じ画が 8 秒超: {len(long_holds)} か所" + ("（台本の step/mark を増やす）" if long_holds else ""))
    ok = all(v[0] for v in checks.values())
    print("---- QA", mp4.name)
    for k, (p, msg) in checks.items():
        print(f"  {'OK ' if p else 'NG '} {k}: {msg}")
    for wmsg in (warnings or []):
        if "秒続く" not in wmsg: print("  注意:", wmsg)
    print("  結果:", "合格" if ok else "不合格")
    if out_json:
        out_json.write_text(json.dumps({k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()} | {"pass": ok, "warnings": warnings or []}, ensure_ascii=False, indent=2), encoding="utf-8")
    return ok

# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="台本から動画を作る")
    b.add_argument("script"); b.add_argument("--out", required=True)
    b.add_argument("--tts", choices=["voicevox", "stub"], default="voicevox")
    b.add_argument("--bgm", default=str(HERE / "assets" / "bgm.mp3"), help="BGM ファイル（無ければ自前合成の BGM）")
    b.add_argument("--bgm-db", type=float, default=-22.0, help="BGM の音量（dB、負の値）")
    q = sub.add_parser("qa", help="出来上がりを検査する")
    q.add_argument("mp4")
    a = ap.parse_args()
    if a.cmd == "build":
        build(Path(a.script), Path(a.out), a.tts, Path(a.bgm) if a.bgm else None, a.bgm_db)
    else:
        sys.exit(0 if qa(Path(a.mp4)) else 1)

if __name__ == "__main__":
    main()
