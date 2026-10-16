#!/usr/bin/env python3
"""make_posts.py ― 台本（YAML）の `sns:` ブロックから、各媒体の投稿文ファイルを作る。

使い方:
  python make_posts.py scripts/002_xxx.yaml --out out/002/sns [--publish out/002/publish.md] [--strict]

出力（--out の中）:
  x_thread.txt          X のスレッド（投稿ごとに --- 区切り、番号付き。最後の投稿に動画 URL を自動で付ける）
  x_single_1.txt …      X の単発（1 本目に動画 URL を自動で付ける）
  threads_1.txt …       Threads（本文に URL は入れない。返信に貼る）
  note_draft.md         note 記事の下書き（骨子を見出しに。無料部分は台本の数字・台詞から自動で要約。有料ラインあり）
  community.txt         YouTube コミュニティ投稿（4 択クイズ。1 行目が質問、①〜④ が選択肢、最後の行が本文）
  pinned_comment.txt    固定コメント
  youtube_description.txt  説明欄（1 行目は結論、2 行目に note の具体物＋記事 URL、連載の再生リスト、次回、
                        publish.md があれば目次、免責は 1 回、VOICEVOX）
  checklist.md          公開日の手順と、置き換える印の一覧と、検査の結果

URL（docs/13 §2.3: 外に貼る動画 URL は常に再生リスト付き）:
  台本の youtube_url:（動画）と playlist_url:（連載の再生リスト）から https://youtu.be/ID?list=PL… を作り、
  X スレッドの最後と X 単発 1 に自動で付ける。未定なら {{YOUTUBE_URL}}・{{PLAYLIST_URL}} のまま出し、
  checklist.md に「公開後に置き換える」を書く。本文の中の {{YOUTUBE_URL}}・{{PLAYLIST_URL}}・{{NOTE_URL}} も、
  分かっている値に置き換える。

sns: のキー（docs/12 §7 ＋ docs/14 §8）:
  x_thread（5〜7 本）, x_single（3 本）, threads（2 本）,
  note_outline{title, free[], paid[], paid_contents（有料部の先頭に書く「何が何個」）, price},
  community（文章）または community_quiz{q, choices[4], answer_in}（両方あればクイズ）,
  pinned_comment, note_url（記事の URL。未定なら …/n/XXXXXXXX）, note_items（説明欄に書く note の具体物）,
  series（連載名）, next_video（次回の題）

検査:
  X は 1 投稿の重み付き文字数（全角＝2、半角＝1、URL＝23）が 280 を超えたら警告。Threads は 500 字。
  禁止語（簡単・誰でも・確実・必ず・不労所得・儲かる）を含んだら警告（「簡単ではない」の形は除外）。
  「今夜」「明日の夜」など、予約公開（土 7:00、docs/14 §6）と合わない時刻の言い方を含んだら警告。
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
PUBLISH_DOW, PUBLISH_HOUR = "土", 7     # 予約公開（docs/14 §6）。投稿文の時刻の言い方はこれに合わせる
BANNED = ["簡単", "誰でも", "確実", "必ず", "不労所得", "儲かる"]
BANNED_EXEMPT = re.compile(r"簡単(では|じゃ|には)")   # 「簡単ではない」は口癖として許す（docs/09）
NIGHT_WORDS = ["今夜", "今晩", "今日の夜", "明日の夜", "夜に公開", "夜公開"]   # 朝 7:00 の予約公開と矛盾する言い方

PH_VIDEO, PH_PLAYLIST, PH_NOTE = "{{YOUTUBE_URL}}", "{{PLAYLIST_URL}}", "{{NOTE_URL}}"
NOTE_MARK = "XXXXXXXX"                                  # note 記事 URL の置換印（…/n/XXXXXXXX）
FIXED_LEGAL = "個別のご相談・物件のご紹介は承っておりません。"

_URL_CHARS = r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]"   # 全角文字の手前で URL が終わる
URL_RE = re.compile(r"https?://" + _URL_CHARS + r"+|\{\{[A-Z_]+\}\}" + _URL_CHARS + r"*")
VIDEO_URL_RE = re.compile(r"youtu\.be/|youtube\.com/|\{\{YOUTUBE_URL\}\}")
NUM_TAIL = re.compile(r"\s*[（(]\d+/\d+[)）]\s*$")       # 投稿末尾の（6/6）

# ---------------------------------------------------------------- 文字の扱い
def clean(text) -> str:
    """★ を消し、前後の空白を落とす（★ は本人確認用の印。投稿文には出さない）。"""
    return re.sub(r"\s*★\s*", "", str(text or "")).strip()

def x_weight(text: str) -> int:
    """X の重み付き文字数。URL（置換印も）は 23、全角（CJK・絵文字など）は 2、半角は 1。"""
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

def fmt_num(x: float) -> str:
    return f"{x:,.10g}"

# ---------------------------------------------------------------- URL
def resolve_urls(doc: dict, sns: dict) -> dict[str, str]:
    """video: 再生リスト付きの動画 URL ／ playlist: 再生リストの URL ／ note: 記事の URL。未定なら置換印。"""
    video = clean(doc.get("youtube_url") or sns.get("youtube_url") or sns.get("video_url") or doc.get("video_url") or "")
    pl = clean(doc.get("playlist_url") or sns.get("playlist_url") or "")
    m = re.search(r"list=([A-Za-z0-9_-]+)", pl)
    list_id = m.group(1) if m else (pl if re.fullmatch(r"[A-Za-z0-9_-]{10,}", pl) else "")
    playlist = f"https://www.youtube.com/playlist?list={list_id}" if list_id else PH_PLAYLIST
    if not video:
        video = PH_VIDEO
    if list_id and "list=" not in video:
        video += ("&" if "?" in video else "?") + f"list={list_id}"
    note = clean(sns.get("note_url") or doc.get("note_url") or "") or PH_NOTE
    return {"video": video, "playlist": playlist, "note": note, "list_id": list_id}

def make_filler(urls: dict[str, str]):
    """本文の {{YOUTUBE_URL}}・{{PLAYLIST_URL}}・{{NOTE_URL}} を分かっている値に置き換える関数を返す。"""
    def fill(text: str) -> str:
        text = re.sub(r"\{\{YOUTUBE_URL\}\}(?![?&]list=)", lambda m: urls["video"], text)
        if urls["playlist"] != PH_PLAYLIST:
            text = text.replace(PH_PLAYLIST, urls["playlist"])
        if urls["note"] != PH_NOTE:
            text = text.replace(PH_NOTE, urls["note"])
        return text
    return fill

def with_video_url(text: str, url: str) -> str:
    """動画 URL が無ければ「▶ URL」を足す。末尾の（6/6）は URL のあとに残す。"""
    if VIDEO_URL_RE.search(text):
        return text
    m = NUM_TAIL.search(text)
    if m:
        return f"{text[:m.start()].rstrip()}\n▶ {url} {m.group().strip()}"
    return f"{text}\n▶ {url}"

def legal_lines(doc: dict) -> list[str]:
    """免責の行。disclaimer に「個別のご相談…」が入っていれば、同じ文を 2 回出さない。"""
    d = clean(doc.get("disclaimer", "登場人物・数字・例文は説明のための架空の設定です。"))
    if d and not d.endswith(("。", "．", ".")):
        d += "。"
    out = [d] if d else []
    if "個別のご相談" not in d:
        out.append(FIXED_LEGAL)
    return out

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
        md.append(f"{label}{n}戸 × 月{fmt_num(rent)}万円 ＝ 月{fmt_num(month)}万円（年{fmt_num(month * 12)}万円）の計算")
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
    return {"id": scene.get("id", ""), "layout": lay, "heading": heading, "chapter": chapter, "md": "\n".join(md),
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
def note_draft(doc: dict, sns: dict, urls: dict[str, str], warnings: list[str]) -> str:
    outline = sns.get("note_outline", {}) or {}
    title = clean(outline.get("title") or doc.get("title", ""))
    price = outline.get("price", 500)
    blocks = build_blocks(doc)
    endings = [b for b in blocks if b["layout"] == "ending"]          # 「今日の一歩」は無料部の最後に置く
    blocks = [b for b in blocks if b["layout"] != "ending"]
    used: set[str] = set()
    lead = clean((doc.get("publish") or {}).get("lead", ""))
    md = [f"# {title}", "", f"（YouTube の埋め込み: この行に再生リスト付きの動画 URL を貼る → {urls['video']}）", ""]
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
    for b in endings:
        md += [b["md"], ""]
    md += [f"---- ここから有料（{price}円）----", ""]
    paid = outline.get("paid") or ["一覧・内訳（有料）"]
    contents = clean(outline.get("paid_contents", ""))
    if not contents:
        contents = "／".join(clean(h) for h in paid)
        if outline:
            warnings.append("note_outline.paid_contents が無い（有料部の先頭に「何が何個入っているか」を 1 行で書く。docs/14 §4.2）")
    md += [f"この先に入っているもの: {contents}", ""]
    for h in paid:
        md += [f"## {clean(h)}", "", "- （ここに書く。一覧なら項目ごとに見方・NG 例、内訳なら金額の行、失敗なら時系列）", ""]
    md += legal_lines(doc) + [""]
    return "\n".join(md)

# ---------------------------------------------------------------- 説明欄
def toc_from_publish(publish_md: Path | None) -> list[str]:
    """make_video.py の publish.md から「▼目次」の塊だけを取り込む。"""
    if not (publish_md and publish_md.exists()):
        return []
    m = re.search(r"## 説明文.*?\n```\n(.*?)\n```", publish_md.read_text(encoding="utf-8"), re.S)
    if not m:
        return []
    lines = m.group(1).split("\n")
    if "▼目次" not in lines:
        return []
    out = []
    for ln in lines[lines.index("▼目次"):]:
        if not ln.strip():
            break
        out.append(ln)
    return out

def description(doc: dict, sns: dict, urls: dict[str, str], publish_md: Path | None) -> str:
    """docs/03・docs/13 §6.1 の順: 結論 → note（具体物＋記事 URL）→ 連載の再生リスト → 次回 → 目次 → 免責（1 回）→ VOICEVOX。"""
    lead = clean(sns.get("lead") or (doc.get("publish") or {}).get("lead") or doc.get("title", ""))
    is_long = doc.get("kind", "long") != "short"
    desc = [lead, ""]
    items = [clean(x) for x in (sns.get("note_items") or []) if clean(x)]
    if items:
        desc.append(f"▼ note: {'／'.join(items)} {urls['note']}")
    elif is_long and urls["note"] != PH_NOTE:
        desc.append(f"▼ note: この回の表と一覧 {urls['note']}")
    series = clean(sns.get("series") or doc.get("series") or "")
    if is_long or urls["playlist"] != PH_PLAYLIST:
        desc.append(f"▼ 連載{'「' + series + '」' if series else ''}の再生リスト {urls['playlist']}")
    if sns.get("next_video"):
        desc.append(f"▼ 次回: {clean(sns['next_video'])}（毎週{PUBLISH_DOW}曜 {PUBLISH_HOUR}:00）")
    if len(desc) > 2:
        desc.append("")
    toc = toc_from_publish(publish_md)
    if toc:
        desc += toc + [""]
    desc += legal_lines(doc)
    voices = "、".join(f"VOICEVOX:{sp.get('speaker', sp.get('name', ''))}" for sp in (doc.get("speakers") or {}).values())
    if voices:
        desc.append(f"音声は合成音声です。{voices}")
    if doc.get("bgm_credit"):
        desc.append(f"BGM: {doc['bgm_credit']}")
    return "\n".join(desc) + "\n"

# ---------------------------------------------------------------- コミュニティ投稿
def community_text(sns: dict, warnings: list[str]) -> str:
    """community_quiz{q, choices, answer_in} があれば 4 択クイズに。無ければ community の文章をそのまま。"""
    quiz = sns.get("community_quiz")
    if not quiz and isinstance(sns.get("community"), dict):
        quiz = sns["community"]
    if not isinstance(quiz, dict):
        return clean(sns.get("community", ""))
    q = clean(quiz.get("q") or quiz.get("question", ""))
    choices = [clean(c) for c in (quiz.get("choices") or []) if clean(c)]
    if not q or not choices:
        warnings.append("community_quiz: q と choices が要ります")
    if len(choices) != 4:
        warnings.append(f"community_quiz: 選択肢が {len(choices)} 個（docs/13 §9.2 は 4 択）")
    marks = "①②③④⑤"
    lines = [q] + [f"{marks[i]} {c}" for i, c in enumerate(choices[:5])]
    ans = clean(quiz.get("answer_in", ""))
    when = f"明日の朝{PUBLISH_HOUR}時に公開する動画で"
    closing = clean(quiz.get("closing") or f"答えは{when}{'（' + ans + '）' if ans else ''}。先に聞きたいことがあれば、ここに書いておいてください。")
    return "\n".join(lines + [closing])

# ---------------------------------------------------------------- 最低限の投稿（sns が無いとき）
def fallback_sns(doc: dict) -> dict:
    pub = doc.get("publish") or {}
    lead = clean(pub.get("lead") or doc.get("title", ""))
    q = clean(doc.get("question", ""))
    single = (f"{q}\n" if q else "") + lead
    if x_weight(single) + URL_WEIGHT + 3 > X_LIMIT:    # 動画 URL（▶ URL）があとから付く
        single = lead
    pinned = "\n".join(x for x in [
        f"この回の問い:「{q}」" if q else "",
        f"詳しい数字と一覧は note にまとめています → {PH_NOTE}",
        f"連載の再生リスト → {PH_PLAYLIST}",
        *[ln for ln in legal_lines(doc) if "個別のご相談" not in ln],
        "個別のご相談・物件のご紹介は承っておりませんが、動画の内容への質問はこのコメント欄にどうぞ。",
    ] if x)
    return {"x_single": [single], "pinned_comment": pinned}

# ---------------------------------------------------------------- 検査
def check_x(label: str, text: str, warnings: list[str]):
    w = x_weight(text)
    if w > X_LIMIT:
        warnings.append(f"{label}: X の重み付き文字数 {w} が {X_LIMIT} を超えています（全角 {X_LIMIT // 2} 字相当）")
    check_banned(label, text, warnings)
    check_time(label, text, warnings)

def check_threads(label: str, text: str, warnings: list[str]):
    if len(text) > THREADS_LIMIT:
        warnings.append(f"{label}: Threads の文字数 {len(text)} が {THREADS_LIMIT} を超えています")
    if not text.rstrip().endswith(("？", "?")):
        warnings.append(f"{label}: Threads は答えやすい問いで終える（末尾が ？ ではありません）")
    if URL_RE.search(text):
        warnings.append(f"{label}: Threads の本文に URL を入れない（問いで終える投稿の URL は返信に。docs/14 §3.2）")
    check_banned(label, text, warnings)
    check_time(label, text, warnings)

def check_banned(label: str, text: str, warnings: list[str]):
    hit = find_banned(text)
    if hit:
        warnings.append(f"{label}: 禁止語を含んでいます → {'、'.join(hit)}")

def check_time(label: str, text: str, warnings: list[str]):
    hit = [w for w in NIGHT_WORDS if w in text]
    if hit:
        warnings.append(f"{label}: 「{'、'.join(hit)}」は予約公開（{PUBLISH_DOW} {PUBLISH_HOUR}:00、docs/14 §6）と合いません。朝の公開に合わせた言い方に")

# ---------------------------------------------------------------- 書き出し
def write(path: Path, text: str):
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")

def placeholders_in(outputs: dict[str, str]) -> list[tuple[str, str, list[str]]]:
    """(印, 置き換えるもの, 入っているファイル) の一覧。"""
    kinds = [
        (PH_VIDEO, "動画の URL（https://youtu.be/ID。再生リストの ?list=… は付けてある）。予約を入れた時点で決まる。台本に youtube_url: を書いて作り直してもよい"),
        (PH_PLAYLIST, "連載の再生リストの URL（https://www.youtube.com/playlist?list=PL…）。台本に playlist_url: を書けば自動で入る"),
        (PH_NOTE, "note 記事の URL。台本の sns.note_url: に書けば自動で入る"),
        (NOTE_MARK, "note 記事の URL の末尾（公開した記事の …/n/ 以降）"),
    ]
    out = []
    for mark, what in kinds:
        files = [f for f, t in outputs.items() if mark in t]
        if files:
            out.append((mark, what, files))
    return out

def checklist(doc: dict, files: list[str], warnings: list[str], has_sns: bool, outputs: dict[str, str], is_quiz: bool) -> str:
    h = PUBLISH_HOUR
    md = [f"# 公開日の手順  {doc.get('id', '')}  {clean(doc.get('title', ''))}", "",
          "生成したファイル: " + "、".join(files), ""]
    pend = placeholders_in(outputs)
    md.append("## 置き換える印（公開後に置き換える）")
    if pend:
        md += [f"- [ ] `{mark}` → {what}: {'、'.join(fs)}" for mark, what, fs in pend]
    else:
        md.append("- なし（URL は全部入っている）")
    md += ["",
           "## 前日（金）",
           f"- [ ] note 記事を公開し、記事の URL（…/n/ 以降）を上の印の所に入れる",
           "- [ ] note の「X で共有」で記事を X に流す（1 行目は記事の結論）",
           f"- [ ] 動画を {PUBLISH_DOW} {h}:00 で予約し、URL が決まったら `{PH_VIDEO}` を置き換える（再生リストに動画を入れる）",
           "- [ ] 21:00 community.txt をコミュニティ投稿" + ("（投票で: 1 行目が質問、①〜④ が選択肢、最後の行は本文。答えの時刻は完成版の mp4 で確かめる）" if is_quiz else "（クイズ形式なら sns.community_quiz に書き直す。docs/13 §9.2）")
           if has_sns else "- [ ] 21:00 コミュニティ投稿で 4 択クイズ（sns ブロックが無いので手で書く。docs/13 §9.2）",
           "", f"## 公開日（{PUBLISH_DOW}）",
           f"- [ ] {h}:00 公開（予約）。youtube_description.txt の 1 行目が結論、2 行目が note の具体物＋記事 URL になっているか確認",
           f"- [ ] {h}:05 pinned_comment.txt を貼って固定",
           f"- [ ] {h}:30 x_single_1.txt を投稿（末尾の ▶ が再生リスト付きの動画 URL になっているか確認）" + ("。threads_1.txt を投稿し、自分の返信に動画 URL を貼る" if has_sns else ""),
           "- [ ] 12:15 x_thread.txt を投稿（URL は最後の投稿だけ。動画と note）。本文の時刻は完成版の mp4 で確かめる" if has_sns else "- [ ] 12:15 X に要約を 1 本（sns ブロックが無いので手で書く）",
           "- [ ] 21:00 コメントに全部返信。クリック率を見る（4％未満なら翌朝サムネ差し替え）",
           "", "## 翌日（日）",
           f"- [ ] {h}:30 ショート 1 を公開（関連動画に長尺を指定）。x_single_2.txt を投稿" if has_sns else f"- [ ] {h}:30 ショート 1 を公開（関連動画に長尺を指定）",
           "- [ ] 21:00 X・Threads・YouTube の返信。平均視聴時間を見る（冒頭 30 秒で 30％落ちていれば次回のフックを直す）",
           "", "## 3 日後（火）",
           "- [ ] x_single_3.txt、threads_2.txt を投稿。ショート 2〜3 は月・水" if has_sns else "- [ ] ショート 2〜3 は月・水",
           "- [ ] コミュニティ投稿でクイズの答えと「よくある質問」への返答（docs/14 §5）",
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
    ap.add_argument("--publish", help="make_video.py が出した publish.md（説明欄の目次を取り込む）")
    ap.add_argument("--strict", action="store_true", help="警告があれば終了コード 1")
    args = ap.parse_args()

    src = Path(args.script)
    doc = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sns = doc.get("sns") or {}
    has_sns = bool(sns)
    if not has_sns:
        print("sns: ブロックが無いので、title・publish.lead・question から最低限の投稿を作ります")
        sns = fallback_sns(doc)
    urls = resolve_urls(doc, sns)
    fill = make_filler(urls)
    warnings: list[str] = []
    files: list[str] = []
    outputs: dict[str, str] = {}

    def emit(name: str, text: str):
        write(out / name, text)
        files.append(name)
        outputs[name] = text

    # X スレッド（最後の投稿に再生リスト付きの動画 URL）
    thread = [fill(clean(t)) for t in (sns.get("x_thread") or []) if clean(t)]
    if thread:
        n = len(thread)
        if not 5 <= n <= 7:
            warnings.append(f"x_thread: 投稿数 {n}（目安は 5〜7）")
        thread[-1] = with_video_url(thread[-1], urls["video"])
        blocks = []
        for i, t in enumerate(thread, 1):
            body = t if re.search(rf"(?<!\d){i}/{n}(?!\d)", t) else f"{i}/{n}\n{t}"   # 本文に番号があれば足さない
            check_x(f"x_thread {i}/{n}", body, warnings)
            if i < n and URL_RE.search(t):
                warnings.append(f"x_thread {i}/{n}: URL は最後の投稿だけに置く")
            blocks.append(body)
        emit("x_thread.txt", "\n---\n".join(blocks))

    # X 単発（1 本目に再生リスト付きの動画 URL）
    singles = [fill(clean(t)) for t in (sns.get("x_single") or []) if clean(t)]
    if singles:
        singles[0] = with_video_url(singles[0], urls["video"])
    for i, t in enumerate(singles, 1):
        check_x(f"x_single_{i}", t, warnings)
        emit(f"x_single_{i}.txt", t)

    # Threads（URL は返信に貼るので本文には付けない）
    for i, t in enumerate((sns.get("threads") or []), 1):
        t = fill(clean(t))
        if not t:
            continue
        check_threads(f"threads_{i}", t, warnings)
        emit(f"threads_{i}.txt", t)

    # note（骨子があるとき、または長尺）
    if has_sns and (sns.get("note_outline") or doc.get("kind", "long") != "short"):
        nd = note_draft(doc, sns, urls, warnings)
        check_banned("note_draft", nd.split("---- ここから有料")[0], warnings)
        emit("note_draft.md", nd)

    # コミュニティ投稿（4 択クイズ）・固定コメント
    ct = fill(community_text(sns, warnings))
    is_quiz = isinstance(sns.get("community_quiz"), dict) or isinstance(sns.get("community"), dict)
    if ct:
        check_banned("community", ct, warnings)
        check_time("community", ct, warnings)
        emit("community.txt", ct)
    if sns.get("pinned_comment"):
        t = fill(clean(sns["pinned_comment"]))
        check_banned("pinned_comment", t, warnings)
        if "note.com" not in t and PH_NOTE not in t:
            warnings.append("pinned_comment: note の URL が入っていません")
        elif "note.com" in t and "/n/" not in t:
            warnings.append(f"pinned_comment: note の URL がトップページです（記事の URL …/n/{NOTE_MARK} にして、公開後に置き換える）")
        emit("pinned_comment.txt", t)

    # 説明欄
    desc = description(doc, sns, urls, Path(args.publish) if args.publish else None)
    check_banned("youtube_description", desc, warnings)
    check_time("youtube_description", desc, warnings)
    emit("youtube_description.txt", desc)

    # 手順
    write(out / "checklist.md", checklist(doc, files, warnings, has_sns, outputs, is_quiz))
    files.append("checklist.md")

    print(f"出力: {out}  ({len(files)} ファイル)")
    for f in files:
        print(f"  {f}")
    if urls["video"] == PH_VIDEO or urls["playlist"] == PH_PLAYLIST:
        print(f"動画 URL: {urls['video']} ／ 再生リスト: {urls['playlist']}（未定の印は checklist.md の「置き換える印」を見る）")
    for w in warnings:
        print(f"警告: {w}")
    if warnings:
        print(f"警告 {len(warnings)} 件")
    return 1 if (args.strict and warnings) else 0

if __name__ == "__main__":
    sys.exit(main())
