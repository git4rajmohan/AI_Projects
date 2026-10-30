言語 / Languages: [English](README.md) | **日本語**

# VisionFlow — AI 動画物体検出・トラッキング・カウント

**映像のフレームを、数えられた追跡対象へ。**

[ポートフォリオ](../../README.ja.md) | [ユーザーガイド（英語）](VisionFlow_Userguide.html)

VisionFlow は、アップロードされた動画を Ultralytics YOLO11 検出器に通し、
ByteTrack / BoT-SORT によってフレームをまたいで物体を恒久的なトラック ID で
追跡し、2 つの異なる方法で数えます。**現在フレーム内の物体数（current）**と、
**実行全体で見られた distinct なトラック ID 数（unique）**です。
フレームごとの検出を単純合計することはありません。40 フレームに映る 1 台の車は、
40 台ではなく 1 台です。

## デモ動画
[![yoloTrafficVechileCounterDemoVideo](https://img.youtube.com/vi/32d_BhMKsZw/0.jpg)](https://youtu.be/32d_BhMKsZw)

## このプロジェクトの目的

「1 時間の交通動画に映る車を数えて」と頼むと、人は同じ車を何度も数えてしまいます。
ナイーブなスクリプト修正 — フレームごとの検出を合計する — はさらに悪く、
同じ車が 40 回数えられます。本当に必要なのは、どの検出が同一の物理オブジェクトに
属するかを識別できるカウンターです。VisionFlow はそのカウンターです。
検出器が物体を見つけ、トラッカーが同一性を与え、カウンターは
フレームごとの生の検出ではなく、その同一性だけを信頼します。

## 実証する機能

- ストリーミング処理パイプライン — アップロードから注釈付き出力まで、
  常に 1 フレームずつ処理します。動画全体を RAM に載せないため、
  長い動画も短い動画と同じ要領で処理できます。
- 検出 → トラッキング → カウントの分離。YOLO が検出し、
  ByteTrack / BoT-SORT がフレーム間の同一性を維持し、カウンターは
  「このフレームに見える数」と「累積の distinct オブジェクト数」を
  別の指標として扱います。
- 注釈付きフレーム上の恒久的なトラック ID。`CAR #12 0.87` 形式のラベルと
  リアルタイムのカウント HUD を表示します。
- 実行ごとの `.jsonl` サイドカーファイル — 出力フレームごとに 1 行の検出記録。
  フレームビューアーがこの記録をそのまま再生するため、モデルを再実行せずに
  実行結果を監査できます。
- 交換可能な継ぎ目（seam）。トラッカーは 2 メソッドのインターフェース
  （`update`/`reset`）の背後にあり、トラッカーの変更は 1 クラスの追加だけで、
  他のコードは変更不要です。
- 型付きエラー（`VideoValidationError`、`ModelError`、`TrackerError`、
  `VideoWriteError`）は 1 文のわかりやすいメッセージを UI に表示し、
  技術的な詳細はログにのみ記録されます。

## アーキテクチャ

```text
アップロード (.mp4/.avi/.mov/.mkv) -> 検証 + メタデータ
  -> YOLO 検出/トラッキング (1 フレームずつストリーミング)
  -> フィルター (信頼度、クラス、最小ボックス面積)
  -> カウンター (current + unique、トラック ID 経由)
  -> アノテーター (ボックス、CLASS #ID conf、カウント HUD)
  -> 注釈付き動画 + .jsonl サイドカー
  -> ダッシュボード: 統計、カウント表、チャート、フレームビューアー
```

すべての概念が 1 つのモジュールを持ちます。`process_video()` はそれらを
ジェネレーターとして組み合わせ、実行が中断されても reader・writer・
tracker を確実に解放します。詳細は
[docs/architecture.md](docs/architecture.md)（英語）を参照してください。

**技術構成：** Python 3.11+ · Streamlit · Ultralytics YOLO11 (n/s/m) ·
OpenCV · ByteTrack / BoT-SORT · NumPy · Pandas · pytest

## ローカル実行（Windows PowerShell）

このプロジェクトのディレクトリで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# GPU の場合（任意）: CUDA 版 PyTorch を強制インストールします
# （pip が CPU 版で「インストール済み」と表示しても、それでは不十分です）:
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install "setuptools<82"
.\.venv\Scripts\streamlit.exe run app.py
# -> http://localhost:8501
```

PATH 上に `ffmpeg` があると、出力動画が H.264 に再エンコードされ、
ブラウザーでインライン再生できます。なくてもダウンロードは機能します。
初回実行時に YOLO の重みが自動ダウンロードされます。

### 5 分間の操作例

1. サイドバーで動画をアップロードすると、解像度・FPS・フレーム数の
   検証カードが表示されます。
2. モデル・しきい値・クラスを選び、**Start Processing** を押します。
3. ライブフレーム、統計、2 つのカウント表（Current / Unique）が更新されます。
4. 注釈付き動画を再生またはダウンロードし、カウントのチャートを確認します。
5. フレームビューアーで任意のフレームをめくり、記録済みの検出内容を確認します。

## 設定（`.env`）

| 変数 | 既定値 | 意味 |
|---|---|---|
| `MODEL_NAME` | `yolo11n.pt` | Ultralytics の重みファイル |
| `CONFIDENCE_THRESHOLD` | `0.50` | 信頼度スライダーの初期値 |
| `IOU_THRESHOLD` | `0.50` | IoU スライダーの初期値 |
| `DEVICE` | `auto` | `auto`（CUDA があれば GPU、なければ CPU）、`cpu`、`cuda` |
| `TRACKER` | `bytetrack` | `bytetrack` または `botsort` |
| `OUTPUT_DIR` | `data/output` | 注釈付き動画とサイドカーの出力先 |

`OLLAMA_*` 変数は post-MVP の LLM インサイト層用の予約です。
MVP では検出やカウントに LLM を使いません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest
```

公開版で 50 テストの合格を確認済みです。テストスイートはオフラインで、
GPU・モデルダウンロード・インターネット接続を必要としません。
カウント（current と unique の分離）、重複 ID の除去、クラス分離、
注釈ラベル、動画検証、writer の解放、フレームスキップのマッピング、
フレームビューアーをカバーします。

## 制限事項

- トラック ID は 1 回の実行内でのみ安定しており、実行をまたぐと
  リセットされます。
- オクルージョンや低信頼度でトラッカーが物体を見失い、再取得すると、
  unique カウントは過大になることがあります。これを解消する
  ライン横断カウント（post-MVP）は意図的に未実装です。
- フレームスキップは処理を速くしますが、ID の切断と過大カウントを
  増やします。アプリは画面上で警告を表示します。

## 認証情報と安全上の注意

- 公開するのはプレースホルダーキーのテンプレート（`.env.example`）だけです。
  実際の `.env` は Git の対象外で、この公開コピーには含めていません。
- 処理してよい動画は、利用が許可されたものだけにしてください。このツールを
  認証・アクセス制御・ストリーム制限の回避に使わないでください。人物が映る
  映像を分析するときは、プライバシーと現地の法律を尊重してください。

## プロジェクト構成

| パス | 用途 |
|---|---|
| [app.py](app.py) | Streamlit ページの配線 |
| [config](config) / [models](models) | 設定、YOLO モデルマネージャー |
| [detection](detection) / [tracking](tracking) / [counting](counting) | 検出 dataclass + フィルター、トラッカーインターフェース + 状態、カウンター + 統計 |
| [video](video) / [visualization](visualization) | reader・writer・パイプライン、アノテーター・ダッシュボード・フレームビューアー |
| [tests](tests) | オフラインの pytest スイート |
| [docs/architecture.md](docs/architecture.md) | パイプライン図とモジュールの責務（英語） |
| [VisionFlow_Userguide.html](VisionFlow_Userguide.html) | 図解付きの独立した英語ガイド。ダウンロードしてブラウザーで開けます |
