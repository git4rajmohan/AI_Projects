言語 / Languages: [English](README.md) | **日本語**

---

# Enterprise Knowledge Assistant — ハイブリッド Graph RAG

> 11 冊の社内 HR/ポリシー PDF を対象とする完全ローカルの RAG チャットボット。ハイブリッドリトリーバーがセマンティックベクトル検索、BM25 キーワード検索、ナレッジグラフの関係性を融合し、較正済みの **evidence gate** がドキュメントが質問を裏付けない場合は *LLM を一度も呼び出す前に* 回答を拒否します。すべての主張には実際のファイル名が付きます。

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![LlamaIndex](https://img.shields.io/badge/LlamaIndex-0.14-Rasa?logo=data&logoColor=white)
![Cognee](https://img.shields.io/badge/Cognee-Knowledge%20Graph-1.4.2-blue)
![Qdrant](https://img.shields.io/badge/Vector%20Store-Qdrant-DC244C?logo=qdrant&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud%20gpt--oss%3A120b-white?logo=ollama)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-30_automated-4ade80)

## なぜこのプロジェクトが存在するのか

グラウンディングがプロンプト上の指示ではなく、機械的なゲートとして機能するハイブリッド(ベクトル + レキシカル + グラフ)検索を示すプロジェクトです。ハルシネーションは、プロンプトが利くことを祈るのではなく、構造的に不可能になっています。

## このプロジェクトが示すこと

- 3 本足のハイブリッド検索 — セマンティックベクトル検索、BM25 キーワード検索、ナレッジグラフのトリプレット — を Reciprocal Rank Fusion(ランクのみの計算)で融合
- データから較正された **evidence gate**(最大コサイン ≥ 0.55)が、証拠が薄い場合は *いかなる LLM 呼び出しの前にも* 拒否
- Cognee によるナレッジグラフ取り込み:11 PDF のエンタープライズコーパスから 1,604 ノード / 4,605 リレーションシップ
- 7 カテゴリの 58 質問ゴールデンデータセットと、メトリクス低下時に**ビルドを失敗させる**(exit 1)品質ゲート
- 出典(ノードごとのソースチャンク + パイプライン)付きのインタラクティブなナレッジグラフ可視化

## アーキテクチャ

```text
INGESTION (one-time)
11 HR PDFs → Cognee (chunk → graph → embed) → Qdrant (131 chunks · 768-d)
                                            → Knowledge graph (1,604 nodes · 4,605 rels)
                                            → Hash ledger (skip duplicates)

QUERY TIME
Question (Streamlit chat)
  → Hybrid retriever (vector + BM25 + graph triplets → RRF fusion)
  → Evidence gate (best cosine ≥ 0.55?) ── no → refuse, LLM never called
  → Ollama LLM (grounded prompt) → Answer + file citations
```

## ワークフロー

1. **一度だけ取り込み** — Cognee が PDF をチャンク化し、エンティティ/リレーションシップを抽出してナレッジグラフを構築し、すべてをローカル Qdrant に埋め込みます。ハッシュ台帳が既に取り込んだドキュメントをスキップします
2. **質問** — ハイブリッドリトリーバーが 3 本の検索を並列実行。RRF が 2 本のチャンク検索を融合します(各ヒットは「どの検索で見つかったか」を記録 — 例 "vector+bm25 ✔")。グラフトリプレット(`travel expenses ──includes_section──> air travel`)がそれに並びます
3. **ゲート** — evidence gate は最大コサインスコアを較正済みの 0.55 閾値と比較します。無関係な質問(テストではスコア ≤ 0.53)は機械的に拒否 — ハルシネーションリスクはゼロです
4. **生成** — LlamaIndex パイプラインがグラウンディングされたプロンプトで、取得済みの証拠からのみ回答を合成します。すべての回答には実際のコーパスファイル名の Sources リストが付きます
5. **検査** — デバッグモードは証拠チェーン全体を公開します:ヒットごとのコサインスコア、BM25 ランキング、RRF の融合順序、グラフトリプレット。グラフビューでは Cognee のナレッジマップを開けます(Story/Flow/Force レイアウト、ノードごとの出典)

## 技術スタック

| 領域 | 技術 |
|---|---|
| LLM | Ollama Cloud(`gpt-oss:120b`)またはローカル `qwen3:8b` |
| Embeddings | ローカル Ollama 経由の `nomic-embed-text`(768-d) |
| RAG フレームワーク | LlamaIndex 0.14 |
| ナレッジグラフ | Cognee 1.4.2(エンティティ/リレーションシップ抽出) |
| ベクトル DB | Qdrant(ローカル、6 コレクション) |
| 検索 | BM25(`rank-bm25`)、コサインベクトル、グラフトリプレット検索、RRF |
| UI | Streamlit チャット + サイドバー(ドキュメント一覧、ヘルスプローブ、グラフビュー、デバッグモード) |
| テスト | pytest(30 テスト) |

## 主要な AI エンジニアリングの概念

- **生成する前に拒否する** — ゲートにより、拒否はプロンプト任せではなく機械的になります
- **3 本足は 1 本に勝る** — ベクトルは意味を、BM25 は正確なポリシー ID(`ACME-HR-002`)を、グラフは関係性(何が何を規定するか)を見つけます
- **仮定せず測る** — 58 質問の評価と、メトリクスが低下すると CI を失敗させる品質ゲートファイル

## 安全性 / 信頼性

- 証拠が薄い場合、evidence gate が生成の前に拒否します(較正済み閾値、単体テスト済み)
- グラウンディングされたプロンプト層が第 2 の防御 — 2 つの拒否層はいずれも単体テスト済み
- ハッシュ台帳による取り込みは重複をスキップ。サイドバーにはライブのサービスヘルスプローブを実装(プレースホルダーではなく実プローブ)
- すべての回答は実際のファイル名を引用します。裏付けのない質問には誠実に「見つかりませんでした」と返します

## テスト / 評価

同梱ベースライン(58 質問、7 カテゴリ — 事実、言い換え、マルチホップ、ディストラクター、裏付けなし)の検証済み結果:

| メトリック | 結果 |
|---|---|
| Citation accuracy | **96%** |
| Context relevance(検索精度) | **94%** |
| Refusal accuracy(gate + prompt の 2 層) | 91% |
| Answer correctness(コーパス検証済みキーワード) | 84% |
| Faithfulness(LLM 判定) | 77.5%(ゲートは 85% — 改善バックログとして公開) |

- 融合、evidence gate、グラウンディング、取り込み、Qdrant、検索、ゴールデンデータセット、設定、ヘルスをカバーする **30 件の pytest テスト**
- `quality_gates.yaml` はメトリクスが低下すると実行を失敗させます(exit 1)— CI 対応
- ダッシュボードは弱いメトリクスを隠さず明示します(検索は強く、生成の誠実さが改善バックログ)

## デモ

[`docs/screenshots/`](docs/screenshots/) に 13 枚の実行スクリーンショット — 引用付きのグラウンディング回答、裏付けのない質問への拒否、RRF 融合の詳細を含むデバッグトレース、ナレッジグラフビュー:

| 新規起動 | グラウンディング回答 | 拒否 | グラフビュー |
|:---:|:---:|:---:|:---:|
| ![Fresh](docs/screenshots/01-fresh-start.png) | ![Answer](docs/screenshots/03-grounded-answer.png) | ![Refusal](docs/screenshots/04-refusal.png) | ![Graph](docs/screenshots/07-graph-view.png) |

完全なウォークスルー:[`Enterprise Knowledge Assistant_Userguide.html`](Enterprise%20Knowledge%20Assistant_Userguide.html) — パイプライン図、デバッグトレースの解説、用語集を含む 4 タブガイド。テスト手順書:[`howtotest.md`](howtotest.md)。

## 実行方法

```powershell
# 1. Install (Python 3.11 tested)
pip install -r requirements.txt

# 2. Configure .env (copy from .env.example)
#    OLLAMA_API_KEY=<your ollama.com key>
#    OLLAMA_CLOUD_BASE_URL=https://ollama.com/v1
#    OLLAMA_EMBED_MODEL=nomic-embed-text (local daemon)
#    QDRANT_URL=http://localhost:6333

# 3. Start services (order matters): local Ollama → Qdrant → Streamlit
#    - Ollama daemon: ollama serve  (embeddings, port 11434)
#    - Qdrant:        start your local Qdrant instance (port 6333)
# 4. Run the app
.\.venv\Scripts\python.exe -m streamlit run app\main.py

# 5. Tests (30) and evaluation
pytest tests/
python scripts/evaluate_rag.py
```

必要なもの:埋め込み用の `nomic-embed-text` を備えたローカル Ollama(クラウドプランには埋め込みモデルがありません)、ローカルの Qdrant インスタンス、LLM 用の Ollama Cloud API キー。取り込みは `scripts/ingest_corpus.py`、インタラクティブなグラフは `scripts/visualize_graph.py` で行います。

## プロジェクト構成

```text
Enterprise-Knowledge-Assistant/
├── app/
│   ├── main.py             # Streamlit entry point
│   ├── config/             # settings from .env (models, thresholds, paths)
│   ├── ingestion/          # Cognee ingestion + hash ledger
│   ├── knowledge/          # knowledge-graph access (nodes, edges, triplets)
│   ├── retrieval/          # hybrid retriever: vector + BM25 + graph → RRF fusion
│   ├── llm/                # Ollama local/cloud client + grounded prompt
│   ├── evaluation/         # evidence gate + quality-gates evaluation
│   ├── vectorstore/        # Qdrant adapter (6 collections)
│   ├── ui/                 # Streamlit components (chat, sidebar, debug panel)
│   └── static/             # graph visualization assets
├── data/
│   ├── documents/          # the 11-file HR/policy PDF corpus
│   └── eval/               # golden_dataset.jsonl (58 questions) + quality_gates.yaml
├── evaluation/             # evaluation run outputs (results.csv/json)
├── scripts/                # ingest, evaluate, visualize graph, probes, judges
├── tests/                  # 12 test modules / 30 tests
├── docs/screenshots/       # 13 real UI captures
└── Enterprise Knowledge Assistant_Userguide.html
```

## このプロジェクトが他と違う点

ベクトル + BM25 + **ナレッジグラフ**のハイブリッド検索と機械的な evidence gate の組み合わせです — Production RAG の 2 本足ハイブリッド + リグレッションゲート方式、そして Knowledge Graph Builder(グラフ証拠を RAG の回答に融合するのではなく、ユーザーデータからグラフを構築する)と対照的です。

## AI 支援開発

このプロジェクトは AI 支援のコーディングワークフローを用いて開発されました。アーキテクチャ、実装上の意思決定、テスト、デバッグ、検証は開発中にレビューと改善が行われています。