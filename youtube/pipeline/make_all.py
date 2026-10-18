#!/usr/bin/env python3
"""make_all.py ― 台本 1 本（または複数）から、公開に要るものを全部そろえる（1 本ずつ繰り返す運用の入口）。

使い方（youtube フォルダで）:
  python pipeline/make_all.py scripts/003_xxx.yaml                 本番音声（VOICEVOX を起動しておく）
  python pipeline/make_all.py scripts/003_xxx.yaml --tts stub      音声なしで画と尺だけ確かめる（速い）
  python pipeline/make_all.py scripts/003_xxx.yaml scripts/S005_xxx.yaml scripts/S006_xxx.yaml

やること（台本ごとに）:
  1. make_video.py build   → out/<id>/<id>.mp4・サムネ・publish.md・qa.json
  2. 字幕の時刻一覧         → out/<id>/字幕の時刻.txt（投稿文の「3:58 で〜」を合わせるのに使う）
  3. make_posts.py --strict → out/<id>/sns/（X・Threads・note 下書き・説明欄・固定コメント・公開手順）
  4. 納品フォルダ           → out/<id>/納品/（mp4・サムネ・投稿文・publish.md を 1 か所に）
最後に、合否と尺の一覧を出す。QA 不合格や投稿文の警告があれば終了コード 1。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # youtube/
VOICEVOX_URL = "http://127.0.0.1:50021"


def voicevox_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def script_id(path: Path) -> str:
    """台本の id（無ければファイル名の先頭 NNN / SNNN）"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^id:\s*"?([^"\n]+)"?', text, re.M)
    return m.group(1).strip() if m else path.stem.split("_")[0]


def subs_times(ass: Path, out: Path, names: dict[str, str]) -> None:
    """字幕（ASS）から「開始時刻 話者 台詞」の一覧を作る"""
    rows = []
    for line in ass.read_text(encoding="utf-8").splitlines():
        if not line.startswith("Dialogue"):
            continue
        p = line.split(",", 9)
        h, m, s = p[1].split(":")
        sec = int(h) * 3600 + int(m) * 60 + float(s)
        text = re.sub(r"\{[^}]*\}", "", p[9]).replace("\\N", "").lstrip("▌").strip()
        rows.append(f"{int(sec // 60)}:{int(sec % 60):02d}  {names.get(p[3], p[3])}: {text}")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")


def run(cmd: list[str]) -> int:
    print("  $", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def make_one(script: Path, tts: str, out_root: Path) -> dict:
    sid = script_id(script)
    out = out_root / sid
    res = {"id": sid, "script": script.name, "qa": False, "detail": "", "posts": None}
    print(f"\n==== {sid}  {script.name}", flush=True)
    if run([sys.executable, str(HERE / "make_video.py"), "build", str(script), "--out", str(out), "--tts", tts]) != 0:
        res["detail"] = "make_video が失敗（上のエラーを見る）"
        return res
    qa_path = out / "qa.json"
    if qa_path.exists():
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        res["qa"] = bool(qa.get("pass"))
        res["detail"] = " / ".join(f"{k}: {v['detail']}" for k, v in qa.items() if isinstance(v, dict) and not v.get("ok"))
        res["dur"] = qa.get("尺", {}).get("detail", "").split("（")[0]
        res["lufs"] = qa.get("ラウドネス", {}).get("detail", "").split("（")[0]
    ass = out / "work" / "subs.ass"
    if ass.exists():
        try:
            import yaml
            sp = (yaml.safe_load(script.read_text(encoding="utf-8")) or {}).get("speakers") or {}
            names = {k: str(v.get("name", k)) for k, v in sp.items()}
        except Exception:
            names = {}
        subs_times(ass, out / "字幕の時刻.txt", names)
    if "sns:" in script.read_text(encoding="utf-8"):
        res["posts"] = run([sys.executable, str(HERE / "make_posts.py"), str(script), "--out", str(out / "sns"),
                            "--publish", str(out / "publish.md"), "--strict"]) == 0
    # 納品フォルダ
    d = out / "納品"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    mp4 = out / f"{sid}.mp4"
    if mp4.exists():
        shutil.copy2(mp4, d / f"{script.stem}.mp4")
    thumbs = sorted(out.glob("thumb_*.png"), key=lambda p: p.stat().st_mtime)
    if thumbs:
        shutil.copy2(thumbs[-1], d / "サムネ.png")
    for f in ("publish.md", "字幕の時刻.txt"):
        if (out / f).exists():
            shutil.copy2(out / f, d / f)
    if (out / "sns").exists():
        shutil.copytree(out / "sns", d / "投稿文")
    res["deliver"] = str(d)
    return res


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows のコンソール対策
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="台本から、動画・サムネ・投稿文・字幕の時刻一覧までを 1 回で作る")
    ap.add_argument("scripts", nargs="+", help="台本 YAML（複数可）")
    ap.add_argument("--tts", choices=["voicevox", "stub"], default="voicevox")
    ap.add_argument("--out-root", default=str(ROOT / "out"), help="出力の親フォルダ（既定 youtube/out）")
    a = ap.parse_args()
    if a.tts == "voicevox" and not voicevox_ok():
        print("VOICEVOX が起動していません。VOICEVOX を起動してから、もう一度実行してください（音声なしで試すなら --tts stub）。")
        return 2
    results = [make_one(Path(s).resolve(), a.tts, Path(a.out_root).resolve()) for s in a.scripts]
    print("\n==== 結果")
    bad = False
    for r in results:
        posts = "なし" if r["posts"] is None else ("警告0" if r["posts"] else "警告あり")
        print(f"  {r['id']:<6} QA {'合格' if r['qa'] else '不合格'}  尺 {r.get('dur', '-')}  音量 {r.get('lufs', '-')}  投稿文 {posts}")
        if r["detail"]:
            print(f"         直す所: {r['detail']}")
        if r.get("deliver"):
            print(f"         納品: {r['deliver']}")
        bad |= (not r["qa"]) or (r["posts"] is False)
    if a.tts == "stub":
        print("\n※ --tts stub は仮の無音で尺を見積もっただけ。公開用は VOICEVOX で作り直す。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
