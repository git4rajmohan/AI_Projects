言語 / Languages: [English](README.md) | **日本語**

---

# AgentFlow — 動的マルチエージェント ワークフロー & スキル オーケストレーター

> LLM がユーザーの意図を構造化されたエージェント ワークフローに変換し、承認を得て、ツール経由で実行し、結果を評価し、成功したワークフローを再利用可能なスキルとして保存する — そんな動的マルチエージェント オーケストレーション プラットフォームです。

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)
![Google ADK](https://img.shields.io/badge/Google%20ADK-Agent%20Framework-4285F4?logo=google&logoColor=white)
![React](https://img.shields.io/badge/React-18%20%2B%20TypeScript-61DAFB?logo=react&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud%20gpt--oss%3A120b-white?logo=ollama)
![SQLite](https://img.shields.io/badge/Persistence-SQLite%20(async)-003B57?logo=sqlite&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-222_passing-4ade80)

## デモ動画
[![Agent Flow Orchestrator Demo](https://img.youtube.com/vi/nuW9I_9GJpI/0.jpg)](https://youtu.be/nuW9I_9GJpI)

## なぜこのプロジェクトが存在するのか

ワークフローを固定されたエージェント列としてハードコードするのではなく、ユーザーの意図から生成する動的マルチエージェント オーケストレーションの実証です。同一のエンジンがどんなタスクにも対応します — プランはデータであり、プラットフォームこそがプロダクトです。

## このプロジェクトが実証すること

- LLM プランニングによる、検証済みの構造化エージェント プランの生成(Pydantic `PlanSpec`)
- Kahn レベル並列化・サイクル検出・上限付きリトライを備えた DAG オーケストレーション
- 実行前、および権限境界でのヒューマンインザループ(HITL)承認
- 基準ごとのスコアリングと上限付きリプランニングを行う評価ステージ
- ディスカバリーとレコメンデーションを備えた、バージョン管理された再利用可能なスキル(`.skill.yaml` / `.skill.zip`)

## アーキテクチャ

```text
インテント (ユーザーの意図) → インテントパーサー (意図解析) → スキル検出・探索 (類似度 ≥ 0.5 の場合に再利用)
                      → LLM プランナー (PlanSpec JSON 生成) → ユーザー承認
                      → エージェントファクトリー → DAG オーケストレーター (階層化・並列処理・リトライ)
                      → ツール実行環境 (Python · ファイル操作 · Web · HTTP API)
                      → 評価エンジン (基準に対するスコアリング 0〜1)
                      → 失敗時 → 再計画/リプランナー (最大2回まで) | 成功時 → スキルライブラリ (バージョン管理)
```

- **バックエンド**: Google ADK ランナーをラップする FastAPI — プランナー、オーケストレーター、ポリシー、評価、スキルの 5 つの独立したエンジン
- **フロントエンド**: React 18 + TypeScript + Vite + Zustand のワークスペース UI(プランカード、リアルタイム エージェント アクティビティ、承認カード、評価バッジ)
- **LLM**: LiteLLM の OpenAI 互換エンドポイント経由で Ollama Cloud `gpt-oss:120b`。モデル ルーター(fast / default / reasoning の 3 ティア)
- **状態管理**: async SQLAlchemy 経由の SQLite — タスク、プラン、実行、イベント、スキル、承認

## ワークフロー

1. **記述** — ユーザーが目標を 1 文で入力。インテント パーサーが分類します(データ分析、リサーチ、QA など)
2. **再利用またはプラン生成** — まずスキル ディスカバリーが走ります(キーワード マッチ ≥ 0.5 で実績あるプランを再利用)。なければ LLM プランナーが `PlanSpec` を生成し、`plan_validator` が検証します(未知のツール、宙ぶらりんの依存関係、サイクルは明確に失敗)
3. **承認** — ユーザーがプランを承認するまで何も実行されません。`EXTERNAL_ACTION` / `DESTRUCTIVE` ツールを使うエージェントは、実行中に 2 回目の承認ゲートをトリガーします
4. **実行** — DAG オーケストレーターがレベルごとにエージェントを実行(`asyncio.gather` による並列化、エージェントごとにリトライ ≤ 3)。永続化されるイベント(`AGENT_STARTED`、`TOOL_STARTED/COMPLETED`、`HUMAN_APPROVAL_REQUIRED` など)を発行
5. **評価** — 構造チェック + 基準ごとのスコアをしきい値(デフォルト 0.7)と比較。失敗はリプランナーにフィードバック(最大 2 回)
6. **スキルとして保存** — 成功したワークフローはバージョン管理された `.skill.yaml` / `.skill.zip` として固定化。インポート パイプラインはインストール前に検証・セキュリティ スキャン・プレビューを行います

## 技術スタック

| 領域 | 技術 |
|---|---|
| LLM | Ollama Cloud(`gpt-oss:120b`)via LiteLLM |
| AI フレームワーク | Google ADK(`LlmAgent`、`Runner`、`FunctionTool`) |
| バックエンド | FastAPI + Uvicorn、SSE ストリーミング |
| データベース | SQLite(async SQLAlchemy、PostgreSQL 対応) |
| フロントエンド | React 18、TypeScript、Vite、TailwindCSS、Zustand |
| バリデーション | Pydantic v2(`PlanSpec` / `AgentSpec`) |
| テスト | pytest + pytest-asyncio(222 テスト) |

## 重要な AI エンジニアリングの概念

- プランはプロンプトではなく検証済みデータ — 自由形式の LLM 出力がオーケストレーターに到達することはない
- DAG 実行: 1 つの依存関係定義から シーケンシャル / 並列 / マージ / リトライ / キャンセル の各パターンを実現
- 権限レベル ポリシー エンジン(`READ < WRITE < EXTERNAL_ACTION < DESTRUCTIVE`)
- 再生成の前にスキル再利用。使用メトリクス付きのセマンティック バージョニング
- タスク種別と複雑さによるモデル ルーティング

## 安全性 / 信頼性

- ヒューマン承認ゲート付きの 4 レベル権限モデル(DB 行 + asyncio Events — 承認は再起動後も保持)
- `python_executor` は正規表現でネットワーク系インポートをブロックし、コード実行が `EXTERNAL_ACTION` ゲートを迂回できないようにしています
- `calculator` は AST ホワイトリスト方式の算術のみ(`eval` 不使用)
- あらゆる箇所で上限付きの自律性: エージェントごとのイテレーション / ツール呼び出し / タイムアウト上限。ワークフローごとのリプラン / 時間 / 総ツール呼び出し上限
- 各ステップ後に実行状態を永続化(クラッシュ復旧可能)。リプランニングは上限 ≤ 2 回

## テスト / 評価

- **222 個のユニット + API テストが合格**(pytest、`asyncio_mode=auto`)。プランナー、DAG、ファクトリー、評価、スキル、承認、API ルートをカバー
- 評価エンジン: 構造チェック + 基準スコアリング(`completeness`、`accuracy`、`format`、`relevance`)としきい値ゲート。オプションで LLM-as-judge パス
- デモ ランをエンドツーエンドで検証済み: CSV → Excel を 95 秒、ツール呼び出し 3 回、評価スコア 1.00

## デモ

記録されたセッション(CSV → Excel デモ)からの実際の UI キャプチャを [`docs/screenshots/`](docs/screenshots/) に格納:

| 意図とプラン | スキル ライブラリ | 完了ランの結果 |
|:---:|:---:|:---:|
| ![Intent](docs/screenshots/00-intent-bubble.png) | ![Skill library](docs/screenshots/01-skill-discovery-plan.png) | ![Result](docs/screenshots/06-completed-run-result.png) |

詳細ウォークスルー: [`AI_AgentFlow Orchestrator_userguide.html`](AI_AgentFlow%20Orchestrator_userguide.html) — 4 タブ構成のガイド(エレベーター ピッチ / 非技術者向け / 技術者向け / 用語集)。

## 実行方法

```bash
# 1. Backend environment
python -m venv venv
venv\Scripts\activate                 # Windows
pip install -r requirements.txt

# 2. Configure .env (project root) — copy from .env.example
#    OPENAI_API_KEY=<your ollama.com key>
#    OPENAI_API_BASE=https://ollama.com/v1
#    AGENTOS_LLM_MODEL=openai/gpt-oss:120b

# 3. Start the backend
venv\Scripts\python -m uvicorn app.main:app --app-dir backend --port 8000

# 4. Frontend (second terminal)
cd frontend
npm install
npm run dev                           # → http://localhost:5173

# 5. Tests
venv\Scripts\python -m pytest -q      # 222 passed
```

Ollama Cloud の API キー(ollama.com/settings/keys)が必要です。オプションの `SERPAPI_API_KEY` で実際のウェブ検索が有効になります。

## プロジェクト構成

```text
AgentFlow-Orchestrator/
├── backend/app/
│   ├── main.py               # FastAPI + ライフサイクル管理 (lifespan) + 10個のルーター + /health エンドポイント
│   ├── planner/              # インテント解析 · プランナー (ADK output_schema) · 計画検証 (plan_validator)
│   ├── factory/              # エージェントファクトリー · ベースエージェント (ADK ループ) · 実行環境
│   ├── orchestrator/         # 実行エンジン · DAG 制御 (Kahnのアルゴリズム + DFS循環検出) · 状態管理 · イベント配信 (SSE)
│   ├── policy/               # 権限管理エンジン · 承認プロセスにおける一時停止/再開制御
│   ├── evaluation/           # 構造的評価 + 評価基準スコアリング · 再計画 (replanner)
│   ├── skills/               # スキルレジストリ · 検出 · 作成 · インポート/エクスポート · スキルレコメンダー
│   ├── tools/builtins/       # ファイル読み込み · ファイル書き込み · Python実行 · 計算機 · HTTPリクエスト · Web検索
│   ├── memory/               # ワーキングメモリ / 記憶 (長期記憶) / スキルスコープ
│   ├── llm/                  # LiteLLM 設定 · モデルルーティング
│   └── models/               # Pydantic スキーマ群 (PlanSpec, AgentSpec, SkillSpec など)
├── frontend/src/             # React ワークスペース: タイムライン, PlanCard, AgentActivityCard, ApprovalInlineCard, EvaluationBadge
├── skills/                   # ビルトインスキル定義 YAML群 (csv-to-excel-converter, document-summarization, web-research)
├── tests/                    # 222 件の pytest テストスイート
├── docs/screenshots/         # 実際の UI キャプチャ画像
├── instruction.md            # 65 セクションで構成されたプラットフォーム仕様書
└── AI_AgentFlow Orchestrator_userguide.html
```

## このプロジェクトの違い

固定されたマルチエージェント階層ではなく、動的なワークフロー生成 — エージェント プランはタスクごとに生成され、検証・承認され、DAG として実行・スコアリングされ、再利用可能なスキルとして固定化されます。E-Commerce プロジェクトが固定階層を示すのに対し、このプラットフォームはワークフローそのものを生成します。

## AI 支援開発

このプロジェクトは AI 支援のコーディング ワークフローを用いて開発されました。アーキテクチャ、実装の意思決定、テスト、デバッグ、検証は開発過程でレビューとブラッシュアップが行われています。
