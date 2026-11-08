**言語 / Languages:** [日本語](./README-FULL_ja.md) · [English](./README-FULL.md)

---

> 🌐 **ようこそ / Welcome:** 言語をお選びください / select your language → [日本語](https://git4rajmohan.github.io/AI_Projects/welcome.html?lang=ja) · [English](https://git4rajmohan.github.io/AI_Projects/welcome.html?lang=en)
>
> **私のサイトへようこそ。オプションをお選びください:** [GitHub ポートフォリオ](./README-FULL_ja.md) · [LinkedIn](https://www.linkedin.com/in/seevaram-rajmohan-04a4a04a/)

# AI / ML エンジニアリング・ポートフォリオ

エージェント AI、マルチエージェント・オーケストレーション、A2A 相互運用性、RAG、ナレッジエンジニアリング、AI セーフティ、ドキュメントインテリジェンス、コンピュータビジョン、音声 AI、Agent オブザーバビリティ、古典的な NLP/ML を扱う、実践的な AI/ML プロジェクト 20 件のコレクションです。

## ポートフォリオ・マップ

6 カテゴリ · 20 プロジェクト

| カテゴリ | プロジェクト数 | 主な技術 |
|---|---:|---|
| 🤖 [エージェント AI & マルチエージェントシステム](./01-Agentic-AI/) | 7 | Google ADK, LangGraph, MCP, Agno, LangChain LCEL, a2a-sdk |
| 📚 [RAG & ナレッジエンジニアリング](./02-RAG-Knowledge/) | 5 | LangGraph, LlamaIndex, ChromaDB, Qdrant, Neo4j |
| 🛡️ [AI セーフティ & 品質エンジニアリング](./03-AI-Safety-Quality/) | 2 | NeMo Guardrails, LLM ジャッジ, PII 検出 |
| 🏭 [応用 AI (Applied AI)](./04-Applied-AI/) | 4 | OCR, ドキュメント AI, 音声 AI, コンピュータビジョン, FastAPI |
| 🧠 [NLP & 機械学習](./05-NLP-Machine-Learning/) | 1 | scikit-learn, NLTK, spaCy |
| 📊 [Agent オブザーバビリティ & 評価](./04-Applied-AI/Agent-Evaluation-Labs/) | 1 | Arize Phoenix, OpenTelemetry, LLM-as-a-Judge |

## 構築できること

- 🤖 エージェント AI / マルチエージェントワークフロー
- 🔧 LLM 工具と MCP オーケストレーション
- 📚 本番指向の RAG・ナレッジシステム
- 📏 LLM/RAG 評価と品質エンジニアリング
- 🛡️ AI セーフティとプロンプトインジェクション防御
- 📄 ドキュメントインテリジェンスと検証ワークフロー
- 🎙️ 音声・マルチモーダル AI パイプライン
- 🧠 古典的 NLP・機械学習システム

## 注目プロジェクト

| プロジェクト | デモ内容 |
|---|---|
| [AgentFlow — 動的マルチエージェントワークフロー & スキルオーケストレーター](./01-Agentic-AI/AgentFlow-Orchestrator/) | 動的マルチエージェントオーケストレーション |
| [エージェント AI MCP ツールオーケストレーションプラットフォーム](./01-Agentic-AI/MCP-Tool-Orchestration/) | MCP とツールオーケストレーション |
| [エージェント AI マルチエージェント・マインドマップオーケストレーター](./01-Agentic-AI/MultiAgent-Mindmap/) | 反復型マルチエージェントレビューループ |
| [本番 RAG ドキュメントアシスタント](./02-RAG-Knowledge/Production-RAG/) | 検索エンジニアリング |
| [LLM ガードレール & AI セーフティ防御ラボ](./03-AI-Safety-Quality/LLM-Guardrails/) | AI セーフティ |
| [RAG 評価 & LLM 品質エンジニアリングハーネス](./02-RAG-Knowledge/RAG-Evaluation-Harness/) | AI 品質・評価 |

## カテゴリ別プロジェクト

### 🤖 エージェント AI & マルチエージェントシステム

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [AgentFlow オーケストレーター](./01-Agentic-AI/AgentFlow-Orchestrator/) | 動的マルチエージェントワークフロー/DAG 生成 | Google ADK, FastAPI, React |
| [MCP ツールオーケストレーション](./01-Agentic-AI/MCP-Tool-Orchestration/) | MCP ツールエコシステムとツール呼び出し | MCP, Agno, Streamlit |
| [E コマース・マルチエージェント](./01-Agentic-AI/MultiAgent-Ecommerce/) | 階層型専門エージェント | Google ADK, LiteLLM |
| [注文返品 & 不正防止エージェント](./01-Agentic-AI/OrderReturns-Fraud-Agent/) | ステートフル業務ワークフロー + HITL | LangGraph, FastAPI, SQLite |
| [病院予約エージェント](./01-Agentic-AI/Hospital-Appointment-Agent/) | LLM 抽出 + 決定論的カレンダー | LangChain LCEL, Twilio SMS |
| [マルチエージェント・マインドマップ](./01-Agentic-AI/MultiAgent-Mindmap/) | 3 エージェント反復レビュー/改善 | Streamlit, Ollama, markmap.js |
| [Agent2Agent (A2A) エクスプローラー](./01-Agentic-AI/Agent2Agent-Explorer/) | リモート A2A エージェントの探索・検証・委譲 | a2a-sdk, Streamlit, FastAPI, SQLite |

### 📚 RAG & ナレッジエンジニアリング

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [本番 RAG アシスタント](./02-RAG-Knowledge/Production-RAG/) | 検索エンジニアリング + 回帰評価 | LangGraph, ChromaDB, BM25 |
| [エンタープライズ・ナレッジアシスタント](./02-RAG-Knowledge/Enterprise-Knowledge-Assistant/) | ハイブリッド (ベクトル + BM25 + グラフ) 検索 | LlamaIndex, Qdrant, Cognee |
| [RAG 評価ハーネス](./02-RAG-Knowledge/RAG-Evaluation-Harness/) | RAG/LLM 品質測定 | RAGAS, pytest, LLM ジャッジ |
| [LLM Wiki](./02-RAG-Knowledge/LLM-Wiki/) | ドキュメントからナレッジベース生成 | FastAPI, React, D3 |
| [ナレッジグラフビルダー](./02-RAG-Knowledge/Knowledge-Graph-Builder/) | グラフネイティブな構築と照会 | Google ADK, Neo4j, SSE |

### 🛡️ AI セーフティ & 品質エンジニアリング

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [LLM ガードレール防御ラボ](./03-AI-Safety-Quality/LLM-Guardrails/) | 専用 AI セーフティ制御 | NeMo Guardrails, Colang, Groq |
| [AI セーフ・サポートチケット分類器](./03-AI-Safety-Quality/Safe-Support-Ticket/) | AI ワークフロー内のセキュリティ制御 | LangGraph, PII マスキング, ジャッジ LLM |

### 🏭 応用 AI (Applied AI)

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [DocFlow ドキュメントインテリジェンス](./04-Applied-AI/DocFlow-Document-Intelligence/) | 請求書は AI が読み取り、決定論的ポリシーが判定 | FastAPI, Streamlit, PyMuPDF, Tesseract OCR |
| [リサーチ音声エージェント](./04-Applied-AI/Research-Voice-Agent/) | エージェントが計画し、ツールが動いてポッドキャスト化 | Google ADK, Ollama gpt-oss:120b, edge-tts, faster-whisper |
| [MaintAI 意思決定プラットフォーム](./04-Applied-AI/DecisionModelDemo/) | 決定モデルが分類し、ポリシーが判定し、LLM が説明 | Streamlit, SQLite, Ollama TEV1, scikit-learn |
| [VisionFlow 動画分析](./04-Applied-AI/VisionFlow/) | YOLO11 検出 + 追跡 + カウント規律 | Ultralytics YOLO11, ByteTrack/BoT-SORT, OpenCV |

### 🧠 NLP & 機械学習

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [感情分析パイプライン](./05-NLP-Machine-Learning/Sentiment-Analysis/) | 古典的 NLP/ML | scikit-learn, TF-IDF, NLTK, spaCy |

### 📊 Agent オブザーバビリティ & 評価

| プロジェクト | AI 機能 | 技術 |
|---|---|---|
| [Agent Evaluation Labs](./04-Applied-AI/Agent-Evaluation-Labs/) | LLM エージェントのオブザーバビリティと評価 (トレーシング + LLM ジャッジ) | Arize Phoenix, OpenTelemetry, Streamlit, DuckDB |

## 技術カバレッジ

**LLM / AI**
Ollama · Ollama Cloud · Groq · LiteLLM

**エージェント AI**
Google ADK · LangGraph · LangChain · Agno · MCP · a2a-sdk

**RAG / ナレッジ**
ChromaDB · Qdrant · Neo4j · LlamaIndex · Cognee · BM25 · RRF

**評価**
RAGAS · LLM-as-a-Judge · pytest · ゴールデンデータセット · Arize Phoenix · OpenTelemetry

**AI セーフティ**
NeMo Guardrails · Colang · プロンプトインジェクション · PII 検出

**応用 AI (Applied AI)**
OCR · ドキュメントインテリジェンス · STT · TTS · 音声 AI · コンピュータビジョン (YOLO11, ByteTrack)

**アプリケーション**
FastAPI · Streamlit · React · SQLite

## AI エンジニアリング横断要素

**評価**
- RAGAS
- LLM-as-a-judge
- ゴールデンデータセット
- 回帰テスト

**セーフティ**
- プロンプトインジェクション検出
- PII 検出
- ジェイルブレイク検出

**信頼性**
- 決定論的検証
- Human-in-the-loop
- エビデンスゲーティング
- チェックポイント

## プロジェクト選びのガイド

### エージェント AI をお探しですか？
- [AgentFlow オーケストレーター](./01-Agentic-AI/AgentFlow-Orchestrator/) · [MCP ツールオーケストレーション](./01-Agentic-AI/MCP-Tool-Orchestration/) · [E コマース・マルチエージェント](./01-Agentic-AI/MultiAgent-Ecommerce/) · [注文返品 & 不正防止](./01-Agentic-AI/OrderReturns-Fraud-Agent/) · [病院予約](./01-Agentic-AI/Hospital-Appointment-Agent/) · [マルチエージェント・マインドマップ](./01-Agentic-AI/MultiAgent-Mindmap/) · [A2A エクスプローラー](./01-Agentic-AI/Agent2Agent-Explorer/)

### RAG / ナレッジエンジニアリングをお探しですか？
- [本番 RAG](./02-RAG-Knowledge/Production-RAG/) · [エンタープライズ・ナレッジアシスタント](./02-RAG-Knowledge/Enterprise-Knowledge-Assistant/) · [RAG 評価ハーネス](./02-RAG-Knowledge/RAG-Evaluation-Harness/) · [LLM Wiki](./02-RAG-Knowledge/LLM-Wiki/) · [ナレッジグラフビルダー](./02-RAG-Knowledge/Knowledge-Graph-Builder/)

### AI セーフティをお探しですか？
- [LLM ガードレール](./03-AI-Safety-Quality/LLM-Guardrails/) · [AI セーフ・サポートチケット](./03-AI-Safety-Quality/Safe-Support-Ticket/)

### 応用 AI をお探しですか？
- [DocFlow ドキュメントインテリジェンス](./04-Applied-AI/DocFlow-Document-Intelligence/) · [リサーチ音声エージェント](./04-Applied-AI/Research-Voice-Agent/) · [MaintAI](./04-Applied-AI/DecisionModelDemo/) · [VisionFlow](./04-Applied-AI/VisionFlow/)

### 古典的 NLP/ML をお探しですか？
- [感情分析](./05-NLP-Machine-Learning/Sentiment-Analysis/)

### Agent オブザーバビリティと評価をお探しですか？
- [Agent Evaluation Labs](./04-Applied-AI/Agent-Evaluation-Labs/)

## ナビゲーション

| ドキュメント | 目的 |
|---|---|
| **README-FULL_ja.md** (このファイル) | 日本語ポートフォリオ概要とナビゲーション |
| [README-FULL.md](./README-FULL.md) | 英語版ポートフォリオ概要 |
| [PORTFOLIO_INDEX.md](./PORTFOLIO_INDEX.md) | 詳細カタログ — 全プロジェクトのアーキテクチャ・差別化ポイント・リンク |
| **各プロジェクトの README** | 実装の詳細 |

## AI 支援開発

本ポートフォリオは、VS Code を用いた AI 支援コーディングワークフローで開発しました。AI ツールで実装を加速しつつ、アーキテクチャ、統合、テスト、デバッグ、検証は開発中にレビュー・改良しています。

### 日本語版のご案内 / 日本語ポートフォリオ

- **[GitHub ポートフォリオ](https://github.com/git4rajmohan/AI_Projects/blob/main/README.ja.md)** - 日本語版・プロジェクト一覧
- **[LinkedIn](https://www.linkedin.com/in/seevaram-rajmohan-04a4a04a/)**

---

*詳細カタログ: [PORTFOLIO_INDEX.md](./PORTFOLIO_INDEX.md) · ライブページ: [git4rajmohan.github.io/AI_Projects](https://git4rajmohan.github.io/AI_Projects/)*
