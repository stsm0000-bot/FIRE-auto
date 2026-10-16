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
from PIL import Image

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
ANIM_SEC = {            # 状態が変わったとき、何秒ぶんコマ撮りするか（レイアウト別）
    "chapter": 0.7, "title": 0.8, "list": 0.8, "flow": 0.9, "compare": 0.8, "bar": 1.3, "quote": 0.7,
    "ending": 0.9, "counter": 2.3, "portfolio": 2.4, "timeline": 0.9, "photo": 0.9,
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
        "聞": {"voicevox_id": 14, "name": "聞き手", "color": "#2F5FB3"},   # 冥鳴ひまり
        "答": {"voicevox_id": 52, "name": "答え手", "color": "#A3631C"},   # 雀松朱司
    })
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
        else:
            default_steps = 1
        steps = int(s.get("steps", default_steps))
        lines, cur, prev = [], 1, 0
        for ln in s.get("lines", []):
            cur = min(int(ln.get("step", cur)), steps)
            lines.append(Line(sp=ln["sp"], text=str(ln["text"]).strip(), step=cur,
                              mark=ln.get("mark"), pause=float(ln.get("pause", PAUSE_LINE)), prev_step=prev))
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

def house_svg(color="#1B1B1B") -> str:
    return ('<svg viewBox="0 0 100 90"><path d="M50 8 L94 48 H80 V84 H20 V48 H6 Z" fill="#fff" stroke="%s" stroke-width="6" stroke-linejoin="round"/>'
            '<rect x="42" y="56" width="16" height="28" fill="%s"/></svg>' % (color, color))

def render_body(doc: dict, sc: Scene, step: int, mark: int | None, anim: bool, prev_step: int = 0) -> str:
    """anim=True のとき、この状態で新しく出る要素に .enter（出現アニメ）を付ける"""
    d = sc.data
    L = sc.layout
    h = []
    ent = lambda cond, extra="": (f' enter {extra}' if (anim and cond) else "")
    if L == "chapter":
        h.append(f'<div class="chapter{ent(True)}"><div class="num">{sc.chapter_no}</div><div class="ttl">{esc(d.get("heading",""))}</div></div>')
    elif L == "title":
        h.append(f'<div class="title"><div class="big{ent(True)}">{esc(d.get("heading",""))}</div>')
        if d.get("sub"):
            h.append(f'<div class="sub{ent(True)}" style="--i:2">{esc(d["sub"])}</div>')
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
        h.append(f'<div class="counter"><div class="lbl{ent(True)}">{esc(d.get("heading",""))}</div>'
                 f'<div class="num{ent(True, "pop")}">{cnt}<small>{esc(d.get("unit",""))}</small></div>')
        if d.get("sub"):
            h.append(f'<div class="sub{ent(True)}" style="--i:4">{esc(d["sub"])}</div>')
        h.append('</div>')
    elif L == "portfolio":
        # 戸建てが 1 軒ずつ増え、右の合計（戸数・月の家賃・年の家賃）が転がる
        n = int(d.get("count", 12)); rent = float(d.get("rent", 7)); cols = int(d.get("cols", 6 if doc["kind"] == "long" else 4))
        h.append(f'<div class="portfolio"><div class="houses" style="--cols:{cols}">')
        for i in range(1, n + 1):
            new = (prev_step < i <= step) if anim else False
            on = i <= step
            h.append(f'<div class="house{" on" if on else " off"}{" enter pop" if new else ""}" style="--i:{i-prev_step-1}">'
                     f'{house_svg("#1B1B1B" if on else "#9a968f")}<span>{esc(d.get("label","戸建て"))} {i}</span></div>')
        h.append('</div><div class="totals">')
        rows = [("戸数", prev_step, step, "戸", 0), (d.get("rent_label", "月の家賃"), prev_step * rent, step * rent, d.get("unit", "万円"), 0),
                ("年の家賃", prev_step * rent * 12, step * rent * 12, d.get("unit", "万円"), 0)]
        delay = 200 + max(0, step - prev_step - 1) * 120
        for k, (lbl, frm, to, unit, dec) in enumerate(rows):
            v = (f'<span data-count-from="{frm}" data-count-to="{to}" data-count-dur="900" data-count-delay="{delay}" data-count-dec="{dec}">{frm:,.{dec}f}</span>'
                 if anim and frm != to else f'{to:,.{dec}f}')
            h.append(f'<div class="tot"><div class="tl">{esc(lbl)}</div><div class="tv">{v}<small> {esc(unit)}</small></div></div>')
        h.append('</div></div>')
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

