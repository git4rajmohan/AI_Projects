言語 / Languages: [English](README.md) | **日本語**

---

# 🛡️ AI 安全型サポートチケット分類機能

**ライブパイプラインビジュアライザー付きの実運用レベル AI チケットトリアージ — LLM 分類器の周りに安全レール（PII マスキング、プロンプトインジェクションガード、検証、フォールバック）を施し、各ノードの出力を UI で確認できます。**

## デモ動画

[![Safe Support Ticket Demo](https://img.youtube.com/vi/KqG39BdxUxc/0.jpg)](https://youtu.be/KqG39BdxUxc)

## なぜこのプロジェクトが存在するのか

安全性を単独のデモとしてではなく、実務的な AI ビジネスワークフローに埋め込まれたセキュリティコントロールとして示すプロジェクトです — モデルがデータを見る前に PII をマスキングし、専任の判定用 LLM がインジェクションの試みを拒否します。

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C?logo=langgraph&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama_Cloud_gpt--oss:120b-654438?logo=ollama&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-8%2F8_passing-4ade80)
![License](https://img.shields.io/badge/License-MIT-blue)

---

## 📌 概要

多くの LLM デモは「プロンプトを入れれば答えが出る」で終わります。このプロジェクトは**欠けている本番レイヤー**を構築します。LangGraph パイプラインの各ステージが厳格で監査可能な境界として機能し — 個人データはモデルが見る前に除去され、専任のガードモデルが操作の試みを拒否し、構造化出力はスキーマ検証され、失敗は安全なフォールバックへ振り分けられ、**すべてのノードの入出力をブラウザで検査できます**。

中心となるのは**ワークフローの可視化**です。6 ノードのパイプラインがライブのストリップとして描画され、各ノードは**緑**（完了）、**赤**（失敗）、**灰色**（スキップ）で点灯し、リプレイ中は**黄色のパルス**が表示されます — 任意のノードをクリックすると詳細ドロワーが開き、そのステージが何を見て何を生成したかを正確に確認できます。

## ✨ 機能

| | 機能 | 内容 |
|--|---------|--------------|
| 🧠 | **LLM 分類** | チケットを 7 種類の問題タイプに分類し、5 チームのいずれかに割り当て、優先度（low→critical）、感情（positive→angry）、信頼度スコア + 根拠を付与 |
| 🛡️ | **PII マスキング** | 正規表現エンジンが、メールアドレス・電話番号・カード番号を*いかなる LLM 呼び出しよりも前*に除去 |
| 🚨 | **プロンプトインジェクションガード** | 専任の LLM 判定（JSON モードの構造化判定）が「ignore your instructions」型の攻撃をブロック。**フェイルセーフ** — ガード自体のエラー時も入力をブロック |
| ✅ | **出力検証** | Pydantic スキーマ + ビジネスルール（信頼度の範囲、低信頼度 ⇒ 人間によるレビュー） |
| 🔁 | **リトライ付きフォールバック** | Tenacity によるリトライ後、保守的な `SAFE_CLASSIFICATION` を返すためチケットが失われることはありません |
| 📊 | **ライブワークフロービジュアライザー** | ノードごとの処理時間、リプレイアニメーション、SVG エッジを備えた色分けパイプラインストリップ |
| 🔍 | **ノード詳細インスペクター** | 任意のノードをクリック → スライドオーバーのドロワー：マスキング済みテキスト、PII チップ、ガード判定、分類結果全体、検証エラー、コスト内訳、生 JSON |
| ⚠️ | **人間レビューのフラグ付け** | 低信頼度またはフォールバック結果には「Flagged for human review」のスタンプが付きます |
| 💰 | **コスト追跡** | 呼び出しごとのトークン数 + USD コスト、シャットダウン時のセッション集計 |
| 🏷️ | **プロンプトのバージョン管理** | バージョン管理されたプロンプトレジストリ（`GET /prompts`）。すべての結果に使用されたプロンプトバージョンが記録されます |
| 🌐 | **デュアルチャネル入力** | `web_form` と `email` の 2 チャネル |
| 📖 | **2 層構成のユーザーガイド** | アプリ内ドキュメント：非技術者向け説明タブと技術アーキテクチャタブ（`/userguide.html`） |

## 🖼️ スクリーンショット

### グリーンパス — PII マスキング付きのクリーンな分類
![グリーンパス](docs/images/01_green_path.png)

### レッドパス — インジェクション攻撃をブロック（classify/validate はスキップ）
![インジェクションブロック](docs/images/02_injection_blocked.png)

### ノードインスペクター — PII マスキングのドロワー
![ノードドロワー](docs/images/03_node_drawer.png)

### 内蔵の 2 層構成ユーザーガイド
![ユーザーガイド](docs/images/04_userguide.png)

## 🏗️ アーキテクチャ

```
                    ┌─────────────────────────────────────────────┐
                    │              FastAPI (main.py)              │
                    │   POST /classify   GET /prompts  /docs      │
                    │         "/" で demo_ui/ を提供               │
                    └────────────────────┬────────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────────┐
                    │      LangGraph StateGraph (graph.py)        │
                    │       run_pipeline_traced(...)              │
                    │   graph.stream(stream_mode="updates")       │
                    └────────────────────┬────────────────────────┘
                                         │
                                         ▼
 START ──► PIIマスキング ──► インジェクションチェック ──► 分類 ──► 検証 ──┬──► コストログ記録 ──► END
              │                    │                    │       │          ▲
              │                    │                    │       │ 失敗     │
              │                    │                    │       ▼          │
              │                    │                    │   フォールバック ─┘
              │                    │                    │   （バリデーション失敗時のみ）
              │                    │                    │
              │                    │                    │   ※インジェクションブロック時は
              │                    │                    │      直接コストログ記録へ
              │                    │                    │
              │                    │                    ▼
              │                    │             production_modules/
              │                    │                （本番モジュール）
              │                    │
              │                    └─ プロンプトインジェクション検出
              │
              └─ 個人情報（PII）のマスキング
```

**各ノードは独立した本番用モジュールに委譲します：**

| ノード | モジュール | 仕組み |
|------|--------|-----------|
| `pii_redact` | `pii_redaction.py` | 正規表現：EMAIL / PHONE / CREDIT_CARD（13–19 桁）→ ラベル付きプレースホルダー |
| `injection_check` | `prompt_injection.py` | LLM-as-a-judge、JSON モードの `InjectionJudgement`、フェイルセーフでブロック |
| `classify` | `structured_output.py` | `ChatOpenAI` JSON モード、スキーマエスケープ済みプロンプト、堅牢な JSON 抽出 |
| `validate` | `validate_response.py` | Pydantic の `TicketClassification` + ビジネスルール |
| `fallback` | `fallback_retry.py` | Tenacity リトライ → `SAFE_CLASSIFICATION`（人間レビュー、信頼度 0） |
| `cost_log` | `cost_calculator.py` | トークン数のカウント + 1K あたりの単価 → `CostInfo` |

### トレースの契約

`POST /classify` は分類結果に**ノードごとの `trace[]` を加えて**返します — これが UI を駆動しています：

```json
{
  "issue_category": "delivery_issue",
  "...": "…final fields…",
  "trace": [
    {
      "node": "injection_check",
      "label": "Injection Check",
      "status": "success | failed | skipped",
      "duration_ms": 1728,
      "output": { "is_safe": true, "detected_pattern": null }
    }
  ]
}
```

ステータスの導出：インジェクションブロック時は `injection_check` が **failed**、`classify`/`validate` は **skipped** になります。検証失敗時は `validate` が **failed** となり `fallback` が実行されます。実行されなかったノード（クリーンな実行での fallback）は `output: null` の **skipped** として合成されます。

## 🚀 クイックスタート

### 前提条件
- Python 3.11+
- [Ollama Cloud API キー](https://ollama.com/settings/keys)（または任意の OpenAI 互換エンドポイント）

### セットアップ

```bash
# 1. Clone
git clone https://github.com/git4rajmohan/AI_Projects.git
cd AI_Projects/AI-Safe-Support-Ticket-Classifier

# 2. Create venv + install
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt

# 3. Configure credentials — copy the example and add YOUR key
copy .env.example .env            # (cp on Linux/macOS)
#   → edit .env and set OLLAMA_API_KEY

# 4. Run
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

**http://localhost:8000** を開き — サンプルチケットを選んで分類を実行します。

- **インタラクティブな API ドキュメント：** http://localhost:8000/docs
- **ユーザーガイド：** http://localhost:8000/userguide.html

### テストの実行

```bash
python -m pytest tests/ -v     # 8 tests — LLM calls mocked, runs offline
```

## 🎮 デモスクリプト（3 クリック、3 つのパイプライン動作）

| クリック | サンプル | 表示される内容 |
|-------|--------|-----------------|
| 1 | 📦 Delayed Delivery | すべてのノードが**緑**、ドロワー内の PII チップ、人間レビューのロジック |
| 2 | 🚨 Injection Attack | `injection_check` が**赤**に、`classify`/`validate` は**灰色スキップ**、🚫 バナー |
| 3 | 🤔 Vague Complaint | 低信頼度 → ⚠「Flagged for human review」 |

このほか、📞 **All PII Types**（電話番号 + カード + メールを同時にマスキング）や、決済/アカウント系パスの 💳/🔐 もあります。

> **注：** 通常の実行では `fallback` ノードは灰色のままです — LLM が不正な出力を返したときにのみ実行されます。これは設計どおりに働く安全網であり、バグではありません。

## 📁 プロジェクト構成

```
AI-Safe-Support-Ticket-Classifier/
├── main.py                     # FastAPI アプリ: /classify (+トレース), /prompts, /health, 静的 UI
├── graph.py                    # LangGraph パイプライン + run_pipeline_traced() トレース取得
├── schema.py                   # Pydantic enum 定義 + TicketClassification + TicketState
├── requirements.txt
├── .env.example                 # 認証情報テンプレート (実際の .env は git-ignore 指定)
├── production_modules/
│   ├── pii_redaction.py        # 正規表現による PII (個人識別情報) スクラバー
│   ├── prompt_injection.py     # LLM 判定によるプロンプトインジェクションガード
│   ├── structured_output.py    # JSON モード分類器 (Function Calling バリアントを含む)
│   ├── validate_response.py    # スキーマ + ビジネスルール検証
│   ├── fallback_retry.py       # tenacity リトライ + SAFE_CLASSIFICATION (安全代替分類)
│   ├── cost_calculator.py      # トークン / コスト計算 + セッショントラッカー
│   ├── prompt_versioning.py    # バージョン管理されたプロンプトレジストリ
│   └── non_determinism.py      # Temperature / Seed 実験デモ
├── demo_ui/
│   ├── index.html              # 単一ファイル UI: ワークフロー表示、ドロワー、リプレイアニメーション
│   └── userguide.html          # 2 タブ構成ドキュメント (非エンジニア向け / 技術者向け)
├── tests/
│   └── test_classifier.py      # 8 件のオフラインテスト (モック LLM)
└── docs/
    └── images/                 # この README で使用されているスクリーンショット画像
```

## 🔒 セキュリティとプライバシーに関する注意

- **PII は LLM に届きません** — マスキングは最初のノードで行われ、UI は意図的にマスキング済みのコピーだけを表示します（元データはサーバーの外に出ません）。
- **インジェクションガードはフェイルクローズド** — ガードモデル自体がエラーを起こした場合、入力は通過せずブロックされます。
- **リポジトリに認証情報なし** — `.env` は git 除外対象で、`.env.example` がテンプレートです。コピーして自分の `OLLAMA_API_KEY` を設定してください。

## 🛠️ 技術スタック

| レイヤー | 選択 | 理由 |
|-------|--------|-----|
| オーケストレーション | **LangGraph** `StateGraph` | 条件分岐エッジ（validate → fallback）、トレーシング用のノード単位ストリーミング |
| API | **FastAPI** + Pydantic | 型付きリクエスト/レスポンスモデル、lifespan フック、自動 `/docs` |
| LLM | **Ollama Cloud** — `gpt-oss:120b` | `langchain-openai` 経由の OpenAI 互換エンドポイント |
| 検証 | **Pydantic v2** | 列挙型で制約されたスキーマ + カスタムビジネスルール |
| リトライ | **tenacity** | レート制限/検証エラー時の指数バックオフ |
| フロントエンド | Vanilla HTML/CSS/JS | ビルド不要。手書きの SVG エッジ。シングルファイル配置 |
| テスト | **pytest** (8/8) | LLM モッキングにより完全オフライン |

## 📄 ライセンス

MIT — 詳細は [LICENSE](LICENSE) を参照してください。

---

*[AI_Projects](https://github.com/git4rajmohan/AI_Projects) — AI/ML プロジェクトのキュレーション集 — の一部です。*
