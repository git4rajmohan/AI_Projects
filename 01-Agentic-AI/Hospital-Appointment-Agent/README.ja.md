言語 / Languages: [English](README.md) | **日本語**

---

# 🏥 病院予約スケジューラ & 確認ボット

> [AI_Projects](../README.md) ショーケース — AI/ML プロジェクトの厳選コレクションの一部です。

**LangChain (LCEL)**、**FastAPI**、**Pydantic** で構築された軽量かつ決定論的なバックエンド サービス。患者/クライアントからの予約リクエストを処理し、会話形式の予約と管理者向け管理のためのフル **エンタープライズ グレードの Web コンソール** を備えています。

## なぜこのプロジェクトが存在するのか

LLM が自由形式の自然言語から構造化された意図を抽出し、実際の予約判断 — カレンダー ルール、スロット選択、確認処理 — は決定論的な Python コードが担う仕組みを実証します。AI がビジネス上の判断を下すことはありません。

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/%F0%9F%A6%9C%EF%B8%8F%E2%83%A3LangChain-LCEL-green)](https://python.langchain.com/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud-white?logo=ollama)](https://ollama.com/)
[![Twilio](https://img.shields.io/badge/SMS-Twilio-red?logo=twilio&logoColor=white)](https://www.twilio.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## スクリーンショット

| チャット コンソール | カレンダー — 週表示 |
|:---:|:---:|
| ![Chat Console](docs/screenshots/01-chat.png) | ![Calendar View](docs/screenshots/02-calendar.png) |
| **予約履歴** | **SMS 送信履歴** |
| ![Booking History](docs/screenshots/03-bookings.png) | ![SMS History](docs/screenshots/04-sms-history.png) |

## 機能

### 会話型チャットボット
- 💬 自然言語での予約: *"来週の月曜 14 時に John Doe の循環器内科予約を入れたい"*
- 🤖 LLM による意図抽出 — LangChain LCEL + Pydantic で構造化された予約フィールドを取得
- 📋 患者名、診療科、予約時刻、マスク済み電話番号、SMS SID を含む予約確認カード
- ⚡ クイックアクション チップ(予約 / 再スケジュール / キャンセル / 問い合わせ)とセッション対応のマルチターン チャット

### 管理コンソール
- 📆 **カレンダー — 週表示**: 7 日 × 8 スロットの空き状況グリッドと色分けステータス レール
- 👥 **予約履歴**: 電話番号をマスクした検索可能なテーブル(クリックで表示)、SMS SID 付き
- 📱 **SMS 履歴**: モード バッジ(twilio / mock / seed / error)付きの送信メッセージ完全監査ログ
- 🟢 アプリ バーにライブ ヘルス ステータス表示(モデルと SMS モードが一目でわかる)

### エンタープライズ UI
- 折りたたみ可能なナビとトップ アプリ バーを備えたライトテーマのサイドバー シェル
- インライン SVG アイコン システム(絵文字ゼロ、アイコン ライブラリ依存ゼロ)
- キーボード操作可能なフォーカス リング、モーション軽減対応、細身のスクロールバー
- レスポンシブ: モバイルではオフキャンバス サイドバー、1024px / 900px / 640px でレイアウト調整

## 何をするか

1. 生の自然言語入力(テキスト/メール/SMS)を**解析**する
2. LLM により構造化された予約変数(意図、日時、診療科、連絡先情報)を**抽出**する
3. モック Calendar API で空き状況を**確認**する
4. Twilio(またはモックの同等機能)で SMS 確認を**送信**する
5. 構造化された JSON 実行サマリーを**返す**

## 技術スタック

| コンポーネント | 技術 |
|-----------|-----------|
| LLM オーケストレーション | LangChain (LCEL) — `langchain`、`langchain-core`、`langchain-openai` |
| LLM プロバイダー | ローカルの OpenAI 形式プロキシ経由で Ollama Cloud(`gpt-oss:120b`) |
| API フレームワーク | FastAPI + Uvicorn |
| データ バリデーション | Pydantic v2 |
| テスト | pytest + pytest-asyncio |
| SMS | Twilio(デフォルトはモック) |

## プロジェクト構成

```text
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point + web UI serving
│   ├── schemas.py           # Pydantic schemas (input/output/extraction)
│   ├── chain.py             # LangChain LCEL pipeline + orchestrator
│   ├── services.py          # Mock Calendar & SMS services
│   ├── config.py            # Environment configuration (pydantic-settings)
│   └── static/
│       └── index.html       # Enterprise web console (single-file, no build step)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures
│   ├── test_chain.py        # Extraction & orchestrator tests
│   └── test_api.py          # FastAPI endpoint tests
├── docs/
│   └── screenshots/         # UI screenshots for README
├── data/
│   └── appointments.db      # SQLite store (bookings, SMS records)
├── ollama_cloud_proxy.py    # OpenAI→Ollama format translator
├── .env                     # API keys (gitignored)
├── .env.example             # Template for .env
├── .gitignore
├── requirements.txt
├── pytest.ini
├── Instruction.md           # Original spec
└── README.md
```

## Web コンソール

UI は `http://127.0.0.1:8000/` で提供されます — 単一ファイルの `app/static/index.html`(Node 不要、ビルド ステップなし)。

| エンドポイント | 用途 |
|----------|---------|
| `GET /` | エンタープライズ Web コンソール(チャット + 管理ビュー) |
| `GET /api/health` | サービス ヘルス(ステータス、モデル、SMS モード) |
| `POST /api/chat` | 会話形式の予約(セッション対応) |
| `POST /api/chat/reset` | チャット セッションのリセット |
| `GET /api/calendar/week` | 7 日間の空き状況グリッド |
| `GET /api/calendar/bookings` | 全予約の一覧 |
| `GET /api/sms/history` | SMS 監査ログ |
| `POST /api/appointment` | 直接スケジューリング API(JSON 入出力) |

## セットアップ

### 1. 仮想環境の作成と依存関係のインストール

```powershell
cd 01-Agentic-AI\Hospital-Appointment-Agent   # from the repository root
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` を `.env` にコピーし、Ollama Cloud の API キーを設定します:

```powershell
Copy-Item .env.example .env
```

`.env` を編集:
```
OLLAMA_API_KEY=your_real_key_from_ollama_com
```

キーは https://ollama.com/settings/keys から取得できます。

### 3. Ollama Cloud プロキシの起動

**アプリを起動する前、および統合テストを実行する前に、これが起動している必要があります。**

```powershell
.\.venv\Scripts\python.exe ollama_cloud_proxy.py
```

プロキシは `http://127.0.0.1:11435/v1` でリッスンし、OpenAI 形式のリクエストを Ollama Cloud のネイティブ形式に変換します。

### 4. API サーバーの起動

新しいターミナルで:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API ドキュメント: http://127.0.0.1:8000/docs

### 5. テストの実行

```powershell
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
```

> ユニット テストは LLM チェーンをモックします — プロキシや Ollama Cloud は不要です。

## API の使い方

### POST /api/appointment

```bash
curl -X POST http://127.0.0.1:8000/api/appointment \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "I need to book a cardiology appointment for John Doe on 2026-09-07 at 14:00. My phone is +15551234567.",
    "channel": "web"
  }'
```

**レスポンス:**
```json
{
  "status": "confirmed",
  "extracted": {
    "intent": "schedule",
    "patient_name": "John Doe",
    "department": "cardiology",
    "preferred_datetime": "2026-09-07T14:00:00",
    "contact_phone": "+15551234567",
    "contact_email": null,
    "notes": null
  },
  "scheduled_datetime": "2026-09-07T14:00:00",
  "confirmation_message_sid": "MOCK_SID_abc123",
  "message": "Appointment confirmed for 2026-09-07 at 14:00. SMS sent (SID: MOCK_SID_abc123)."
}
```

### GET /api/health

```bash
curl http://127.0.0.1:8000/api/health
```

## 動作の仕組み

```
Raw Text ➊ [ChatPromptTemplate | ChatOpenAI | PydanticOutputParser] ➋ ExtractedAppointment
                                                                         │
                                                                         ▼
                                                              ┌─── Calendar Check ────┐
                                                              │                       │
                                                         Available?            Not Available?
                                                              │                       │
                                                         Book Slot          Find Next Available
                                                              │                       │
                                                              └────── SMS ────────────┘
                                                                         │
                                                                         ▼
                                                                  ExecutionSummary
```

## 設定

| 環境変数 | 説明 | デフォルト |
|---------|-------------|---------|
| `OLLAMA_API_KEY` | Ollama Cloud API キー | (必須) |
| `OPENAI_API_KEY` | langchain-openai 用のダミーキー | `ollama-cloud-proxy` |
| `OPENAI_API_BASE` | プロキシ エンドポイント | `http://127.0.0.1:11435/v1` |
| `OLLAMA_MODEL` | `openai/` プレフィックス付きの Ollama モデル | `openai/gpt-oss:120b` |
| `TWILIO_ACCOUNT_SID` | Twilio SID(`mock` = モックモード) | `mock` |
| `TWILIO_AUTH_TOKEN` | Twilio トークン | `mock` |
| `TWILIO_FROM_NUMBER` | Twilio 送信元番号 | `+10000000000` |
| `APP_HOST` | API ホスト | `127.0.0.1` |
| `APP_PORT` | API ポート | `8000` |

## 利用可能な Ollama Cloud モデル

- `gpt-oss:120b`(デフォルト)
- `gpt-oss:20b`
- `glm-5.2`
- `kimi-k2.6`
- `deepseek-v4-flash`

モデルを変更するには、`.env` の `OLLAMA_MODEL` を編集します。

## 備考

- **LangGraph 不使用 / ベクトル検索リトリーバー不使用** — 仕様どおり、厳密に線形の LCEL パイプラインです。
- **モック サービス** — Calendar と SMS はデフォルトでモックです。実際の SMS を有効にするには `.env` に実 Twilio 認証情報を設定してください。
- **プロキシ必須** — アプリが LLM 呼び出しを行う前に、Ollama Cloud プロキシが起動している必要があります。