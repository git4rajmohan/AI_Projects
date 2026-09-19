言語 / Languages: [English](README.md) | **日本語**

---

# AI / ML エンジニアリング・ポートフォリオ

エージェント AI、マルチエージェント・オーケストレーション、RAG、ナレッジエンジニアリング、AI セーフティ、ドキュメントインテリジェンス、音声 AI、古典的な NLP/ML を扱う、実践的な AI/ML プロジェクト 16 件のコレクションです。

## ポートフォリオ・マップ

5 カテゴリ · 16 プロジェクト

| カテゴリ | プロジェクト数 | 主な技術 |
|---|---:|---|
| 🤖 [エージェント AI & マルチエージェントシステム](./01-Agentic-AI/) | 6 | Google ADK, LangGraph, MCP, Agno, LangChain LCEL |
| 📚 [RAG & ナレッジエンジニアリング](./02-RAG-Knowledge/) | 5 | LangGraph, LlamaIndex, ChromaDB, Qdrant, Neo4j |
| 🛡️ [AI セーフティ & 品質エンジニアリング](./03-AI-Safety-Quality/) | 2 | NeMo Guardrails, LLM Judges, PII Detection |
| 🏭 [応用 AI](./04-Applied-AI/) | 2 | OCR, Document AI, Voice AI, FastAPI |
| 🧠 [NLP & 機械学習](./05-NLP-Machine-Learning/) | 1 | scikit-learn, NLTK, spaCy |

## 主な構築領域

- 🤖 エージェント AI とマルチエージェント・ワークフロー
- 🔧 LLM ツールと MCP オーケストレーション
- 📚 本番指向の RAG とナレッジシステム
- 📏 LLM/RAG の評価と品質エンジニアリング
- 🛡️ AI セーフティとプロンプトインジェクション対策
- 📄 ドキュメントインテリジェンスと検証ワークフロー
- 🎙️ 音声・マルチモーダル AI パイプライン
- 🧠 古典的な NLP と機械学習システム

## 注目プロジェクト

| プロジェクト | プロジェクト名（日本語） | 実証内容 |
|---|---|---|
| [AgentFlow — Dynamic Multi-Agent Workflow & Skill Orchestrator](./01-Agentic-AI/AgentFlow-Orchestrator/) | エージェントフロー — 動的マルチエージェント・ワークフロー＆スキル・オーケストレーター | 動的マルチエージェント・オーケストレーション |
| [Agentic AI MCP Tool Orchestration Platform](./01-Agentic-AI/MCP-Tool-Orchestration/) | エージェント AI MCP ツール・オーケストレーション・プラットフォーム | MCP とツール・オーケストレーション |
| [Production RAG Documentation Assistant](./02-RAG-Knowledge/Production-RAG/) | 本番指向 RAG ドキュメントアシスタント | 検索エンジニアリング |
| [LLM Guardrails & AI Safety Defense Lab](./03-AI-Safety-Quality/LLM-Guardrails/) | LLM ガードレール＆AI セーフティ・ディフェンスラボ | AI セーフティ |
| [RAG Evaluation & LLM Quality Engineering Harness](./02-RAG-Knowledge/RAG-Evaluation-Harness/) | RAG 評価＆LLM 品質エンジニアリング・ハーネス | AI 品質/評価 |

## カテゴリ別プロジェクト

### 🤖 エージェント AI & マルチエージェントシステム

