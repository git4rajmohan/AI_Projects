言語 / Languages: [English](README.md) | **日本語**

# Agent2Agent Explorer — リモート A2A エージェント探索・検証・委譲

**公開エージェントレジストリから、組織をまたいで完了したタスクまで — 実際のタスクが完了するまで何も信用しない。**

[ポートフォリオ](../../README.ja.md) | [ユーザーガイド（英語）](A2A_Explorer_Userguide.html)

独立してホストされたサードパーティの A2A エージェントを発見・検証し、タスクを委譲する Python 製 A2A クライアント/エクスプローラーです。ローカルの 2 エージェント デモも同梱しています。`a2a-sdk 1.3.0` 上に構築され、ローカルのデモ エージェントは **Ollama Cloud** 経由で応答します。

## このプロジェクトの目的

*他人の* エージェントを呼び出すことは、自分のエージェントを呼び出すこととは違います。アドレスも、できることも、プロトコルに対応しているかも、認証情報が必要かも分からない — そもそもその URL にあるのがエージェントなのか、単なる Web ページや REST API なのかすら分かりません。URL を貼り付けて願うのは、統合が壊れるやり方です。Agent2Agent Explorer はその「初対面」を正しく扱います。**ディレクトリが候補を見つけ、Agent Card が能力を宣伝し、バリデーターが証明する — 相手のエージェント自身が完了したタスクだけが相互運用性の証拠です。200 OK を返す Web ページは何も証明しません。**

## 実証する機能

- **一括でなく段階的な検証** — Card · Protocol · Endpoint · Authentication · Task
  execution の 5 つの独立したチェックが、それぞれ個別の合否バッジを持ちます。
  カードが有効でもエンドポイントが死んでいれば、そのように表示されます。
  `task_ready` には Protocol と Endpoint の合格が必要で、「Task execution」は
  実際に完了したタスクだけが緑にします。
- **実在するレジストリからの発見** — 検証済みの公開 API（`GET /api/agents`、
  エージェント詳細解決、クライアント側フィルタリング、スクレイピングなし、
  パス推測なし）に基づく a2aregistry.org アダプター。URL 貼り付けは常に使える
  フォールバックで、レジストリの *Web ページ* リンクでも実際のカードへ自動解決します。
- **SDK ファースト** — カードは `a2a.parse_agent_card`、タスクは SDK の
  `ClientFactory` で処理。アプリは独自のプロトコル メッセージやレジストリ
  エンドポイントを発明しません。
- **見えるタスクライフサイクル** — `SUBMITTED → WORKING → COMPLETED`(または
  FAILED / CANCELED / REJECTED / TIMEOUT)。両側が対応する場合のみストリーミング、
  それ以外はハードタイムアウト付きポーリング。タスクなしの返信(message-only reply)も
  一級のラベル付きケースとして扱います。
- **決定論的ルーティング + 並列委譲** — コーディネーターは *宣伝された skill* への
  単語オーバーラップでタスクをルーティングし、送信前に明示的なユーザー確認を要求します
  (LLM が URL を選んだり発明したりすることはありません)。`parallel` モードは
  明示的に選ばれた 2 つの保存エージェントへ同じタスクを送り、エージェントごとの
  属性付きで結果を返します。
- **信頼しない出力の規律** — リモートの結果は属性付きでそのまま表示され、実行は
  しません。成果物(artifact)は一覧表示のみで自動ダウンロードしません。x402 形式の
  有料ツール提案は検出して警告し、決して支払いません。

## アーキテクチャ

```text
ローカル コーディネーター
      | 発見
      v
公開エージェント ディレクトリ (a2aregistry.org、検証済み API)
      | 候補の Agent Card URL を返す
      v
リモート Agent Card  -- エンドポイント + スキル + 認証を宣伝
      v
リモート A2A エンドポイント (HTTPS、SSRF 対策、リダイレクト禁止)
      | タスク要求 / タスク結果
      v
サードパーティ エージェント  -> 属性付きの結果がローカル コーディネーターへ
```

すべての概念が 1 つのファイルを持ち、アプリは公式 `a2a-sdk 1.3.0` の周りの接着剤です。
Streamlit ページ(`webui.py`)と CLI(`remote_agents_cli.py`、`coordinator.py`)は
同じパイプライン関数を呼びます。詳細は
[docs/remote_agent_architecture.md](docs/remote_agent_architecture.md)（英語）を参照してください。

**技術構成：** Python 3.11+ · a2a-sdk 1.3.0 (`[http-server]` extra) ·
JSON-RPC + HTTP+JSON トランスポート · Streamlit · FastAPI · httpx · SQLite ·
Ollama Cloud (`gpt-oss:120b`) · pytest + pytest-asyncio

## ローカル実行（Windows PowerShell）

このプロジェクトのディレクトリで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env を編集: OLLAMA_API_KEY を https://ollama.com/settings/keys から取得

