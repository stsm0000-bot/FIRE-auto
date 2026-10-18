---
name: make-video
description: チャンネル「小規模な大家」の動画を 1 本作る（題材決め → 台本 → 音声なしの試し → ★の確認 → 本番ビルド → 投稿文 → アップロードの案内）。「次の動画を作って」「003 を作って」「/make-video 題名」のときに使う。
argument-hint: "[題名や番号（省略すると docs/15 §9.2 の次の回）]"
---

# 動画を 1 本作る（小規模な大家）

手順の本体は `youtube/docs/16_動画1本の作り方.md`。この順で進める。毎回の決まりはリポジトリ直下の `CLAUDE.md`。

## 0. 準備（毎回）

1. `git pull origin claude/fervent-edison-ffigc4`。
2. `youtube/はじめに読む.md` の §C（決まっていること）を確かめる。
3. VOICEVOX が起動しているか（http://127.0.0.1:50021/version）。していなければ本人に起動を頼む（試しは `--tts stub` で先に進めてよい）。
4. 空き容量を見る。少なければ `youtube/out/` の古い回の `work/` を消してよいか本人に聞く。

## 1. 題材（本人が選ぶ）

- 引数があればそれを題材にする。無ければ `docs/15_引き継ぎ書.md` §9.2 の次の回（前回の次回予告）。
- タイトル 3 案・問い・サムネの文字（2 行 10 字以内）を**チェックボックス形式**で本人に出して選んでもらう。
- 探し方そのものを主題にしない（note の役目）。

## 2. 台本

- `youtube/scripts/_ひな形_長尺.yaml` をコピーして `NNN_題名.yaml`、`_ひな形_ショート.yaml` から `SNNN_題名.yaml` を 3 本。番号は既存の最大＋1。
- 完成見本は `scripts/002_50万円の戸建てから.yaml`。約 10 分（35 場面・台詞 140 本前後）まで肉付けする。
- docs/16 §2 の決まり（モデルケース・管理費・手数料・note へ 2 回送る・禁止語・1 台詞 45 字まで・場面と図解を交互・★は冒頭コメント）を守る。

## 3. 試し（音声なし）

```bat
cd youtube
python pipeline\make_all.py scripts\NNN_….yaml scripts\SNNN_….yaml … --tts stub
```

- 尺（長尺 9:30〜10:30・ショート 59 秒以内）と「同じ画が 8 秒超」を直す。コマを見て札の重なり・改行の崩れを直す（docs/16 §9）。

## 4. ★の確認（本人）

- 台本冒頭の ★ を、チェックボックス形式で本人に確かめてもらう。答えを台本に反映する。

## 5. 本番

```bat
python pipeline\make_all.py scripts\NNN_….yaml scripts\SNNN_….yaml …
```

- 全部 QA 合格・投稿文の警告 0 になるまで直す。
- `out\<id>\納品\字幕の時刻.txt` で山場の時刻を見て、台本の `sns:` の時刻（x_thread の最後・x_single・community_quiz.answer_in）を合わせ、もう一度 `make_all.py`。

## 6. 本人に渡す

- `out\<id>\納品\` の mp4・サムネ・コマ一覧を本人に見せ、見てほしい時刻を添える。直しがあれば 2 へ。
- OK が出たら台本をコミットして push（ブランチ `claude/fervent-edison-ffigc4`。メッセージは日本語）。

## 7. アップロードと SNS の案内

- docs/16 §7（YouTube Studio の設定・予約・改変コンテンツ）と §8（`投稿文\checklist.md` の時刻どおり）を、本人と 1 つずつ進める。投稿ボタンは本人が押す。
- 動画 URL・note の記事 URL が決まったら台本の `youtube_url:`・`sns.note_url` に書き、`make_all.py` で投稿文を作り直す。

## 8. 記録

- 48 時間の数字を docs/14 §7 の表に 1 行。docs/15 §9.2 の次の回を更新してコミット。
