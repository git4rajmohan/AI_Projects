言語 / Languages: [English](README.md) | **日本語**

---

# 本番環境向け RAG ドキュメントアシスタント

> 本番指向の Retrieval-Augmented Generation パイプライン。3 つのチャンキング戦略、RRF で融合した BM25 + ベクトルのハイブリッド検索、主張ごとの引用付きの厳密なグラウンディング生成、誠実な拒否動作 — そして品質が低下した瞬間に 🟢 が反転する決定論的リグレッションゲート。

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C)
![ChromaDB](https://img.shields.io/badge/Vector%20Store-ChromaDB-00C853)
![FastAPI](https://img.shields.io/badge/FastAPI-Visualizer%20UI-009688?logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud%20gpt--oss%3A120b-white?logo=ollama)
![BM25](https://img.shields.io/badge/Retrieval-BM25%20%2B%20Vectors%20%2B%20RRF-orange)

## デモ動画

[![Production RAG Demo](https://img.youtube.com/vi/nK-iQ_vPdX0/0.jpg)](https://youtu.be/nK-iQ_vPdX0)

## なぜこのプロジェクトが存在するのか

検索エンジニアリングを、チャット UI ではなく一つの規律として示すプロジェクトです。誠実なハイブリッド検索、取得コンテキストからのみ生成され主張ごとに引用が付く回答、設計された拒否動作 — そして凍結済みゴールデンセット + リグレッションゲートにより、品質の変化を「感覚」ではなく「測定」で扱います。

## このプロジェクトが示すこと

- 3 つのチャンキング戦略 — 文字分割(意図的に壊したベースライン)、`###` ハイブリッドゲート付きの構造分割、埋め込みセマンティック — に加え、壊れたコードブロック/テーブルを数えるコンパレーター
- ハイブリッド検索:BM25 キーワード + ベクトル類似度を Reciprocal Rank Fusion(`k=60`)で融合
- `[Source: doc, Section: …]` 形式の引用か、明示的な拒否 — 厳密にグラウンディングされた生成
- 2 フェーズ評価:決定論的な LLM 不要メトリクス + 任意の Ragas LLM ジャッジ
- リグレッションゲート(ベースラインに対する 🟢/🟡/🔴)+ 30 件の記録済みスナップショット履歴

## アーキテクチャ

```text
INGESTION (offline)
docs/*.md → Chunk (3 strategies) → Embed (nomic-embed-text) → ChromaDB

QUERY TIME (online)
Question → Hybrid search (BM25 + vector + RRF) → Grounded prompt
         → Generate (gpt-oss:120b) → Cited answer | Refusal

EVALUATION
19-question frozen golden set → live pipeline → snapshot JSON
→ gate diff vs baseline → 🟢 PASS / 🟡 WARN / 🔴 FAIL (exit code for CI)
```

クエリパスは 3 ノードの LangGraph `StateGraph`(`retrieve → build_prompt → generate`)で構成され、検索エラー時に END へショートサーキットする条件エッジを持ちます — ノードは決して例外を投げず、読み取れるエラー文字列を state に設定します。

## ワークフロー

1. **Ingest(取り込み)** — Markdown を読み込み、選択した戦略でチャンク化し、埋め込みを生成して永続的な ChromaDB コレクションにアップサートします(再取り込みの前にドキュメント単位で古いチャンクを削除)
2. **Ask(質問)** — クエリを埋め込み、BM25 検索とベクトル検索を並列に実行(2 倍のオーバーフェッチ)し、RRF でランキングを融合。ソースラベル付きのトップ 5 チャンクを注入して、引用付きの回答を生成します
3. **Refuse(拒否)** — コーパスの範囲外の質問には *"I could not find an answer to this question in the provided documentation."* と返します — 設計され、測定対象の動作です(スイートには専用のネガティブ質問が含まれます)
4. **Gate(ゲート)** — 19 質問のゴールデンセットをライブパイプラインで再生し、メトリクスをスナップショット化してベースラインと差分を取ります。品質メトリクスの低下が 0.05 超で 🟡、0.15 超で 🔴(CI では非ゼロ終了)

## 技術スタック

| 領域 | 技術 |
|---|---|
| LLM | Ollama Cloud(`gpt-oss:120b`)- チャット/回答生成 |
| Embeddings | ローカル Ollama 経由の `nomic-embed-text`(768-d) |
| AI フレームワーク | LangGraph(`StateGraph`、純粋関数ノード 3 個) |
| ベクトル DB | ChromaDB(永続化、HNSW) |
| 検索 | BM25(`rank_bm25`)、コサインベクトル、RRF 融合 |
| バックエンド | FastAPI ステップ実行ビジュアライザー(バニラ JS SPA) |
| 評価 | 決定論的メトリクス + 任意の Ragas LLM ジャッジ(`glm-5.3-flash`) |

## 主要な AI エンジニアリングの概念

- **チャンクは検索の原子** — 同じクエリが文字分割では断片を返し、構造分割ではクリーンな引用付き回答を返すことをデモが証明します
- **2 つのリトリーバーは 1 つに勝る** — ベクトルは意味を、BM25 は正確なトークン(`MCPToolset`、`X-Goog-Api-Key`)を見つけます。RRF はランクだけでマージするため、スコアの較正は不要です
- **グラウンディングされた生成** — システムプロンプトは推論を禁じ、すべての主張は取得したチャンクを引用しなければなりません
- **コーパスからゴールデンセットを作る** — LLM が生成した後、クローズドブック・グラウンディング・重複排除(コサイン 0.9)の各フィルターで硬化させてから凍結します

## 安全性 / 信頼性

- 拒否動作は設計され、**測定**されています(2 つの専用ネガティブ質問に対する `refusal_accuracy`)
- リグレッションゲートは recall、citation coverage、must-term coverage、refusal accuracy、latency を監視します — Ragas の LLM スコアは参考として付きますが、判定を覆すことはありません(決定論的で再現可能なゲート)
- ノードは例外を投げる代わりにエラーを state に記録し、検索失敗時は読み取れるメッセージ 1 つでグラフを終了します
- スイートの再現性のため温度は 0 に固定。スナップショットには設定一式(戦略、リトリーバー、top_k、モデル、コーパス)を記録します

## テスト / 評価

同梱ベースライン(`eval/BASELINE.json`、埋め込みセマンティック 46 チャンク、ハイブリッド検索、top-5)の検証済みメトリクス:

| メトリック | 値 |
|---|---|
| recall@k | **1.0**(回答可能な質問はすべて該当セクションにヒット) |
| first relevant rank | 1.18 |
| must-term coverage | 0.67 |
| refusal accuracy | 0.5 |
| latency | 平均 2.2 秒 / p95 3.2 秒(質問あたり) |

- **19 質問の凍結ゴールデンセット**(15 セクション · 2 マルチホップ · 2 ネガティブ)。コーパスから LLM が生成し、クローズドブック + グラウンディング + 重複排除フィルターで硬化させてから凍結
- **30 件の評価スナップショット**を記録。ゲートは実行ごとにベースライン(または任意の 2 スナップショット)と差分を取ります
- ゴールデンセット生成は再現可能です:セクションごとに 2 ペア + マルチホップ + ネガティブケースを、凍結前にすべてフィルター検証します

## デモ

完全なウォークスルー:[`RAG_Production_Userguide.html`](RAG_Production_Userguide.html) — パイプライン図、モジュールマップ、ゲートフロー図を含む 4 タブガイド(Elevator Pitch / Non-Technical / Technical / Glossary)。プロジェクトドキュメント:[`Project_Documentation.md`](Project_Documentation.md)。

FastAPI ビジュアライザーは **Ingestion**、**Inference**、**Evaluation** の 3 つのタブを提供します。パイプラインの各ステップを 1 つずつ実行し、詳細パネル(チャンクプレビュー、BM25/ベクトル/融合ランキングのトレース、保存された ChromaDB 行、ゲート差分テーブル)を表示します。

## 実行方法

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure .env (project root — see settings in config/settings.py)
#    OLLAMA_API_KEY=<your ollama.com key>
#    OLLAMA_CHAT_BASE_URL=https://ollama.com/v1
#    OLLAMA_CHAT_MODEL=gpt-oss:120b
#    OLLAMA_EMBED_BASE_URL=http://localhost:11434/v1
#    OLLAMA_EMBED_MODEL=nomic-embed-text

# 3. Keep local Ollama running (serves the embeddings model)

# 4. Start the visualizer
python -m uvicorn ui.server:app --port 8000
#    → open http://localhost:8000

# Optional CLI chunking demo
python demo/01_chunking_comparison.py

# Evaluation gate from CLI
python -m eval.gate <snapshot_id>
```

チャットには Ollama Cloud の API キー、埋め込みには `nomic-embed-text` を備えたローカル Ollama が必要です。

## プロジェクト構成

```text
Production-RAG/
├── chunking/          # character · structural (H2+H3 gate) · embedding-semantic · comparison
├── vectorstore/       # embedder (OpenAI-compatible) · ChromaDB store (upsert, stale delete)
├── retrieval/         # pure vector search · hybrid BM25+vector+RRF with per-stage trace
├── generation/        # grounded prompt builder · answer generator with citation regex
├── pipeline/          # LangGraph StateGraph: state · nodes (try/except) · graph (conditional edge)
├── eval/              # golden_generator (LLM + 3 filters) · metrics · runner · gate · ragas_eval
│   └── snapshots/     # 30 recorded runs + BASELINE.json + golden_set.jsonl (19 pairs)
├── ui/                # FastAPI visualizer: step-by-step runners, param config, static SPA
├── docs/              # 2 source Markdown documents (healthcare MCP guide, AI-agents-vs-MCP)
├── demo/              # CLI demo sequence proving the chunking story
├── main.py            # demo sequence entry point
└── RAG_Production_Userguide.html
```

## このプロジェクトが他と違う点

検索エンジニアリングに本番形式のリグレッション評価を組み合わせたものです — Enterprise Knowledge Assistant(グラフ検索と evidence gate を追加)や RAG Evaluation Harness(RAG エンドポイントそのものではなく、任意の RAG エンドポイントを評価する)とは異なります。

## AI 支援開発

このプロジェクトは AI 支援のコーディングワークフローを用いて開発されました。アーキテクチャ、実装上の意思決定、テスト、デバッグ、検証は開発中にレビューと改善が行われています。
