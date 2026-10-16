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
XFADE_FRAMES = 6        # 画の切り替えにかけるコマ数（0.2秒）
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
        if layout in ("list", "flow", "bar"):
            default_steps = max(1, len(items))
        elif layout == "compare" or (layout == "quote" and s.get("caption")):
            default_steps = 2
        else:
            default_steps = 1
        steps = int(s.get("steps", default_steps))
        lines, cur = [], 1
        for ln in s.get("lines", []):
            cur = int(ln.get("step", cur))
            lines.append(Line(sp=ln["sp"], text=str(ln["text"]).strip(), step=min(cur, steps),
                              mark=ln.get("mark"), pause=float(ln.get("pause", PAUSE_LINE))))
        scenes.append(Scene(id=str(s["id"]), layout=layout, data=s, lines=lines, steps=steps,
                            chapter_no=chapter_no if layout == "chapter" else None))
    doc["_scenes"] = scenes
    doc["_chapters"] = chapter_no
    return doc

# ---------------------------------------------------------------- スライド描画
def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))

def render_body(doc: dict, sc: Scene, step: int, mark: int | None, chapter_idx: int) -> str:
    d = sc.data
    L = sc.layout
    h = []
    if L == "chapter":
        h.append(f'<div class="chapter"><div class="num">{sc.chapter_no}</div><div class="ttl">{esc(d.get("heading",""))}</div></div>')
    elif L == "title":
        h.append(f'<div class="title"><div class="big">{esc(d.get("heading",""))}</div>')
        if d.get("sub"):
            h.append(f'<div class="sub">{esc(d["sub"])}</div>')
        h.append('</div>')
    elif L in ("list", "flow"):
        items = d.get("items", [])
        h.append(f'<div class="{L}">')
        if d.get("heading"):
            h.append(f'<div class="h">{esc(d["heading"])}</div>')
        h.append('<div class="row">')
        for i, it in enumerate(items, 1):
            cls = "box" + (" on" if i <= step else " off") + (" mark" if mark == i else "")
            label = it if isinstance(it, str) else it.get("text", "")
            note = "" if isinstance(it, str) else it.get("note", "")
            h.append(f'<div class="{cls}"><span class="n">{i}</span><span class="t">{esc(label)}</span>'
                     + (f'<span class="note">{esc(note)}</span>' if note and i <= step else "") + '</div>')
            if L == "flow" and i < len(items):
                h.append(f'<div class="arrow{" on" if i < step else " off"}">→</div>')
        h.append('</div></div>')
    elif L == "compare":
        h.append('<div class="compare">')
        for k, side in enumerate(("left", "right"), 1):
            s = d.get(side, {})
            cls = "col" + (" on" if k <= step else " off") + (f' {s.get("tone","")}')
            h.append(f'<div class="{cls}"><div class="ct">{esc(s.get("title",""))}</div>')
            for it in s.get("items", []):
                h.append(f'<div class="ci">{esc(it)}</div>')
            h.append('</div>')
        h.append('</div>')
    elif L == "bar":
        rows = d.get("rows", [])
        mx = max([float(r.get("value", 0)) for r in rows] + [1.0])
        h.append('<div class="bars">')
        if d.get("heading"):
            h.append(f'<div class="h">{esc(d["heading"])}</div>')
        for i, r in enumerate(rows, 1):
            w = int(100 * float(r.get("value", 0)) / mx)
            on = " on" if i <= step else " off"
            h.append(f'<div class="brow{on}{" mark" if mark == i else ""}"><div class="bl">{esc(r.get("label",""))}</div>'
                     f'<div class="bt"><div class="bf" style="width:{w}%"></div></div><div class="bv">{esc(r.get("note",""))}</div></div>')
        h.append('</div>')
    elif L == "quote":
        h.append('<div class="quote">')
        if d.get("heading"):
            h.append(f'<div class="h">{esc(d["heading"])}</div>')
        h.append(f'<div class="qbox">{esc(d.get("text",""))}</div>')
        if d.get("caption"):
            h.append(f'<div class="cap{" on" if step >= 2 else " off"}">{esc(d["caption"])}</div>')
        h.append('</div>')
    elif L == "ending":
        h.append('<div class="ending"><div class="eh">今日の一歩</div>'
                 f'<div class="eb">{esc(d.get("heading",""))}</div>')
        if d.get("sub"):
            h.append(f'<div class="es">{esc(d["sub"])}</div>')
        h.append('<div class="ecta">続きは note で ▶</div></div>')
    else:
        raise SystemExit(f"未対応の layout: {L}")
    return "\n".join(h)

