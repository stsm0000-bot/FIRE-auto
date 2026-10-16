#!/usr/bin/env python3
"""make_posts.py ― 台本（YAML）の `sns:` ブロックから、各媒体の投稿文ファイルを作る。

使い方:
  python make_posts.py scripts/002_xxx.yaml --out out/002/sns [--publish out/002/publish.md] [--strict]

出力（--out の中）:
  x_thread.txt          X のスレッド（投稿ごとに --- 区切り、番号付き）
  x_single_1.txt …      X の単発
  threads_1.txt …       Threads
  note_draft.md         note 記事の下書き（骨子を見出しに。無料部分は台本の数字・台詞から自動で要約。有料ラインあり）
  community.txt         YouTube コミュニティ投稿
  pinned_comment.txt    固定コメント
  youtube_description.txt  説明欄（publish.md があればそれを取り込み、1 行目を sns.lead に差し替える）
  checklist.md          公開日の手順と、検査の結果

検査:
  X は 1 投稿の重み付き文字数（全角＝2、半角＝1、URL＝23）が 280 を超えたら警告。Threads は 500 字。
  禁止語（簡単・誰でも・確実・必ず・不労所得・儲かる）を含んだら警告（「簡単ではない」の形は除外）。
  --strict で警告があれば終了コード 1。

`sns:` が無い台本では、title・publish.lead・question から最低限（X 単発 1 本・固定コメント・説明欄）を作る。
依存は pyyaml だけ。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

X_LIMIT = 280
THREADS_LIMIT = 500
URL_WEIGHT = 23
BANNED = ["簡単", "誰でも", "確実", "必ず", "不労所得", "儲かる"]
BANNED_EXEMPT = re.compile(r"簡単(では|じゃ|には)")   # 「簡単ではない」は口癖として許す（docs/09）
URL_RE = re.compile(r"https?://\S+")
PLACEHOLDER_VIDEO = "https://youtu.be/XXXXXXXXXXX"

# ---------------------------------------------------------------- 文字の扱い
def clean(text) -> str:
    """★ を消し、前後の空白を落とす（★ は本人確認用の印。投稿文には出さない）。"""
    return re.sub(r"\s*★\s*", "", str(text or "")).strip()

def x_weight(text: str) -> int:
    """X の重み付き文字数。URL は 23、全角（CJK・絵文字など）は 2、半角は 1。"""
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += _weight_plain(text[pos:m.start()]) + URL_WEIGHT
        pos = m.end()
    return total + _weight_plain(text[pos:])

def _weight_plain(s: str) -> int:
    w = 0
    for ch in s:
        cp = ord(ch)
        if cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247:
            w += 1
        else:
            w += 2
    return w

def find_banned(text: str) -> list[str]:
    t = BANNED_EXEMPT.sub("", text)
    return [w for w in BANNED if w in t]

# ---------------------------------------------------------------- 台本の場面 → 要約ブロック
def _lines_of(scene: dict) -> list[dict]:
    return [ln for ln in scene.get("lines", []) if isinstance(ln, dict)]

def key_line(scene: dict, answerer: str) -> str:
    """場面の台詞から要約に使う 1 行（mark 付き → 数字入り → 最初の答え手の台詞）。"""
    ls = [ln for ln in _lines_of(scene) if ln.get("sp") == answerer] or _lines_of(scene)
    for pick in (lambda l: "mark" in l, lambda l: re.search(r"\d", str(l.get("text", ""))), lambda l: True):
        for ln in ls:
            if pick(ln):
                return clean(ln.get("text", ""))
    return ""

def _item_text(it) -> str:
    if isinstance(it, dict):
        return " ".join(clean(it.get(k, "")) for k in ("when", "label", "text", "value", "note", "caption") if it.get(k))
    return clean(it)

def scene_block(scene: dict, chapter: str, answerer: str) -> dict | None:
    lay = scene.get("layout", "")
    heading = clean(scene.get("heading", "")).replace("\n", " ")
    md: list[str] = []
    if lay == "counter":
        md.append(f"**{heading} {scene.get('value', '')}{clean(scene.get('unit', ''))}**" + (f" ― {clean(scene.get('sub'))}" if scene.get("sub") else ""))
    elif lay == "flow":
        items = scene.get("items", [])
        if items and isinstance(items[0], dict) and any("value" in it for it in items):
            md += ["| 項目 | 金額 |", "|---|---|"]
            for it in items:
                md.append(f"| {clean(it.get('op', ''))} {clean(it.get('text', ''))} | {clean(it.get('value', ''))} |")
        else:
            md += [f"- {_item_text(it)}" for it in items]
    elif lay == "list":
        md += [f"- {clean(it.get('text', ''))}" + (f"（{clean(it.get('note'))}）" if isinstance(it, dict) and it.get("note") else "")
               if isinstance(it, dict) else f"- {clean(it)}" for it in scene.get("items", [])]
    elif lay == "bar":
        md += ["| | 値 |", "|---|---|"]
        md += [f"| {clean(r.get('label', ''))} | {clean(r.get('note', r.get('value', '')))} |" for r in scene.get("rows", [])]
    elif lay == "compare":
        for side in ("left", "right"):
            s = scene.get(side, {})
            if s:
                md.append(f"- **{clean(s.get('title', ''))}**: " + "、".join(clean(x) for x in s.get("items", [])))
    elif lay == "timeline":
        md += ["| 時期 | できごと | 補足 |", "|---|---|---|"]
        md += [f"| {clean(it.get('when', ''))} | {clean(it.get('text', ''))} | {clean(it.get('note', ''))} |" for it in scene.get("items", [])]
    elif lay == "portfolio":
        n, rent = int(scene.get("count", 0) or 0), float(scene.get("rent", 0) or 0)
        label = clean(scene.get("label", "戸建て"))
        month = n * rent
        md.append(f"{label}{n}戸 × 月{rent:g}万円 ＝ 月{month:g}万円（年{month * 12:g}万円）の計算")
    elif lay == "quote":
        md.append(f"> {clean(scene.get('text', ''))}" + (f"（{clean(scene.get('caption'))}）" if scene.get("caption") else ""))
    elif lay == "photo":
        for side, tag in (("before", "買ったとき"), ("after", "直したあと")):
            s = scene.get(side, {})
            if s:
                cap, tg = clean(s.get("caption", "")), clean(s.get("tag", tag))
                md.append(f"- {cap}" if tg in cap else f"- {tg}: {cap}")
    elif lay == "ending":
        md.append(f"**今日の一歩**: {heading}" + (f" ― {clean(scene.get('sub'))}" if scene.get("sub") else ""))
    elif lay == "scene":
        texts = [clean(p.get("text", "")) for p in scene.get("props", []) if isinstance(p, dict) and p.get("kind") in ("headline", "price", "sign", "calendar", "stamp")]
        if texts:
            md.append("、".join(t for t in texts if t))
    elif lay in ("chapter", "title"):
        return None
    line = key_line(scene, answerer)
    if line:
        md.append(f"> {line}")
    if not md:
        return None
    body_for_match = " ".join([chapter] + md + [str(scene.get("sub", ""))])
    return {"id": scene.get("id", ""), "heading": heading, "chapter": chapter, "md": "\n".join(md),
            "show_heading": lay not in ("counter", "ending"),
            "hgrams": bigrams(heading), "grams": bigrams(body_for_match)}

def bigrams(s: str) -> set[str]:
    s = re.sub(r"[\s|*>\-:：・、。（）()「」【】]+", "", str(s))
    return {s[i:i + 2] for i in range(len(s) - 1)}

def build_blocks(doc: dict) -> list[dict]:
    answerer = "答"
    chapter = ""
    out = []
    for sc in doc.get("scenes", []):
        if not isinstance(sc, dict):
            continue
        if sc.get("layout") == "chapter":
            chapter = clean(sc.get("heading", ""))
            continue
        if sc.get("layout") in ("quote", "ending"):
            chapter = "まとめ"
        b = scene_block(sc, chapter, answerer)
        if b:
            out.append(b)
    return out

def chapters_of(doc: dict) -> list[str]:
    return [clean(sc.get("heading", "")) for sc in doc.get("scenes", []) if isinstance(sc, dict) and sc.get("layout") == "chapter"]

def match_blocks(heading: str, blocks: list[dict], used: set[str], limit: int = 3) -> list[dict]:
    """骨子の見出しと場面の重なり（文字 2-gram）で選ぶ。場面の見出しとの一致は 3 倍に数える。"""
    hg = bigrams(heading)
    scored = sorted(((3 * len(hg & b["hgrams"]) + len(hg & b["grams"]), i)
                     for i, b in enumerate(blocks) if b["id"] not in used), reverse=True)
    best = scored[0][0] if scored else 0
    picked = [blocks[i] for s, i in scored[:limit] if s >= max(2, best // 2)]
    for b in picked:
        used.add(b["id"])
    return picked

# ---------------------------------------------------------------- note の下書き
def note_draft(doc: dict, sns: dict, video_url: str) -> str:
    outline = sns.get("note_outline", {}) or {}
    title = clean(outline.get("title") or doc.get("title", ""))
    price = outline.get("price", 500)
    blocks = build_blocks(doc)
    used: set[str] = set()
    lead = clean((doc.get("publish") or {}).get("lead", ""))
    md = [f"# {title}", "", f"（YouTube の埋め込み: この行に動画の URL を貼る → {video_url}）", ""]
    if lead:
        md += [lead, ""]
    free = outline.get("free") or ["この記事で分かること", "動画の数字"]
    for i, h in enumerate(free):
        md.append(f"## {clean(h)}")
        if i == 0 and re.search(r"分かる|わかる|要約|まとめ", str(h)):
            md += [f"- {c}" for c in chapters_of(doc)] or ["- （動画の章を書く）"]
            if doc.get("question"):
                md.append(f"- 問い: {clean(doc['question'])}")
        else:
            hits = match_blocks(h, blocks, used)
            if hits:
                for b in hits:
                    if b["show_heading"] and b["heading"] and b["heading"] != clean(h):
                        md.append(f"**{b['heading']}**")
                    md.append(b["md"])
                    md.append("")
            else:
                md.append("（動画の該当部分を書く）")
        md.append("")
    rest = [b for b in blocks if b["id"] not in used]
    if rest:
        md += ["## 動画に出た、そのほかの数字", ""]
        for b in rest:
            if b["show_heading"] and b["heading"]:
                md.append(f"**{b['heading']}**")
            md += [b["md"], ""]
    md += [f"---- ここから有料（{price}円）----", ""]
    paid = outline.get("paid") or ["一覧・内訳（有料）"]
    md.append("有料部分に入っているもの: " + "／".join(clean(h) for h in paid))
    md.append("")
    for h in paid:
        md += [f"## {clean(h)}", "", "- （ここに書く。一覧なら項目ごとに見方・NG 例、内訳なら金額の行、失敗なら時系列）", ""]
    md += [clean(doc.get("disclaimer", "")), "個別のご相談・物件のご紹介は承っておりません。", ""]
    return "\n".join(md)

# ---------------------------------------------------------------- 説明欄
def description(doc: dict, sns: dict, publish_md: Path | None) -> str:
    lead = clean(sns.get("lead") or (doc.get("publish") or {}).get("lead") or doc.get("title", ""))
    if publish_md and publish_md.exists():
        text = publish_md.read_text(encoding="utf-8")
        m = re.search(r"## 説明文.*?\n```\n(.*?)\n```", text, re.S)
        if m:
            lines = m.group(1).split("\n")
            lines[0] = lead
            return "\n".join(lines) + "\n"
    desc = [lead, ""]
    if doc.get("note_url"):
        desc += ["▼この回の元になった記事（note）", doc["note_url"], ""]
    voices = "、".join(f"VOICEVOX:{sp.get('speaker', sp.get('name', ''))}" for sp in (doc.get("speakers") or {}).values())
    desc += [clean(doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です。")),
             "個別のご相談・物件のご紹介は承っておりません。"]
    if voices:
        desc.append(f"音声は合成音声です。{voices}")
    if doc.get("bgm_credit"):
        desc.append(f"BGM: {doc['bgm_credit']}")
    return "\n".join(desc) + "\n"

# ---------------------------------------------------------------- 最低限の投稿（sns が無いとき）
def fallback_sns(doc: dict, video_url: str) -> dict:
    pub = doc.get("publish") or {}
    lead = clean(pub.get("lead") or doc.get("title", ""))
    q = clean(doc.get("question", ""))
    note_url = doc.get("note_url", "https://note.com/dokechi_hudousan")
    single = (f"{q}\n" if q else "") + f"{lead}\n▶ {video_url}"
    if x_weight(single) > X_LIMIT:
        single = f"{lead}\n▶ {video_url}"
    pinned = "\n".join(x for x in [
        f"この回の問い:「{q}」" if q else "",
        clean(doc.get("disclaimer", "")),
        f"詳しい数字と一覧は note にまとめています → {note_url}",
        "個別のご相談・物件のご紹介は承っておりませんが、動画の内容への質問はこのコメント欄にどうぞ。",
    ] if x)
    return {"x_single": [single], "pinned_comment": pinned}

# ---------------------------------------------------------------- 検査
def check_x(label: str, text: str, warnings: list[str]):
    w = x_weight(text)
    if w > X_LIMIT:
        warnings.append(f"{label}: X の重み付き文字数 {w} が {X_LIMIT} を超えています（全角 {X_LIMIT // 2} 字相当）")
    check_banned(label, text, warnings)

def check_threads(label: str, text: str, warnings: list[str]):
    if len(text) > THREADS_LIMIT:
        warnings.append(f"{label}: Threads の文字数 {len(text)} が {THREADS_LIMIT} を超えています")
    if not text.rstrip().endswith(("？", "?")):
        warnings.append(f"{label}: Threads は答えやすい問いで終える（末尾が ？ ではありません）")
    check_banned(label, text, warnings)

def check_banned(label: str, text: str, warnings: list[str]):
    hit = find_banned(text)
    if hit:
        warnings.append(f"{label}: 禁止語を含んでいます → {'、'.join(hit)}")

# ---------------------------------------------------------------- 書き出し
def write(path: Path, text: str):
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")

def checklist(doc: dict, files: list[str], warnings: list[str], has_sns: bool) -> str:
    md = [f"# 公開日の手順  {doc.get('id', '')}  {clean(doc.get('title', ''))}", "",
          "生成したファイル: " + "、".join(files), "",
          "## 前日（金）",
          "- [ ] note 記事を公開し、URL を pinned_comment.txt と youtube_description.txt に入れる（XXXXXXXX を置換）",
          "- [ ] note の「X で共有」で記事を X に流す（1 行目は記事の結論）",
          "- [ ] 21:00 community.txt をコミュニティ投稿" if has_sns else "- [ ] 21:00 コミュニティ投稿で予告（sns ブロックが無いので手で書く）",
          "", "## 公開日（土）",
          "- [ ] 7:00 公開（予約）。youtube_description.txt の 1 行目が結論になっているか確認",
          "- [ ] 7:05 pinned_comment.txt を貼って固定",
          "- [ ] 7:30 x_single_1.txt を投稿（動画 URL の XXXXXXXXXXX を置換）" + ("。threads_1.txt を投稿" if has_sns else ""),
          "- [ ] 12:15 x_thread.txt を投稿（URL は最後の投稿だけ）" if has_sns else "- [ ] 12:15 X に要約を 1 本（sns ブロックが無いので手で書く）",
          "- [ ] 21:00 コメントに全部返信。クリック率を見る（4％未満なら翌朝サムネ差し替え）",
          "", "## 翌日（日）",
          "- [ ] 7:30 ショート 1 を公開（関連動画に長尺を指定）。x_single_2.txt を投稿" if has_sns else "- [ ] 7:30 ショート 1 を公開（関連動画に長尺を指定）",
          "- [ ] 21:00 X・Threads・YouTube の返信。平均視聴時間を見る（冒頭 30 秒で 30％落ちていれば次回のフックを直す）",
          "", "## 3 日後（火）",
          "- [ ] x_single_3.txt、threads_2.txt を投稿。ショート 2〜3 は月・水" if has_sns else "- [ ] ショート 2〜3 は月・水",
          "- [ ] 48 時間の数字を docs/14 §7 の表に記録",
          "", "## 検査の結果"]
    md += [f"- 警告: {w}" for w in warnings] or ["- 警告なし"]
    return "\n".join(md) + "\n"

# ---------------------------------------------------------------- main
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows のコンソール対策
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="台本の sns: ブロックから投稿文のファイル群を作る")
    ap.add_argument("script", help="台本 YAML")
    ap.add_argument("--out", required=True, help="出力フォルダ")
    ap.add_argument("--publish", help="make_video.py が出した publish.md（説明欄を取り込む）")
    ap.add_argument("--strict", action="store_true", help="警告があれば終了コード 1")
    args = ap.parse_args()

    src = Path(args.script)
    doc = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sns = doc.get("sns") or {}
    has_sns = bool(sns)
    video_url = clean(sns.get("video_url") or doc.get("video_url") or PLACEHOLDER_VIDEO)
    warnings: list[str] = []
    files: list[str] = []

    if not has_sns:
        print("sns: ブロックが無いので、title・publish.lead・question から最低限の投稿を作ります")
        sns = fallback_sns(doc, video_url)

    # X スレッド
    thread = [clean(t) for t in (sns.get("x_thread") or []) if clean(t)]
    if thread:
        n = len(thread)
        if not 5 <= n <= 7:
            warnings.append(f"x_thread: 投稿数 {n}（目安は 5〜7）")
        blocks = []
        for i, t in enumerate(thread, 1):
            body = t if re.search(rf"(?<!\d){i}/{n}(?!\d)", t) else f"{i}/{n}\n{t}"   # 本文に番号があれば足さない
            check_x(f"x_thread {i}/{n}", body, warnings)
            if i < n and URL_RE.search(t):
                warnings.append(f"x_thread {i}/{n}: URL は最後の投稿だけに置く")
            blocks.append(body)
        write(out / "x_thread.txt", "\n---\n".join(blocks))
        files.append("x_thread.txt")

    # X 単発
    for i, t in enumerate((sns.get("x_single") or []), 1):
        t = clean(t)
        if not t:
            continue
        check_x(f"x_single_{i}", t, warnings)
        write(out / f"x_single_{i}.txt", t)
        files.append(f"x_single_{i}.txt")

    # Threads
    for i, t in enumerate((sns.get("threads") or []), 1):
        t = clean(t)
        if not t:
            continue
        check_threads(f"threads_{i}", t, warnings)
        write(out / f"threads_{i}.txt", t)
        files.append(f"threads_{i}.txt")

    # note
    if has_sns:
        nd = note_draft(doc, sns, video_url)
        check_banned("note_draft", nd.split("---- ここから有料")[0], warnings)
        write(out / "note_draft.md", nd)
        files.append("note_draft.md")

    # コミュニティ投稿・固定コメント
    if sns.get("community"):
        t = clean(sns["community"])
        check_banned("community", t, warnings)
        write(out / "community.txt", t)
        files.append("community.txt")
    if sns.get("pinned_comment"):
        t = clean(sns["pinned_comment"])
        check_banned("pinned_comment", t, warnings)
        if "note.com" not in t:
            warnings.append("pinned_comment: note の URL が入っていません")
        write(out / "pinned_comment.txt", t)
        files.append("pinned_comment.txt")

    # 説明欄
    desc = description(doc, sns, Path(args.publish) if args.publish else None)
    check_banned("youtube_description", desc, warnings)
    write(out / "youtube_description.txt", desc)
    files.append("youtube_description.txt")

    # 手順
    write(out / "checklist.md", checklist(doc, files, warnings, has_sns))
    files.append("checklist.md")

    print(f"出力: {out}  ({len(files)} ファイル)")
    for f in files:
        print(f"  {f}")
    for w in warnings:
        print(f"警告: {w}")
    if warnings:
        print(f"警告 {len(warnings)} 件")
    return 1 if (args.strict and warnings) else 0

if __name__ == "__main__":
    sys.exit(main())