def render_html(doc: dict, sc: Scene, step: int, mark: int | None, chapter_idx: int, anim: bool = False, prev_step: int = 0) -> str:
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
            .replace("{{BODY}}", render_body(doc, sc, step, mark, anim, prev_step)))

def render_png(chrome: str, html: str, out_png: Path, size: tuple[int, int]) -> Path:
    key = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
    out = out_png.with_name(f"{out_png.stem}_{key}.png")
    if out.exists():
        return out
    html_path = out.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={size[0]},{size[1]}",
         "--virtual-time-budget=2000", f"--screenshot={out}", html_path.resolve().as_uri() + "?static"])
    im = Image.open(out)
    if im.size != size:  # 念のため寸法を揃える
        im = im.convert("RGB").resize(size)
        im.save(out)
    return out

def render_thumbnail(chrome: str, doc: dict, out_dir: Path) -> Path | None:
    th = doc.get("thumbnail")
    if not th:
        return None
    size = (1280, 720) if doc["kind"] == "long" else (1080, 1920)
    tpl = (HERE / "templates" / "thumb.html").read_text(encoding="utf-8")
    html = (tpl.replace("{{W}}", str(size[0])).replace("{{H}}", str(size[1]))
            .replace("{{FONT}}", doc.get("font", default_font()))
            .replace("{{BIG}}", esc(th.get("big", ""))).replace("{{SUB}}", esc(th.get("sub", "")))
            .replace("{{TAG}}", esc(th.get("tag", "小規模な大家"))))
    return render_png(chrome, html, out_dir / "thumb.png", size)

# ---------------------------------------------------------------- 音声
def wav_duration(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()

def write_silence(p: Path, sec: float, sr=SR):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sec * sr))