def render_html(doc: dict, sc: Scene, step: int, mark: int | None, chapter_idx: int) -> str:
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
            .replace("{{BODY}}", render_body(doc, sc, step, mark, chapter_idx)))

def render_png(chrome: str, html: str, out_png: Path, size: tuple[int, int]) -> Path:
    key = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
    out = out_png.with_name(f"{out_png.stem}_{key}.png")
    if out.exists():
        return out
    html_path = out.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={size[0]},{size[1]}",
         f"--screenshot={out}", html_path.resolve().as_uri()])
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
        text = wrap_jp(text, 13 if short else 25)
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},{sp},,0,0,0,,{{\\c{col}}}▌{{\\c&H00FFFFFF&}}{text}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- 結合
def build(script: Path, out_dir: Path, tts_mode: str, bgm: Path | None, bgm_db: float):
    doc = load_script(script)
    kind = doc["kind"]; size = SIZES[kind]
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"; (work / "slides").mkdir(parents=True, exist_ok=True); (work / "voice").mkdir(exist_ok=True)
    chrome = find_chrome()
    print(f"[1/5] スライド描画 ({kind} {size[0]}x{size[1]})  chrome={chrome}")

    segments: list[tuple[Path, float]] = []     # (png, 表示秒)
    audio_parts: list[tuple[Path, float]] = []  # (wav, 後ろの無音秒)
    sub_events: list[tuple[float, float, str, str]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    chapter_idx = 0
    for si, sc in enumerate(doc["_scenes"]):
        if sc.layout == "chapter":
            chapter_idx = sc.chapter_no
            chapters.append((t, f"{chapter_idx}. " + sc.data.get("heading", "")))
        elif sc.layout == "ending":
            chapters.append((t, "今日の一歩"))
        if not sc.lines:  # 台詞なしの場面は 2 秒見せる
            png = render_png(chrome, render_html(doc, sc, sc.steps, None, chapter_idx), work / "slides" / sc.id, size)
            sil = work / "voice" / f"{sc.id}_sil.wav"; write_silence(sil, 2.0)
            segments.append((png, 2.0)); audio_parts.append((sil, 0.0)); t += 2.0
        for li, ln in enumerate(sc.lines):
            png = render_png(chrome, render_html(doc, sc, ln.step, ln.mark, chapter_idx), work / "slides" / sc.id, size)
            wav = work / "voice" / f"{sc.id}_{li:02d}.wav"
            tts_line(tts_mode, doc, ln, wav)
            dur = wav_duration(wav)
            last = li == len(sc.lines) - 1
            pause = (PAUSE_CHAPTER if sc.layout == "chapter" else PAUSE_SCENE) if last else ln.pause
            sub_events.append((t, t + dur + min(pause, 0.3), ln.sp, ln.text))
            segments.append((png, dur + pause)); audio_parts.append((wav, pause)); t += dur + pause
    total = t
    print(f"      場面 {len(doc['_scenes'])} / 台詞 {len(sub_events)} / 予定尺 {total:.1f} 秒")

    print("[2/5] 音声を 1 本に")
    voice = work / "voice.wav"; concat_wavs(audio_parts, voice)

    print("[3/5] 字幕 (ASS)")
    write_ass(doc, sub_events, work / "subs.ass")

    print("[4/5] 画の並び（切り替えはクロスフェード）")
    frames_txt = []
    prev: Path | None = None
    for png, dur in segments:
        if prev is not None and prev != png:
            a = Image.open(prev).convert("RGB"); b = Image.open(png).convert("RGB")
            for k in range(1, XFADE_FRAMES + 1):
                f = work / "slides" / f"x_{hashlib.md5((str(prev)+str(png)+str(k)).encode()).hexdigest()[:10]}.png"
                if not f.exists():
                    Image.blend(a, b, k / (XFADE_FRAMES + 1)).save(f)
                frames_txt.append((f, 1 / FPS))
            dur = max(0.05, dur - XFADE_FRAMES / FPS)
        frames_txt.append((png, dur)); prev = png
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
    # 音: BGM があればダッキング混合 → 2 パスのラウドネス正規化
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
    measured_i = float(m["input_i"])
    if tts_mode == "stub" or measured_i < -70:   # スタブ（無音）の場合は正規化しない
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