# オフライン検証: LLM 接続 + ローカル 2 エージェント往復
.\.venv\Scripts\python.exe smoke_test.py
.\.venv\Scripts\python.exe demo.py

# エクスプローラー（推奨）
.\.venv\Scripts\python.exe -m streamlit run webui.py
#    -> http://localhost:8511 — Discover → Save → Send Task → Saved Agents

# 同じ操作をコマンドラインから
.\.venv\Scripts\python.exe remote_agents_cli.py search <query>        # 公開レジストリ
.\.venv\Scripts\python.exe remote_agents_cli.py discover <card-url>   # カード + 段階的検証
.\.venv\Scripts\python.exe remote_agents_cli.py save <card-url>
.\.venv\Scripts\python.exe remote_agents_cli.py task <id|card-url> "your question"
.\.venv\Scripts\python.exe coordinator.py remote "echo hello"         # スキル一致 + 確認
.\.venv\Scripts\python.exe coordinator.py parallel 1 2 "your question" # 並列委譲
```

**ローカル** の worker エージェントを実行するターミナルでのみ
`ALLOW_LOCAL_AGENTS="true"` を先に設定してください。公開サードパーティ
エージェントには追加設定が不要です。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q   # 64 テスト合格
```

テストスイートは完全にオフラインです。SSRF/DNS/レジストリ応答のモックと、
同じ SDK で構築したローカル A2A テスト サーバー（ベアラートークン保護のものを含む）
を使い、インターネット接続は不要です。SSRF ブロック（プライベート/ループバック/
メタデータ IP、リダイレクト）、カード スキーマ検証、段階的エンドポイント チェック、
タスクライフサイクル、認証情報の分離とログの墨消し、決定論的ルーティングと
並列委譲をカバーします。

## 公開エージェント テスト報告（実際のサードパーティ相互運用）

| | |
|---|---|
| エージェント | **Swarmnest** (swarmnest.ai、運営: Swarmnest) |
| 発見方法 | `a2aregistry.org` 公開 API (`GET /api/agents`) |
| Agent Card URL | `https://swarmnest.ai/.well-known/agent-card.json` |
| テスト日 | 2026-10-31 (JST) |
| 認証 | 不要 |
| 送信タスク | "MCP server for Postgres"（宣伝されていた `search-directory` スキル） |
| 結果 | **COMPLETED** — テキスト要約 + 構造化 JSON（23 件、上位 5 件にリンク） |

このカードでの検証パイプライン: `Agent Card: VALID / Protocol: SUPPORTED /
Endpoint: REACHABLE / Authentication: NONE REQUIRED`、その後実際のタスクが完了しました。
さらに 2026-10-31 に、2 つの独立した公開エージェント（Swarmnest と Public Adjusters
Directory、publicadjusters.fyi）への**並列委譲**も検証 — 1 回の
`coordinator.py parallel` 実行で両方 COMPLETED、エージェントごとの属性付きです。
公開エージェントはオフラインになったり利用規約を変えたりすることがあります。
このテストは手動であり、自動テストスイートには含まれません。

## セキュリティに関する注意

- すべての送信 URL は、1 バイトでも送信する前に SSRF 検証を通ります: HTTPS 強制、
  DNS 解決、ループバック/プライベート/リンクローカル/クラウドメタデータ IP の
  ブロック（`ip.is_global`）、リダイレクト禁止、応答サイズ上限、オプションの
  ドメイン許可リスト。`ALLOW_LOCAL_AGENTS=true` が localhost への唯一の扉であり、
  開発/テスト専用です。
- （認証を要求するエージェント向けの）ベアラートークンは、セッション中の
  `A2A_BEARER_TOKEN` 環境変数か UI のパスワード欄にだけ存在します。
  永続化も、ログ出力（グローバルなログレコードの墨消し）も、argv 経由の受け渡しも
  しません。呼び出しごとに分離されています。
- リモート エージェントの出力は信頼しないデータとして扱います: 属性付きでそのまま
  表示し、実行せず、指示として扱いません。
- SQLite にはエージェントのメタデータとタスク履歴のみを保存します —
  認証情報は保存しません（token/secret/password カラムは存在しないことを
  テストで保証しています）。

## ドキュメント

- [docs/current_architecture.md](docs/current_architecture.md) — 基本の 2 エージェント デモ（英語）
- [docs/remote_agent_architecture.md](docs/remote_agent_architecture.md) — リモート エクスプローラーの設計とセキュリティ境界（英語）
- [docs/manual_test_plan.md](docs/manual_test_plan.md) — 手動テスト A–E（英語）
- [A2A_Explorer_Userguide.html](A2A_Explorer_Userguide.html) — 図解付きの完全ガイド（英語）。ダウンロードしてブラウザーで開けます

## AI 支援開発

このプロジェクトは、AI 支援コーディング・ワークフローで開発しました。アーキテクチャ、実装の判断、テスト、デバッグ、検証については開発過程でレビューと改善を行っています。