def tts_voicevox(text: str, speaker_id: int, out: Path, speed: float = 1.0):
    q = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": speaker_id}), method="POST")
    with urllib.request.urlopen(q, timeout=60) as r:
        query = json.loads(r.read())
    query["speedScale"] = speed
    query["outputSamplingRate"] = SR
    query["outputStereo"] = False
    s = urllib.request.Request(f"{VOICEVOX_URL}/synthesis?" + urllib.parse.urlencode({"speaker": speaker_id}),
                               data=json.dumps(query).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(s, timeout=120) as r:
        out.write_bytes(r.read())

def tts_line(mode: str, doc: dict, ln: Line, out: Path):
    if out.exists():
        return
    if mode == "stub":
        n = len(re.sub(r"[、。！？!?,.\s]", "", ln.text))
        write_silence(out, max(0.8, n * STUB_SEC_PER_CHAR + 0.25))
        return
    sp = doc["speakers"][ln.sp]
    tts_voicevox(ln.text, int(sp["voicevox_id"]), out, float(doc.get("speed", 1.0)))

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
    fs = 66 if short else 58
    mv = 560 if short else 46   # 下端からの距離（ショートは中央寄り）
    ml = 70 if short else 200
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
        text = wrap_jp(text.replace("★", "").strip(), 13 if short else 25)
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},{sp},,0,0,0,,{{\\c{col}}}▌{{\\c&H00FFFFFF&}}{text}")
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
    plan: list[dict] = []        # {html, key, nframes, dur, scene}
    audio_parts: list[tuple[Path, float]] = []
    sub_events: list[tuple[float, float, str, str]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    chapter_idx = 0
    last_key = None
    for sc in doc["_scenes"]:
        if sc.layout == "chapter":
            chapter_idx = sc.chapter_no
            chapters.append((t, f"{chapter_idx}. " + sc.data.get("heading", "")))
        elif sc.layout == "ending":
            chapters.append((t, "今日の一歩"))
        lines = sc.lines or [Line(sp=next(iter(doc["speakers"])), text="", step=sc.steps, pause=0.0)]
        for li, ln in enumerate(lines):
            key = (sc.id, ln.step, ln.mark)
            changed = key != last_key
            html = render_html(doc, sc, ln.step, ln.mark, chapter_idx, anim=changed, prev_step=ln.prev_step if changed else ln.step)
            if ln.text:
                wav = work / "voice" / f"{sc.id}_{li:02d}.wav"
                tts_line(tts_mode, doc, ln, wav)
                dur = wav_duration(wav)
            else:
                wav = work / "voice" / f"{sc.id}_sil.wav"; write_silence(wav, 2.0); dur = 2.0
            last = li == len(lines) - 1
            pause = (PAUSE_CHAPTER if sc.layout == "chapter" else PAUSE_SCENE) if last else ln.pause
            if ln.text:
                sub_events.append((t, t + dur + min(pause, 0.3), ln.sp, ln.text))
            nframes = int(round(ANIM_SEC.get(sc.layout, 0.8) * FPS)) if (changed and motion) else 1
            plan.append({"html": html, "key": key, "nframes": nframes, "dur": dur + pause, "scene": sc.id})
            audio_parts.append((wav, pause)); t += dur + pause
            last_key = key
    total = t
    print(f"      場面 {len(doc['_scenes'])} / 台詞 {len(sub_events)} / 予定尺 {total:.1f} 秒")

    print("[2/5] スライドをコマ撮り")
    jobs = []
    for pl in plan:
        h = hashlib.md5(pl["html"].encode("utf-8")).hexdigest()[:12]
        prefix = work / "slides" / f"{pl['scene']}_{h}"
        pl["prefix"] = prefix
        html_path = prefix.with_suffix(".html")
        if not html_path.exists():
            html_path.write_text(pl["html"], encoding="utf-8")
        if pl["nframes"] == 1:
            final = prefix.with_suffix(".png")
            if not final.exists():
                if motion:
                    jobs.append({"html": str(html_path), "out": str(prefix), "frames": 1})
                else:
                    render_png(chrome, pl["html"], prefix, size)
        else:
            lastf = prefix.parent / f"{prefix.name}_{pl['nframes']-1:04d}.png"
            if not lastf.exists():
                jobs.append({"html": str(html_path), "out": str(prefix), "frames": pl["nframes"], "fps": FPS})
    if jobs:
        spec = work / "jobs.json"
        spec.write_text(json.dumps({"width": size[0], "height": size[1], "jobs": jobs}, ensure_ascii=False), encoding="utf-8")
        run(["node", str(RENDER_JS), str(spec)], cwd=HERE)
    print(f"      コマ {sum(j.get('frames',1) for j in jobs)} 枚を新規生成")

    print("[3/5] 音声を 1 本に / 字幕 (ASS)")
    voice = work / "voice.wav"; concat_wavs(audio_parts, voice)
    write_ass(doc, sub_events, work / "subs.ass")

    print("[4/5] 画の並び（場面の切り替えはクロスフェード）")
    frames_txt: list[tuple[Path, float]] = []
    prev_png: Path | None = None; prev_scene = None
    for pl in plan:
        prefix: Path = pl["prefix"]
        if pl["nframes"] == 1:
            seq = [prefix.with_suffix(".png")]
        else:
            seq = [prefix.parent / f"{prefix.name}_{i:04d}.png" for i in range(pl["nframes"])]
        if prev_png is not None and pl["scene"] != prev_scene:   # 場面が変わる: クロスフェード
            a = Image.open(prev_png).convert("RGB"); b = Image.open(seq[0]).convert("RGB")
            for k in range(1, XFADE_FRAMES + 1):
                f = work / "slides" / f"x_{hashlib.md5((str(prev_png)+str(seq[0])+str(k)).encode()).hexdigest()[:10]}.png"
                if not f.exists():
                    Image.blend(a, b, k / (XFADE_FRAMES + 1)).save(f)
                frames_txt.append((f, 1 / FPS))
        remain = pl["dur"]
        if len(seq) > 1:
            use = seq[:max(1, min(len(seq), int(remain * FPS) - 1))]
            for f in use[:-1]:
                frames_txt.append((f, 1 / FPS)); remain -= 1 / FPS
            seq = [use[-1]]
        frames_txt.append((seq[0], max(0.04, remain)))
        prev_png = seq[0]; prev_scene = pl["scene"]
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
          f"subtitles=subs.ass,format=yuv420p")
    mix = work / "mix.wav"
    if bgm and Path(bgm).exists():
        run(["ffmpeg", "-y", "-i", str(voice), "-stream_loop", "-1", "-i", str(Path(bgm).resolve()),
             "-filter_complex",
             f"[1:a]aformat=sample_rates={SR}:channel_layouts=mono,volume={bgm_db}dB,atrim=0:{total:.3f},afade=t=out:st={max(0,total-2):.2f}:d=2[bg];"
             f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=600:makeup=1[duck];"
             f"[0:a][duck]amix=inputs=2:duration=first:normalize=0[mix]",
             "-map", "[mix]", "-ac", "1", str(mix)], cwd=work)
    else:
        shutil.copy(voice, mix)
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
         "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out_mp4.resolve())], cwd=work)

    thumb = render_thumbnail(chrome, doc, out_dir)
    write_publish(doc, chapters, total, out_dir, thumb)
    print(f"完成: {out_mp4}")
    qa(out_mp4, kind, stub=(tts_mode == "stub"), out_json=out_dir / "qa.json")

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
    desc += [doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です。"),
             "個別のご相談・物件のご紹介は承っておりません。",
             "音声は合成音声です。VOICEVOX:冥鳴ひまり、VOICEVOX:雀松朱司"]
    tags = pub.get("tags", ["不動産投資", "大家", "一棟目", "小規模大家", "不動産", "物件探し"])
    md = [f"# 公開用メモ  {doc['id']}", "",
          f"- 種別: {'長尺' if doc['kind']=='long' else 'ショート'}  尺 {fmt_ts(total)}",
          f"- タイトル: {doc.get('title','')}",
          f"- サムネ: {thumb.name if thumb else '（thumbnail 未設定）'}",
          f"- タグ: {', '.join(tags)}", "",
          "## 説明文（そのまま貼る）", "```", *desc, "```"]
    (out_dir / "publish.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- 検査
def qa(mp4: Path, kind: str | None = None, stub=False, out_json: Path | None = None) -> bool:
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
    ok = all(v[0] for v in checks.values())
    print("---- QA", mp4.name)
    for k, (p, msg) in checks.items():
        print(f"  {'OK ' if p else 'NG '} {k}: {msg}")
    print("  結果:", "合格" if ok else "不合格")
    if out_json:
        out_json.write_text(json.dumps({k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()} | {"pass": ok}, ensure_ascii=False, indent=2), encoding="utf-8")
    return ok

# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="台本から動画を作る")
    b.add_argument("script"); b.add_argument("--out", required=True)
    b.add_argument("--tts", choices=["voicevox", "stub"], default="voicevox")
    b.add_argument("--bgm", default=str(HERE / "assets" / "bgm.mp3"), help="BGM ファイル（無ければ BGM なし）")
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
