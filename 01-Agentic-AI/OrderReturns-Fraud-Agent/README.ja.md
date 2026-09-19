言語 / Languages: [English](README.md) | **日本語**

---

# 🔁 自動返品 & 不正防止エージェント

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/🦜%20LangGraph-StateGraph-1C3C3C)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_APIs-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud-white?logo=ollama)
![SQLite](https://img.shields.io/badge/Persistence-SQLite-003B57?logo=sqlite&logoColor=white)

E コマースの返品/返金ワークフロー向け LangGraph + FastAPI サービス。循環する写真証憑ループ、決定論的な不正ヒューリスティクス、Ollama Cloud LLM による返品理由分類器、そして高額返金のための SQLite チェックポイント化された**ヒューマンインザループ(HITL)**マネージャー承認ゲート(`interrupt()` ベース、`INSTRUCTIONS.md` 準拠)を備えています。


## デモ動画

[![Order Returns & Fraud Agent Demo](https://img.youtube.com/vi/X6S-7u6hg2s/0.jpg)](https://youtu.be/X6S-7u6hg2s)

## なぜこのプロジェクトが存在するのか

AI がリクエストを解釈する一方で、ポリシーと返金の判断は決定論的なコードが下すステートフルな業務プロセス エージェントを実証します — 高リスク案件にはヒューマン承認ゲートとチェックポイント化を併用します。

**ハイライト**

- 🧠 単一の `StateGraph` が駆動する 4 経路の返品ワークフロー(自動完了、写真証憑ループ、マネージャー承認、ポリシー拒否)
- 🤖 決定論的なキーワード フォールバック付き LLM 返品理由分類器(Ollama Cloud `gpt-oss:120b`)— モデルに到達できなくても決して壊れない
- 🚦 ネイティブ `interrupt()` のマネージャー承認ステップへのゲートとなる決定論的な不正スコアリング(返品速度、リトライ後も写真なし、高額返金)
- 🗄️ SQLite チェックポイント化 — 中断中のランを含め、すべてのランがサーバー再起動をまたいで永続化・再開可能
- 🖥️ **Customer**、**Manager**、**Pipeline**(ワークフロー段階ダッシュボード)ビューを持つ Streamlit コンソール
- 🧪 149 個の pytest テスト(ユニット + FastAPI 統合。ライブ LLM テストはマーカーの背後)

> 📄 **詳細な設計ドキュメント:** [`docs/plan.md`](./docs/plan.md)(フェーズ別ビルド計画)·
> [`docs/uiplan.md`](./docs/uiplan.md)(UI 設計)·
> [`docs/howtotest.md`](./docs/howtotest.md)(完全なテスト ウォークスルー)

| Customer — 返品を追跡 | ワークフロー パイプライン ダッシュボード |
|:---:|:---:|
| ![Customer view](./docs/screenshots/01-customer.png) | ![Pipeline view](./docs/screenshots/02-pipeline.png) |
| **マネージャー コンソール — 承認 & 不正内訳** | **API リファレンス(FastAPI / Swagger)** |
| ![Manager view](./docs/screenshots/03-manager.png) | ![API docs](./docs/screenshots/04-api-docs.png) |

## アーキテクチャ

```
POST /returns ──► validate_policy ──► classify_condition (LLM) ──► check_photo_proof
                                                                        │  (loop on resume)
                                                                        ▼
                                          calculate_fee ◄───────────────┘
                                                │
                                                ▼
                                          fraud_check ──► (high value / fraud?) ──► human_gate
                                                                                            │ resume
                                                     completed ◄── finalize_refund ◄────────┤
                                                     rejected  ◄── reject_by_manager ◄──────┘
```

- **ステート マシン:** `app/graph.py` — 条件分岐エッジ、上限付き写真証憑ループ、2 つのネイティブ `interrupt()` ゲート(`check_photo_proof`、`human_gate`)を備えた `StateGraph(ReturnState)`。
- **永続化:** `langgraph-checkpoint-sqlite` の `SqliteSaver` が `checkpoints.sqlite` に書き込み — 中断中のランを含め、すべてのランがサーバー再起動をまたいで永続化・再開可能。
- **LLM 分類器:** `app/llm.py` — Ollama Cloud(`gpt-oss:120b`)を指す `langchain-ollama.ChatOllama` が自由記述の理由を `damaged_defective` / `buyer_remorse` に分類。LLM が何らかの障害を起こしても、静かに決定論的なキーワード分類器へフォールバックするため、モデルが原因でサービスが壊れることはありません。
- **ビジネス ルール:** `app/services.py` — モック注文 DB、30 日ウィンドウ チェック、送料(破損 = $0.00、購入後の気変わり = $5.99)、不正スコア ヒューリスティクス、モック決済ゲートウェイ。

## ビジネス ルール

| ルール | 動作 |
| --- | --- |
| 返品ウィンドウ | 注文が 30 日より古い → `denied_policy` |
| 送料 | 破損/不良 = **$0.00**。購入後の気変わり = **$5.99** |
| 返金額 | `item_value - shipping_fee` |
| 不正スコア | `+0.4` 顧客の返品速度(30 日以内に 3 件以上)· `+0.4` リトライ回数を使い切った後も写真のない破損申告 · `+0.3` 返金額 > $500 |
| ヒューマン ゲート | 返金額 **> $200.00** または不正スコア **≥ 0.7** → マネージャー承認 |
| 写真ループ | 写真なしの破損/不良申告 → 一時停止 + 写真をリクエスト。`MAX_PHOTO_RETRIES`(3)で上限管理。使い切った場合はランを続行し、不正チェックがフラグ付け(`no_photo_proof`) |

## セットアップ

**Python 3.11+** が必要です。

```powershell
# from this project's root folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -r requirements.txt

# configure
copy .env.example .env   # then edit values
```

`.env` キー(`.env.example` を参照):

| キー | 用途 | デフォルト |
| --- | --- | --- |
| `OLLAMA_API_KEY` | Ollama Cloud キー(ollama.com/settings/keys から取得) | *(空 → キーワード フォールバック分類器)* |
| `OLLAMA_MODEL` | チャット モデル | `gpt-oss:120b` |
| `OLLAMA_BASE_URL` | Ollama エンドポイント | `https://ollama.com` |
| `SQLITE_DB_PATH` | チェックポイント DB ファイル | `./checkpoints.sqlite` |
| `HIGH_VALUE_THRESHOLD` | マネージャー承認が必要になる返金額 | `200.00` |
| `FRAUD_SCORE_THRESHOLD` | マネージャー承認が必要になる不正スコア | `0.7` |
| `MAX_PHOTO_RETRIES` | 写真証憑ループの上限 | `3` |

> サービスは `OLLAMA_API_KEY` が空のままでも動作します — 分類は単純に LLM の代わりにキーワード フォールバックを使います。

## 実行

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

インタラクティブ API ドキュメント: <http://127.0.0.1:8000/docs>。

> **ポートに関する注意(Windows):** ポート 8000 は `/api/*` ルートで応答する無関係なローカル サービスが占有していることがよくあります。別のポートでスモークテストしてください。例:
> `.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765`

## UI の実行(Streamlit)

Streamlit コンソールがバックエンドをエンドツーエンドで駆動します — **Customer** ビュー(返品の開始/追跡、写真再提出)と **Manager** ビュー(承認待ちキュー + 全返品テーブル)。認証なし、手動更新ボタンあり。

```powershell
# terminal 1 — backend (use 8765 to dodge the Windows port-8000 conflict)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765

# terminal 2 — UI
.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

UI のデフォルトは `http://127.0.0.1:8765` です。バックエンドが別の場所で動いている場合はサイドバーで変更してください。

### UI ウォークスルー(デモ フロー)

1. **購入後の気変わり(自動完了):** Customer → *Start a new return* → `ORD-1002`(Wireless Headphones、$129.50)を選択 → 理由 "Changed my mind" → **Submit** → ステータスが即座に `completed`(返金 $123.51、手数料 $5.99)。
2. **写真ループ:** 同じく `ORD-1002` を理由 "Headphones arrived broken" で選択、写真なし → ステータス `awaiting_photo` → Track セクション → *I have a photo* にチェック、URL を入力 → **Submit photo** → `completed`(手数料 $0.00)。
3. **マネージャー承認:** `ORD-1001`(Ultrabook、$899)を任意の理由で選択 → `awaiting_approval` → サイドバーを **Manager** に切替 → 返品が *Pending approvals* に表示(返金 $893.01、不正スコア 0.7)→ ノートを追加 → **Approve** → `completed`(または **Reject** → `rejected`)。
4. **ポリシー拒否:** `ORD-1003`(Mechanical Keyboard、45 日経過)を選択 → 即座に `denied_policy` を表示。

## フロー例(curl)

### 1. ハッピー パス — 購入後の気変わり、低額(自動完了)

```powershell
curl -X POST http://127.0.0.1:8000/returns -H "Content-Type: application/json" -d '{
  "order_id": "ORD-1002", "item_id": "SKU-HEADPHN-02",
  "reason_text": "I changed my mind, the headphones are too heavy"
}'
# → {"thread_id":"<uuid>","status":"completed","message":"Return completed — refund processed successfully.",
#    "next_action":"none","refund_amount":123.51,"shipping_fee":5.99,"fraud_score":0.0,"fraud_flags":[]}
```

### 2. 写真証憑ループ — 破損品、写真なし

```powershell
curl -X POST http://127.0.0.1:8000/returns -H "Content-Type: application/json" -d '{
  "order_id": "ORD-1002", "item_id": "SKU-HEADPHN-02",
  "reason_text": "left earcup is broken"
}'
# → {"status":"awaiting_photo","next_action":"submit_photo", ...}

curl -X POST http://127.0.0.1:8000/returns/<thread_id>/photo -H "Content-Type: application/json" -d '{
  "photo_provided": true, "photo_url": "https://example.com/proof.jpg"
}'
# → {"status":"completed","refund_amount":129.50,"shipping_fee":0.00, ...}
```

`{"photo_provided": false}` を送信するとループが再一時停止します(最大 `MAX_PHOTO_RETRIES`)。使い切った場合はランが続行し、不正チェックが `no_photo_proof` フラグ(+0.4)を追加します。これによりランはマネージャー ゲートへルーティングされます。

### 3. マネージャー承認ループ — 高額 / 不正

```powershell
curl -X POST http://127.0.0.1:8000/returns -H "Content-Type: application/json" -d '{
  "order_id": "ORD-1001", "item_id": "SKU-LAPTOP-01",
  "reason_text": "screen arrived cracked"
}'
# refund 899.00 > 200 → {"status":"awaiting_approval","next_action":"await_manager",
#                        "refund_amount":893.01,"fraud_score":...,"fraud_flags":[...]}

curl -X POST http://127.0.0.1:8000/returns/<thread_id>/approve -H "Content-Type: application/json" -d '{
  "manager_note": "Verified damage photo, approved."
}'
# → {"status":"completed","manager_note":"Verified damage photo, approved.", ...}

# or reject instead:
curl -X POST http://127.0.0.1:8000/returns/<thread_id>/reject -H "Content-Type: application/json" -d '{}'
# → {"status":"rejected", ...}
```

### 4. ポリシー拒否 — 30 日ウィンドウ外の注文

```powershell
curl -X POST http://127.0.0.1:8000/returns -H "Content-Type: application/json" -d '{
  "order_id": "ORD-1003", "item_id": "SKU-KEYBOARD-03", "reason_text": "stopped working"
}'
# → {"status":"denied_policy","message":"Return denied by policy: ...","next_action":"none"}
```

### 5. ランの調査

```powershell
curl http://127.0.0.1:8000/returns/<thread_id>
# 404 when the thread_id is unknown.
```

## エラー セマンティクス

| コード | 意味 |
| --- | --- |
| `404` | 未知の `thread_id`(チェックポイント未作成) |
| `409` | 一時停止していないスレッドの再開、または*誤った*ゲートでの一時停止(例: マネージャー ゲートのスレッドに `/photo`) |
| `422` | リクエスト ボディがバリデーションに失敗 |

## テスト

```powershell
.venv\Scripts\python.exe -m pytest -v              # full suite (142+ tests; live-LLM tests deselected)
.venv\Scripts\python.exe -m pytest -m integration  # 2 live Ollama Cloud tests (requires OLLAMA_API_KEY in .env)
```

テスト ファイルは `plan.md` のフェーズを反映しています: `test_schemas.py`、
`test_services.py`、`test_graph.py`(状態遷移、割り込み、ループ、
インスタンスをまたぐ SQLite 永続化)、`test_llm.py`(パーサー/フォールバックのユニット +
ライブ統合)、`test_api.py`(FastAPI 統合。再起動等価性を含む)。

## エンドポイント サマリー

| メソッド | パス | 用途 |
| --- | --- | --- |
| `POST` | `/returns` | 返品ワークフローを開始(新しい `thread_id` を返す) |
| `GET` | `/returns` | 全返品の一覧。`?status=` で絞り込み可能 |
| `POST` | `/returns/{thread_id}/photo` | 写真証憑の割り込みを再開 |
| `POST` | `/returns/{thread_id}/approve` | マネージャー ゲートで承認 |
| `POST` | `/returns/{thread_id}/reject` | マネージャー ゲートで却下 |
| `GET` | `/returns/{thread_id}` | 現在のチェックポイント済み状態を調査 |
| `GET` | `/orders` | モック注文の一覧(UI の注文ピッカーの生成に使用) |

## モック データ(フローを試すため)

| 注文 | 金額 | 注文日 | 備考 |
| --- | --- | --- | --- |
| `ORD-1001` | $899.00 | 5 日前 | 新規 + 高額 → 承認ゲートをトリガー。顧客 `CUST-A` は返品速度も該当 |
| `ORD-1002` | $129.50 | 10 日前 | 新規 + 低額 → 自動完了 |
| `ORD-1003` | $79.99 | 45 日前 | ウィンドウ外 → `denied_policy` |
| `ORD-1004` | $349.00 | 25 日前 | 新規 + 高額 |
| `ORD-1005` | $45.00 | 60 日前 | ウィンドウ外、低額 |
| `ORD-1006` | $15.00 | 2 日前 | 非常に新規、低額 |

顧客: `CUST-A` は直近 30 日で 3 件の返品(速度による不正フラグ)、`CUST-B`/`CUST-C`/`CUST-D` はトリガーしません。