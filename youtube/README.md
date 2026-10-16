# youtube ― チャンネル「小規模な大家」の動画制作一式

| 場所 | 中身 |
|---|---|
| `docs/00_現状診断.md` | いまの動画とチャンネルの何が弱いか（計測値つき） |
| `docs/01_動画設計図.md` | 構成・画・音・字幕の仕様。台本の書き方 |
| `docs/02_制作パイプライン.md` | 台本 → 動画の仕組みと必要なもの |
| `docs/03_公開テンプレート.md` | タイトル・説明欄・サムネ・終了画面・運用 |
| `docs/04_デスクトップ引き継ぎ.md` | デスクトップで最初にやること、Claude Code に貼る指示 |
| `docs/05_シリーズ企画.md` | note の記事に対応させた動画の並び |
| `pipeline/make_video.py` | 台本（YAML）から mp4・サムネ・説明文を作る |
| `scripts/` | 台本。`NNN_題名.yaml`（長尺）、`SNNN_題名.yaml`（ショート） |

最短の使い方:

```bat
pip install -r pipeline\requirements.txt
python pipeline\make_video.py build scripts\001_資料が届かない人.yaml --out out\001
```