| プロジェクト | プロジェクト名（日本語） | 実証する AI 機能 | 技術 |
|---|---|---|---|
| [AgentFlow Orchestrator](./01-Agentic-AI/AgentFlow-Orchestrator/) | エージェントフロー・オーケストレーター | 動的マルチエージェント・ワークフロー/DAG 生成 | Google ADK, FastAPI, React |
| [MCP Tool Orchestration](./01-Agentic-AI/MCP-Tool-Orchestration/) | MCP ツール・オーケストレーション | MCP ツールエコシステムとツール呼び出し | MCP, Agno, Streamlit |
| [E-Commerce Multi-Agent](./01-Agentic-AI/MultiAgent-Ecommerce/) | EC マルチエージェント | 階層型の専門エージェント | Google ADK, LiteLLM |
| [Order Returns & Fraud Agent](./01-Agentic-AI/OrderReturns-Fraud-Agent/) | 注文返品・不正検出エージェント | ステートフルな業務ワークフロー + HITL | LangGraph, FastAPI, SQLite |
| [Hospital Appointment Agent](./01-Agentic-AI/Hospital-Appointment-Agent/) | 病院予約エージェント | LLM による抽出 + 決定論的なカレンダー処理 | LangChain LCEL, Twilio SMS |
| [Multi-Agent Mindmap](./01-Agentic-AI/MultiAgent-Mindmap/) | マルチエージェント・マインドマップ | 3 エージェントによる反復レビュー/改善 | Streamlit, Ollama, markmap.js |

### 📚 RAG & ナレッジエンジニアリング

| プロジェクト | プロジェクト名（日本語） | 実証する AI 機能 | 技術 |
|---|---|---|---|
| [Production RAG Assistant](./02-RAG-Knowledge/Production-RAG/) | 本番指向 RAG アシスタント | 検索エンジニアリング + 回帰評価 | LangGraph, ChromaDB, BM25 |
| [Enterprise Knowledge Assistant](./02-RAG-Knowledge/Enterprise-Knowledge-Assistant/) | エンタープライズ・ナレッジアシスタント | ハイブリッド検索（ベクトル + BM25 + グラフ） | LlamaIndex, Qdrant, Cognee |
| [RAG Evaluation Harness](./02-RAG-Knowledge/RAG-Evaluation-Harness/) | RAG 評価ハーネス | RAG/LLM 品質の測定 | RAGAS, pytest, LLM judge |
| [LLM Wiki](./02-RAG-Knowledge/LLM-Wiki/) | LLM ウィキ | ドキュメントからナレッジベース生成 | FastAPI, React, D3 |
| [Knowledge Graph Builder](./02-RAG-Knowledge/Knowledge-Graph-Builder/) | ナレッジグラフ・ビルダー | グラフネイティブな構築とクエリ | Google ADK, Neo4j, SSE |

### 🛡️ AI セーフティ & 品質エンジニアリング

| プロジェクト | プロジェクト名（日本語） | 実証する AI 機能 | 技術 |
|---|---|---|---|
| [LLM Guardrails Defense Lab](./03-AI-Safety-Quality/LLM-Guardrails/) | LLM ガードレール・ディフェンスラボ | 専用の AI セーフティ制御 | NeMo Guardrails, Colang, Groq |
| [AI-Safe Support Ticket Classifier](./03-AI-Safety-Quality/Safe-Support-Ticket/) | AI セーフ・サポートチケット分類器 | AI ワークフローへのセキュリティ制御組み込み | LangGraph, PII redaction, judge LLM |

### 🏭 応用 AI

| プロジェクト | プロジェクト名（日本語） | 実証する AI 機能 | 技術 |
|---|---|---|---|
| [DocFlow Document Intelligence](./04-Applied-AI/DocFlow-Document-Intelligence/) | ドックフロー・ドキュメントインテリジェンス | 請求書は AI が読み取り、判断は決定論的なポリシーが行う | FastAPI, Streamlit, PyMuPDF, Tesseract OCR |
| [Research Voice Agent](./04-Applied-AI/Research-Voice-Agent/) | リサーチ・ボイスエージェント | エージェントが計画し、ツールが実行 → 完成したポッドキャスト | Google ADK, Ollama gpt-oss:120b, edge-tts, faster-whisper |

### 🧠 NLP & 機械学習

