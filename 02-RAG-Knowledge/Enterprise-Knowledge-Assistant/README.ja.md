言語 / Languages: [English](README.md) | **日本語**

---

# エンタープライズナレッジアシスタント — ハイブリッド Graph RAG

> 11 冊の社内 HR/ポリシー PDF を対象とする完全ローカルの RAG チャットボット。ハイブリッドリトリーバーがセマンティックベクトル検索、BM25 キーワード検索、ナレッジグラフの関係性を融合し、較正済みの **evidence gate** がドキュメントが質問を裏付けない場合は *LLM を一度も呼び出す前に* 回答を拒否します。すべての主張には実際のファイル名が付きます。

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![LlamaIndex](https://img.shields.io/badge/LlamaIndex-0.14-Rasa?logo=data&logoColor=white)
![Cognee](https://img.shields.io/badge/Cognee-Knowledge%20Graph-1.4.2-blue)
![Qdrant](https://img.shields.io/badge/Vector%20Store-Qdrant-DC244C?logo=qdrant&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud%20gpt--oss%3A120b-white?logo=ollama)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-30_automated-4ade80)

## デモ動画

[![Enterprise Knowledge Assistant Demo](https://img.youtube.com/vi/xhG9u-uPp8Y/0.jpg)](https://youtu.be/xhG9u-uPp8Y)

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
データ取り込み (初回のみ)
11件のHR関連PDF → Cognee (チャンク分割 → グラフ化 → 埋め込みベクター化)
                 → Qdrant (131チャンク · 768次元)
                 → ナレッジグラフ (1,604ノード · 4,605リレーション)
                 → ハッシュ台帳 (重複スキップ)

クエリ処理 (オンライン)
質問入力 (Streamlit チャット)
  → ハイブリッド検索 (ベクター + BM25 + グラフ三つ組(トリプレット) → RRF統合)
  → エビデンスゲート (最高コサイン類似度 ≥ 0.55?)
      └── いいえ (No) → 回答拒否 (LLMは呼び出されません)
      └── はい (Yes)  → Ollama LLM (根拠付きプロンプト) → 回答 + ファイル引用情報
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
│   ├── main.py              # Streamlit エントリーポイント
│   ├── config/              # .env から設定を読み込み (モデル、しきい値、パス)
│   ├── ingestion/           # Cognee によるデータ取り込み + ハッシュ台帳
│   ├── knowledge/           # ナレッジグラフ アクセス制御 (ノード、エッジ、三つ組)
│   ├── retrieval/           # ハイブリッド検索エンジン: ベクター + BM25 + グラフ → RRF統合
│   ├── llm/                 # Ollama (ローカル/クラウド) クライアント + 根拠付きプロンプト
│   ├── evaluation/          # エビデンスゲート + クオリティゲート評価
│   ├── vectorstore/         # Qdrant アダプター (6つのコレクション)
│   ├── ui/                  # Streamlit UI コンポーネント (チャット、サイドバー、デバッグパネル)
│   └── static/              # グラフ可視化用アセット
├── data/
│   ├── documents/           # 人事・規定関連 PDF コーパス (11ファイル)
│   └── eval/                # golden_dataset.jsonl (ゴールデンデータセット: 58の質問) + quality_gates.yaml
├── evaluation/              # 評価実行ログ・出力結果 (results.csv/json)
├── scripts/                 # データ取り込み、評価実行、グラフ可視化、各種プローブ・判定スクリプト
├── tests/                   # 12のテストモジュール / 計30件のテストケース
├── docs/screenshots/        # 実際の UI キャプチャ画像 (13点)
└── Enterprise Knowledge Assistant_Userguide.html
```

## このプロジェクトが他と違う点

ベクトル + BM25 + **ナレッジグラフ**のハイブリッド検索と機械的な evidence gate の組み合わせです — Production RAG の 2 本足ハイブリッド + リグレッションゲート方式、そして Knowledge Graph Builder(グラフ証拠を RAG の回答に融合するのではなく、ユーザーデータからグラフを構築する)と対照的です。

## AI 支援開発

このプロジェクトは AI 支援のコーディングワークフローを用いて開発されました。アーキテクチャ、実装上の意思決定、テスト、デバッグ、検証は開発中にレビューと改善が行われています。
