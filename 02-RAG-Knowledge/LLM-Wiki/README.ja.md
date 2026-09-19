言語 / Languages: [English](README.md) | **日本語**

---

# 📚 LLM Wiki — AI ナレッジベースジェネレーター

> ドキュメントの山から、生きた相互リンク型ナレッジベースをハンズフリーで構築します。ソースドキュメントを `Clippings/` に置いて *Run Ingest* を押すと、LLM が構造化された wiki を書き上げます — ソースページ、エンティティページ、コンセプトページ、マスターインデックスを、Obsidian 方式の `[[wiki-links]]` で縫い合わせます。フォルダツリーや D3 フォースグラフで閲覧し、出典を引用し自信度を自己採点するストリーミングチャットで問い合わせられます。

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18_Vite-61DAFB?logo=react&logoColor=black)
![D3.js](https://img.shields.io/badge/D3-7_Graph_View-F9A03C?logo=d3.js&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-8_providers_%2B_local_GGUF-8B5CF6)
![Storage](https://img.shields.io/badge/Storage-Plain_Markdown-16a34a)

## デモ動画

[![LLM Wiki Demo](https://img.youtube.com/vi/dayj8CjGDhM/0.jpg)](https://youtu.be/dayj8CjGDhM)

## なぜこのプロジェクトが存在するのか

LLM の出力が、チャットが終わると消える回答ではなく、永続的でナビゲート可能なナレッジベース — wiki リンクとグラフ可視化を備えた Git フレンドリーな Markdown — になり得ることを示すプロジェクトです。wiki 構築の知性はアプリの中にはありません。契約(`AGENTS.md` スキーマ + 厳格な `===FILE:===` 出力形式 + 後処理ガード)の中にあります。そのため同じパイプラインが、2 GB のローカル GGUF モデルからフロンティアのクラウドモデルまでそのまま動きます。

## このプロジェクトが示すこと

- ドキュメントからナレッジへの変換:1 回の ingest でソースページ、エンティティページ、コンセプトページ、更新済みインデックスを出力
- エンティティ/コンセプトを永続的な共有ページへ抽出(1 つのソースが 5〜15 ページに触れるのは設計どおり — エンティティとコンセプトを書き直さず再利用するため)
- プレーンな `.md` ファイル間の Obsidian 方式 `[[wiki-links]]` ナビゲーション(データベースなし)
- wiki のリンク構造のグラフ可視化(D3 フォースグラフ、孤立ノード検出付き)
- 出典引用付きのストリーミングチャット(SSE)— wiki のみから回答し、引用チップと自信度スコアを表示
- 2 フェーズの wiki Health Check:即時のプログラム的 lint(壊れたリンク、孤立ページ、行き止まり)+ LLM による叙述的レビュー

## アーキテクチャ

```text
Documents (Clippings/ — .md .docx .xlsx .pdf .pptx, never modified)
   ↓  single streaming LLM call per source (AGENTS.md schema + current index.md in context)
===FILE:=== protocol → thinking-strip → path slugify/type-inference → guards
   ↓
Source / Entity / Concept Pages + index.md  (plain .md + YAML frontmatter)
   ↓
[[Wiki Links]] → folder tree view · D3 force graph
   ↓
Query (SSE): keyword/semantic page retrieval → grounded streaming answer
             → confidence score + citation chips ("wiki mode" only answers from the wiki)
```

- **バックエンド**:FastAPI — 6 ルーター(`config`、`ingest`、`wiki`、`query`、`lint`、`utils`)+ SPA 静的マウント
- **フロントエンド**:React 18 + Vite + Zustand + TailwindCSS、3 タブ(Config / View Wiki / Query)
- **LLM**:`openai` + `anthropic` SDK 経由の 8 プロバイダー — OpenAI、Azure OpenAI、Anthropic、Ollama、LM Studio、Together、Baseten、そして **local-cpu**:GGUF モデル(Gemma 2 2B、Llama 3.2 3B、Qwen 2.5 3B、Phi 3.5 Mini など)を `llama-cpp-python` でプロセス内サーブ。Hugging Face からオンデマンドでダウンロード
- **ストレージ**:`wiki/sources|entities|concepts|analyses` 配下のプレーン Markdown + YAML frontmatter — データベースなし、Obsidian 互換、Git フレンドリー、完全に再生成可能(`Clippings/` は不変)

## 主要な AI エンジニアリングの概念

- **スキーマはコードではなく `AGENTS.md` に** — プロジェクトごとのエンティティ/コンセプト分類は編集可能な Markdown で、すべての ingest プロンプトに埋め込まれます
- **`===FILE:===` 出力プロトコル** — モデルは入れ子の JSON より「マーカー付きでファイルを出力する」方がはるかに確実に従います。パーサーは寛容です(slugify、frontmatter からのタイプディレクトリ推論、退化ループの折りたたみ)
- **小さなモデルへの多層防御** — thinking-strip → 空回答リトライ → トークン上限 → タイムアウト → 抽出的フォールバック → インデックス自動再構築
- **グラウンディングされた検索** — キーワードのトークンオーバーラップスコアリング(top 8)または LLM によるセマンティックページ選択。クラウドモデルは 40,000 文字のコンテキスト予算、ローカルモデルは 12,000 文字 + スニペット削減
- **誠実な失敗** — システムプロンプトは一般知識からの回答を固く禁じています。wiki が知らないことについては、モデルはそう言わなければなりません

## 安全性 / 信頼性

- グラウンディング契約:wiki モードは取得ページから**のみ**回答します — 外部知識はシステムプロンプトで禁止。欠落トピックには固定の拒否メッセージで対応
- パス安全性:すべてのファイル操作はトラバーサルに対する解決済みパスガードを通ります。アップロードと LLM が出力したパスはディスクに触れる前にサニタイズされます
- `wiki/log.md` は追記専用で、LLM が上書きすることは決してできません
- キーのマスキング:バックエンドは保存済み API キーを `***` で返し、実際のキーはサーバー側で復元します。環境変数から与えたキーが `config.json` に書き戻されることはありません
- 設定の優先順位:`config.json`(UI 保存値)> `.env`/環境変数(`LLMWIKI_*` 変数)— 詳細は `.env.example` を参照

## 技術スタック

| 領域 | 技術 |
|---|---|
| LLM プロバイダー | OpenAI · Azure OpenAI · Anthropic · Ollama · LM Studio · Together · Baseten · local-cpu GGUF(`llama-cpp-python`) |
| バックエンド | FastAPI · Uvicorn · Pydantic v2 · SSE ストリーミング |
| ドキュメント解析 | `python-docx` · `openpyxl` · `pypdf` · `python-pptx` |
| フロントエンド | React 18 · Vite 5 · Zustand 4 · TailwindCSS 3 · D3 7 · react-markdown 9 |
| ナレッジベース | Markdown + YAML frontmatter(`python-frontmatter`)、Obsidian 互換 |
| 設定 | `config.json`(gitignore 済み)+ `.env` フォールバック(`LLMWIKI_*` 変数) |

## デモ

[`docs/screenshots/`](docs/screenshots/) に実際の UI キャプチャ:

| Ingest | Wiki ツリー | Wiki グラフ |
|:---:|:---:|:---:|
| ![Ingest screen](docs/screenshots/01-ingest-screen.jpg) | ![Wiki tree view](docs/screenshots/02-view-wiki-tree.jpg) | ![Wiki graph view](docs/screenshots/03-view-wiki-graph.jpg) |
| **引用付き Query** | **LLM 接続** | **Health check** |
| ![Query page](docs/screenshots/04-query-page.jpg) | ![LLM connection](docs/screenshots/05-llm-connection.jpg) | ![Health check](docs/screenshots/06-health-check.jpg) |

完全なウォークスルー:[`LLMWikiUI_Userguide.html`](LLMWikiUI_Userguide.html) — ingest 契約、検索の内部動作、SSE イベントスキーマ、Health Check の各フェーズを詳説した 4 タブガイド(Elevator Pitch / Non-Technical / Technical / Glossary)。

## 実行方法

```bash
# 1. Backend
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt

# 2. LLM credentials (optional) — copy .env.example to .env and fill in,
#    or just type the key in the Config tab (stored in gitignored config.json)
copy .env.example .env

# 3. Frontend dependencies
cd frontend
npm install

# 4. Development — terminal 1 (backend), terminal 2 (frontend)
.venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # → http://localhost:5173

# 5. Production (single port) — build the SPA, then serve it from FastAPI
cd frontend && npm run build
cd ..
.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# → http://localhost:8000
```

初回利用:Config タブを開く → プロバイダーを選択(キーレスの GGUF モデルなら `local-cpu`)→ *Test Connection* → wiki プロジェクトを作成 → その `Clippings/` フォルダにドキュメントを置く → *Run Ingest*。

Python 3.10+ と Node.js 18+ が必要です。クラウドプロバイダーには API キーが必要ですが、Ollama/LM Studio/local-cpu はキーなしで動きます。

## ワークフロー

1. **設定** — LLM プロバイダーとモデルを一度だけ設定します(8 プロバイダー。Test Connection で検証)
2. **プロジェクト作成** — 1 フォルダ = 1 wiki。標準スキャフォールド(`wiki/`、`Clippings/`、`raw/`、`AGENTS.md`)が自動生成されます
3. **Ingest** — LLM が各ソースを読み、ソースページ + エンティティページ + コンセプトページ + 更新済みインデックスを書きます。呼び出しごとに `AGENTS.md` と現在の `index.md` がコンテキストに含まれるため、wiki が成長しても命名の一貫性が保たれます。ログエントリは `wiki/log.md` に記録され、インデックスは安全網として自動再構築されます
4. **閲覧** — 読むにはツリービュー、知識の形を見るにはグラフビュー(孤立ノード = Health Check が指摘する孤立ページ)
5. **Query & Health Check** — 引用と自信度付きのストリーミング回答。2 フェーズの lint が壊れたリンク、孤立ページ、行き止まり、矛盾、コンセプトの欠落を検出します

## このプロジェクトが他と違う点

永続的でナビゲート可能な Git フレンドリーなナレッジベースを生み出します — チャットファーストの RAG アシスタントでは、抽出された知識はベクトルストアに宿り、回答はセッションとともに消えます。ここではナレッジベースそのものがプロダクトです。人間が読めて、Obsidian 互換で、Git でバージョン管理でき、LLM がそれを維持します。

## AI 支援開発

このプロジェクトは VS Code 上の AI 支援コーディングワークフローを用いて開発されました。AI ツールを実装の高速化に使用しつつ、アーキテクチャ、統合、テスト、デバッグ、検証は開発中にレビューと改善が行われています。
