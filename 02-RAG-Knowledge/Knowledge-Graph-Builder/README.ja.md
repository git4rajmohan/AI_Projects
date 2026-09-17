言語 / Languages: [English](README.md) | **日本語**

---

# 🔗 Knowledge Graph Builder

> スプレッドシートとテキストドキュメントを、AI エージェント・Neo4j・Google ADK で動くインタラクティブでクエリ可能なナレッジグラフに変換します。
## なぜこのプロジェクトが存在するのか

グラフネイティブな知識表現を示すプロジェクトです。AI エージェントがスキーマを洗練し(提案 → 批評 → 検証)、決定論的なコードが Cypher を生成するため、LLM が生のグラフクエリを書くことはありません。
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1.svg)](https://neo4j.com)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.5-4285F4.svg)](https://google.github.io/adk-docs/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📖 概要

**Knowledge Graph Builder** は、構造化データファイル(CSV)と非構造化テキスト(Markdown)からナレッジグラフの作成を自動化する Web アプリケーションです。グラフスキーマを手動で設計し Cypher クエリを書く代わりに、次の操作だけで済みます:

1. データファイルを**選択**する
2. グラフに何を捉えさせたいかを**記述**する
3. **AI エージェントに**スキーマの提案と洗練を任せる
4. **確認・承認して構築**する — あとは自然な英語で質問できます

アプリは AI エージェントのチーム(Google ADK `LoopAgent`)を使ってグラフスキーマを反復的に提案・批評・検証し、Neo4j 内にグラフを構築します。最後に自然言語でクエリできるようになります — すべてクリーンな Web UI を通じて行われます。

---

## ✨ 機能

- 🤖 **AI によるスキーマ提案** — 3 エージェントの洗練ループ(Proposer → Critic → Checker)がデータから最適なグラフ構造を提案します
- 📁 **ファイルブラウザー** — ファイルシステムをナビゲートし、CSV・Markdown・JSON ファイルを選択できます
- 🏗️ **ワンクリックでのグラフ構築** — Neo4j データベースの作成、CSV のコピー、Cypher `LOAD CSV` の実行によるノードとリレーションシップの構築を自動化します
- 🔍 **自然言語 Q&A** — 平易な英語で質問すると、AI エージェントが Cypher に翻訳し、クエリを実行し、結果を要約します
- 📊 **インタラクティブなグラフ可視化** — ズーム・パン・ドラッグ対応の Canvas ベースのグラフエクスプローラー
- 📡 **ライブのエージェント進行状況** — スキーマ提案ループの実行中、SSE ストリーミングでエージェントの動きをリアルタイム表示します
- 🗄️ **マルチデータベース対応** — プロジェクトごとに独立した Neo4j データベースを持ちます
- 📋 **6 つのサンプルデータセット** — Furniture、Tech、Reviews、Healthcare、E-commerce、Education

---

## 🏗️ アーキテクチャ

```
┌─────────────────────────────────────────────────────────━E
━E             Browser (Vanilla HTML/JS/CSS)               ━E
━E   4-step wizard · Canvas graph viz · SSE progress       ━E
└────────────────────┬────────────────────────────────────━E
                     ━EREST API + SSE
┌────────────────────▼────────────────────────────────────━E
━E             FastAPI Backend (main.py)                    ━E
━E  /api/browse · /api/propose · /api/build · /api/query   ━E
└─────┬──────────────┬──────────────────┬─────────────────━E
      ━E             ━E                 ━E
┌─────▼─────━E┌──────▼───────━E┌────────▼──────────━E
━E Neo4j    ━E━E agents.py   ━E━E graph_builder.py ━E
━E Database ━E━E (ADK agents)━E━E (Cypher builder) ━E
━E          ━E━E             ━E━E                   ━E
━Ebolt://   ━E━ELoopAgent:   ━E━ELOAD CSV ↁEMERGE   ━E
━E:7687     ━E━E Proposer    ━E━E docker cp         ━E
━E          ━E━E Critic      ━E━E auto-detect       ━E
━E          ━E━E Checker     ━E━E stats/graph data  ━E
━E          ━E━ELlmAgent:    ━E└────────────────────━E
━E          ━E━E QueryAgent  ━E
└───────────━E└──────┬───────━E
                     ━E
              ┌──────▼───────━E
              ━E LLM (LiteLLm)━E
              ━E Ollama Cloud ━E
              ━E via proxy    ━E
              └──────────────━E
```

### AI エージェントパイプライン

| エージェント | タイプ | 役割 |
|-------|------|------|
| `schema_proposal_agent` | LlmAgent | ファイルを読み、ノードとリレーションシップの構築ルールを提案する |
| `schema_critic_agent` | LlmAgent | 提案を検証し、"valid" またはフィードバック付きの "retry" を返す |
| `CheckStatusAndEscalate` | BaseAgent | Critic が "valid" を返したらループを停止する(最大 3 イテレーション) |
| `query_agent` | LlmAgent | 自然言語の質問を Cypher に翻訳 → 実行 → 回答を要約する |

---

## 📸 スクリーンショット

> ℹ️ **注記:** スクリーンショット内の UI テキストは英語で表示されています。実際の画面は英語版 README または [ユーザーガイド](userguide.html) でご確認ください。

(スクリーンショットは [英語版 README](README.md#-スクリーンショット) を参照してください)

---

## 🚀 クイックスタート

### 前提条件

- **Python 3.12+**
- **Neo4j 5.x**(ローカルまたは Docker で稼働)
- **Ollama** アカウント(クラウド LLM 利用時)またはローカル Ollama インスタンス
- **Google ADK**(`google-adk` パッケージ)

### 1. リポジトリのクローン

```bash
git clone https://github.com/git4rajmohan/AI_Projects.git
cd AI_Projects/KnowledgegraphUIapp
```

### 2. 仮想環境の作成

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数の設定

```bash
# テンプレートをコピーして値を記入
cp .env.example .env
# Ollama API キー、Neo4j パスワードなどを .env に記入
```

### 5. Neo4j の起動

```bash
# オプション A: Docker
docker run -d --name neo4j-adk \
  -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5

# オプション B: ローカルの Neo4j インストール
# Neo4j が bolt://localhost:7687 で稼働していることを確認
```

### 6. Ollama Cloud プロキシの起動(クラウド LLM を使う場合)

```bash
# 親ワークスペースディレクトリから実行
python ollama_cloud_proxy.py
# http://127.0.0.1:11435/v1 で待ち受けます
```

### 7. アプリの起動

```bash
python -m uvicorn app.main:app --reload --port 8080
```

### 8. UI を開く

ブラウザで **http://localhost:8080** にアクセスします。

---

## 📂 プロジェクト構成

```
KnowledgegraphUIapp/
├── app/
━E  ├── __init__.py
━E  ├── main.py              # FastAPI Web サーバーと REST エンドポイント
━E  ├── agents.py            # Google ADK エージェント (LoopAgent + LlmAgent)
━E  ├── graph_builder.py     # Cypher LOAD CSV によるグラフ構築
━E  ├── query_engine.py      # 直接 LLM クエリ(フォールバック経路)
━E  └── static/
━E      └── index.html       # シングルページフロントエンド(バニラ JS)
├── input_files/             # 6 つのサンプルデータセット
━E  ├── project1_furniture/  # 製品、サプライヤー、部品、アセンブリ
━E  ├── project2_tech/       # 企業、顧客、製品、購入
━E  ├── project3_reviews/    # Markdown 製品レビュー(10 ファイル)
━E  ├── project4_healthcare/ # 医師、病院、患者、処方
━E  ├── project5_ecommerce/  # 購入者、販売者、注文、製品、レビュー
━E  └── project6_education/  # 学生、教授、講座、大学
├── tests/
━E  ├── test_app.py          # ユニットテスト
━E  ├── e2e_test.py          # E2E テスト(プロジェクト 1)
━E  └── e2e_test_project2.py # E2E テスト(プロジェクト 2)
├── images/                  # ドキュメント用スクリーンショット
├── userguide.html           # インタラクティブなユーザーガイド(2 タブ)
├── requirements.txt
├── .env.example             # 環境変数テンプレート(コミット可能)
└── .gitignore
```

---

## 🔄 仕組み

### Step 1: ファイルの選択とゴールの記述
ファイルシステムを閲覧し、CSV/MD/JSON ファイルを選択し、Neo4j データベースに名前を付け、グラフに何を捉えさせたいかを記述します。

### Step 2: AI がスキーマを提案
Google ADK の `LoopAgent` が 3 エージェントの洗練ループ(最大 3 イテレーション)を実行します:
- **Proposer エージェント**がファイルを読み、ノード/リレーションシップのルールを提案する
- **Critic エージェント**が提案を検証し、フィードバック付きで "valid" または "retry" を返す
- **Checker** が Critic の承認時にループを停止する

SSE ストリーミングでライブの進行状況を確認でき、最終的な JSON プランは編集できます。

### Step 3: グラフの構築
アプリは(必要なら)Neo4j データベースを作成し、CSV をインポートディレクトリにコピーし(必要なら `docker cp`)、Cypher の `LOAD CSV` + `MERGE` クエリを実行してノードとリレーションシップを構築します。

### Step 4: クエリと探索
自然言語で質問します。`query_agent`(ADK `LlmAgent`)がグラフスキーマを取得し、Cypher を生成して実行し、回答を要約します。インタラクティブな Canvas 可視化がグラフ構造を表示します。

---

## 🛠️ 技術スタック

| コンポーネント | 技術 |
|-----------|-----------|
| バックエンド | FastAPI 0.115 + Uvicorn |
| AI エージェント | Google ADK 1.5 (LlmAgent, LoopAgent, Runner) |
| LLM | Ollama Cloud (gpt-oss:120b) via LiteLLM proxy |
| グラフデータベース | Neo4j 5.x (Python driver 5.28) |
| フロントエンド | Vanilla HTML/CSS/JavaScript (no framework) |
| グラフ可視化 | HTML5 Canvas (custom renderer) |
| ストリーミング | Server-Sent Events (SSE) |
| バリデーション | Pydantic |

---

## 📦 依存パッケージ

```
fastapi==0.115.0
uvicorn==0.30.6
neo4j==5.28.1
neo4j-graphrag==1.8.0
python-dotenv==1.0.1
google-adk==1.5.0
litellm==1.73.6
openai
pydantic
```

---

## 📝 サンプルデータセット

| プロジェクト | ファイル | ドメイン |
|---------|-------|--------|
| Furniture | 5 個の CSV | 製品、アセンブリ、部品、サプライヤー、部品-サプライヤー対応 |
| Tech | 5 個の CSV | 企業、顧客、パートナーシップ、製品、購入 |
| Reviews | 10 個の Markdown ファイル | 特徴・問題・場所を含む製品レビュー |
| Healthcare | 6 個の CSV | 医師、病院、薬剤、患者、処方、治療 |
| E-commerce | 5 個の CSV | 購入者、販売者、注文、製品、レビュー |
| Education | 5 個の CSV | 学生、教授、講座、履修、大学 |

---

## 🔒 セキュリティ

- **`.env` は gitignore 済み** — 実際の API キーやパスワードをコミットしないでください
- 設定のテンプレートとして `.env.example` を使用します
- Ollama クラウドプロキシはダミーの `OPENAI_API_KEY` を使用します — 実際のキー(`OLLAMA_API_KEY`)は `.env` に保管されます
- Neo4j の認証情報はハードコードではなく環境変数から読み込まれます

---

## 📄 ライセンス

このプロジェクトは MIT License の下で公開されています — 詳細は [LICENSE](LICENSE) を参照してください。

---

## 👤 作者

**Raj Mohan**
- GitHub: [@git4rajmohan](https://github.com/git4rajmohan)