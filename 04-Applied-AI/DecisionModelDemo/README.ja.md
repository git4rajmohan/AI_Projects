言語 / Languages: [English](README.md) | **日本語**

# MaintAI Decision Platform — 保全判断支援プラットフォーム

**機械のセンサーデータから、根拠を説明できる保全判断へ。**

[ポートフォリオ](../../README.ja.md) | [ユーザーガイド（英語）](MaintAI_Userguide.html)

MaintAI は、構造化された判断と生成 AI による説明を分離します。
検証済みのセンサー値と工学的ルールをローカルの TEV1 決定モデルに渡し、
決定論的なポリシーが最終結果を決めます。任意の LLM は、その結果を
上書きせず、根拠を説明する役割だけを担います。

これはローカル環境で動かす判断支援デモであり、機械制御装置、故障予測器、
本番用の安全システムではありません。同梱データはすべて合成データです。
しきい値を実際の設備に使う場合は、設備固有の工学的検証が必要です。

## 実証する機能

- 8 つの Streamlit ページ：設備群ダッシュボード、機械監視、判断ワークベンチ、
  機械台帳、CSV インポート、保全履歴、モデル評価、設定。
- 機械ごとにバージョン管理する温度・振動・モーター負荷の上限値。
- CSV の検証と、受け付けなかったデータの隔離レポート。
- モデル出力、ポリシー結果、信頼度、人によるレビュー要否の分離表示。
- センサー値、判断、点検、監査イベントの SQLite への保存。
- 正解ラベル付き合成データによる正解率、クラス別指標、混同行列の評価。
  合成データでの結果は、本番環境の性能測定値ではありません。
- 根拠に基づく JSON 形式の説明。説明サービスが使えない場合は、
  決定論的な代替説明であることを明示して表示します。

## アーキテクチャ

```text
CSV / 合成センサー値 -> 検証 -> 工学的ルールと傾向分析
  -> TEV1 による分類 -> 決定論的ポリシー -> 判断の保存
  -> 根拠付き LLM 説明 -> 人による点検とレビューの完了
```

ポリシーはモデルの判断を受け入れる前に、不正な入力、強制エスカレーション、
重大しきい値の超過、利用できないモデル出力、低信頼度または矛盾する分類を
優先して処理します。緊急対応の場合も人によるレビューが必要です。

**技術構成：** Python、Streamlit、SQLite、Requests、Pydantic、Pandas、
Plotly、scikit-learn、python-dotenv、pytest、Ollama / Ollama Cloud。

決定サービスは `/api/chat` ではなく、非標準エンドポイント
**`POST /v1/systemone`** を使います。ローカルの Ollama・モデル環境が
このエンドポイントを提供する必要があります。モデルを取得するだけでは
互換性は確認できません。生成 AI の説明サービスは `/api/chat` を使います。

## ローカル実行（Windows PowerShell）

このプロジェクトのディレクトリで実行します。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# ローカルの .env を編集。Ollama Cloud を使う場合だけ OLLAMA_API_KEY を設定。
ollama pull tev1:4b
.\.venv\Scripts\python.exe -m maintai.seed
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m streamlit run maintai\app.py --server.address 127.0.0.1
```

`http://localhost:8501` を開きます。シード処理は 5 台のデモ機械と合成データを
作成し、既存の機械は変更しません。利用できるモデルは環境によって異なります。
ローカルで説明を生成する場合は、`LLM_MODEL` にインストール済みのチャットモデル、
`LLM_BASE_URL` に `http://localhost:11434` を設定します。
この場合、クラウド用のキーは不要です。

### 5 分間の操作例

1. **Machine Monitoring（機械監視）** で機械を選び、測定値と上限値を確認します。
2. 分析を実行し、**Decision Workbench（判断ワークベンチ）** でモデル出力と、
   それとは別のアプリケーション判断を確認します。
3. 説明、根拠、サービスが利用できない場合のメッセージを確認します。
4. **Maintenance History（保全履歴）** で Engineer として点検を記録し、
   レビューを完了します。ダッシュボードの更新も確認します。
5. **Model Evaluation（モデル評価）** で正解ラベル付き合成データによる
   ポリシー評価を実行します。

[maintai/data](maintai/data) にある正常・警告・重大の CSV を順番に取り込むことも
できます。ただし、固定タイムスタンプは古くなっている可能性があります。
実演では現在のタイムスタンプを使うか、データレビューが必要という結果を想定してください。

## 設定とトラブルシューティング

設定は [config/settings.py](config/settings.py) に集約されています。
[.env.example](.env.example) にホスト、モデル名、タイムアウト、信頼度、
傾向分析の設定項目があります。機械固有の上限値は Machine Registry で編集します。
既定値は、すべての設備に適用できる工学的な基準ではありません。

- **インポートエラー：** このプロジェクトのディレクトリで実行し、
  上記のように `PYTHONPATH` を設定してください。
- **Ollama に接続できない：** Ollama を起動し、Settings の接続チェックを使います。
  モデル名に加え、`/v1/systemone` への対応も確認してください。
- **クラウド認証エラー：** ローカルのキーとモデル設定を確認します。
  認証情報を Issue、スクリーンショット、ログに貼り付けないでください。
- **設備データがない：** 合成データを有効にし、`python -m maintai.seed` を実行します。
- **データが古い：** Monitoring で新しい測定値を生成するか、現在のデータを取り込みます。
  古いサンプルを新しく見せるために、鮮度チェックを弱めないでください。

## テスト

```powershell
$env:OLLAMA_API_KEY = "dummy-test-key"
$env:OLLAMA_CLOUD_MODEL = "test-model"
$env:RUN_LIVE_TESTS = "0"
.\.venv\Scripts\python.exe -m pytest tests -q
```

別のターミナルで実行してください。ダミー値はモックを使うテスト専用で、
実際の推論には使いません。既定のテストは HTTP 呼び出しをモック化します。
実サービスのスモークテストは `RUN_LIVE_TESTS=1` で明示的に有効にし、
設定済みで接続可能なモデルサービスを用意する必要があります。

## プロジェクト構成

| パス | 用途 |
|---|---|
| [maintai](maintai) | 現行アプリ、8 ページ、ルール、ポリシー、永続化、シード処理 |
| [config](config) | 環境変数に基づく共通設定 |
| [services](services) | モデルクライアント、結果整形、評価 |
| [prompts](prompts) | 構造化判断用の共通プロンプト |
| [tests](tests) | オフライン回帰テストと任意の実サービスチェック |
| [oldbackup](oldbackup) | アーカイブとして保持した元の Decision + LLM Playground |
| [MaintAI_Userguide.html](MaintAI_Userguide.html) | 図解付きの独立した英語ガイド。ダウンロードしてブラウザーで開けます |

アーカイブの Playground は、LLM のみ、TEV1 + LLM、両者の並列比較の各モードを
提供します。このディレクトリから同じ `PYTHONPATH` を使って実行するには、
次のコマンドを使います。

```powershell
Set-Location oldbackup
..\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## 認証情報と安全上の注意

- 公開するのはキーが空のテンプレートだけです。実際のキーは Git の対象外である
  ローカルの `.env` または環境変数に保存してください。
- 環境設定ファイルの派生版、Streamlit のシークレット、秘密鍵ファイル、
  ローカルデータベース、エクスポート、仮想環境、録画は Git から除外しています。
- この公開版にはスクリーンショットと開発メモを含めていません。
- デモのロール選択は **認証機能ではありません**。アプリは localhost で使い、
  ネットワークに公開したり、アクチュエーターに接続したりしないでください。
