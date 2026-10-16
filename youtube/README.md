# youtube ― チャンネル「小規模な大家」の動画制作一式

| 場所 | 中身 |
|---|---|
| `docs/00_現状診断.md` | いまの動画とチャンネルの何が弱いか（計測値つき） |
| `docs/01_動画設計図.md` | 構成・画・音・字幕の仕様。台本の書き方 |
| `docs/02_制作パイプライン.md` | 台本 → 動画の仕組みと必要なもの |
| `docs/03_公開テンプレート.md` | タイトル・説明欄・サムネ・終了画面・運用 |
| `docs/04_デスクトップ引き継ぎ.md` | デスクトップで最初にやること、Claude Code に貼る指示 |
| `docs/05_シリーズ企画.md` | note の記事に対応させた動画の並び |
| `docs/06_参考チャンネル研究.md` | 伸びている不動産投資系の見せ方と、真似する要素 |
| `docs/07_実例シリーズの作り方.md` | 自分の物件を特定されずに数字で語る線引き、公開前の確認表 |
| `docs/08_事業計画.md` | 収益の見立て、収益化までの道筋、12 週の計画、見る数字 |
| `pipeline/make_video.py` | 台本（YAML）から mp4・サムネ・説明文を作る |
| `pipeline/render_frames.js` | 動き（出現・数字が伸びる・戸建てが増える）を 1 コマずつ撮る（node + Playwright） |
| `scripts/` | 台本。`NNN_題名.yaml`（長尺）、`SNNN_題名.yaml`（ショート） |

台本は `002_50万円の戸建てから.yaml`（実例シリーズ、動きあり）が最新の見本。

最短の使い方:

```bat
pip install -r pipeline\requirements.txt
python pipeline\make_video.py build scripts\001_資料が届かない人.yaml --out out\001
```