| プロジェクト | プロジェクト名（日本語） | 実証する AI 機能 | 技術 |
|---|---|---|---|
| [Sentiment Analysis Pipeline](./05-NLP-Machine-Learning/Sentiment-Analysis/README.ja.md/) | センチメント分析パイプライン | 古典的な NLP/ML | scikit-learn, TF-IDF, NLTK, spaCy |

## 技術カバレッジ

**LLM / AI**
Ollama · Ollama Cloud · Groq · LiteLLM

**エージェント AI**
Google ADK · LangGraph · LangChain · Agno · MCP

**RAG / ナレッジ**
ChromaDB · Qdrant · Neo4j · LlamaIndex · Cognee · BM25 · RRF

**評価**
RAGAS · LLM-as-a-Judge · pytest · ゴールデンデータセット

**AI セーフティ**
NeMo Guardrails · Colang · プロンプトインジェクション · PII 検出

**応用 AI**
OCR · ドキュメントインテリジェンス · STT · TTS · 音声 AI

**アプリケーション**
FastAPI · Streamlit · React · SQLite

## 横断的な AI エンジニアリング

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
- 決定論的バリデーション
- ヒューマンインザループ（HITL）
- エビデンスゲーティング
- チェックポイント管理

## プロジェクト選びのガイド

### エージェント AI をお探しですか？
- [AgentFlow Orchestrator](./01-Agentic-AI/AgentFlow-Orchestrator/) · [MCP Tool Orchestration](./01-Agentic-AI/MCP-Tool-Orchestration/) · [E-Commerce Multi-Agent](./01-Agentic-AI/MultiAgent-Ecommerce/) · [Order Returns & Fraud](./01-Agentic-AI/OrderReturns-Fraud-Agent/) · [Hospital Appointment](./01-Agentic-AI/Hospital-Appointment-Agent/) · [Multi-Agent Mindmap](./01-Agentic-AI/MultiAgent-Mindmap/)

### RAG / ナレッジエンジニアリングをお探しですか？
- [Production RAG](./02-RAG-Knowledge/Production-RAG/) · [Enterprise Knowledge Assistant](./02-RAG-Knowledge/Enterprise-Knowledge-Assistant/) · [RAG Evaluation Harness](./02-RAG-Knowledge/RAG-Evaluation-Harness/) · [LLM Wiki](./02-RAG-Knowledge/LLM-Wiki/) · [Knowledge Graph Builder](./02-RAG-Knowledge/Knowledge-Graph-Builder/)

### AI セーフティをお探しですか？
- [LLM Guardrails](./03-AI-Safety-Quality/LLM-Guardrails/) · [AI-Safe Support Ticket](./03-AI-Safety-Quality/Safe-Support-Ticket/)

### 応用 AI をお探しですか？
- [DocFlow Document Intelligence](./04-Applied-AI/DocFlow-Document-Intelligence/) · [Research Voice Agent](./04-Applied-AI/Research-Voice-Agent/)

### 古典 NLP/ML をお探しですか？
- [Sentiment Analysis](./05-NLP-Machine-Learning/Sentiment-Analysis/)

## ドキュメントの見方

| ドキュメント | 目的 |
|---|---|
| **README.ja.md**（このファイル） | リクルーター向けランディングページ — ポートフォリオ概要とナビゲーション（日本語版） |
| [README.md](./README.md) | 英語版ランディングページ |
| [PORTFOLIO_INDEX.md](./PORTFOLIO_INDEX.md) | 詳細カタログ — 全 16 プロジェクトのアーキテクチャ、差別化ポイント、リンク |
| **各プロジェクトの README** | プロジェクトごとの実装詳細 |

## AI 支援開発

このポートフォリオは、VS Code を使った AI 支援コーディング・ワークフローで開発しました。AI ツールによって実装を加速しつつ、アーキテクチャ、統合、テスト、デバッグ、検証については開発過程でレビューと改善を行っています。
