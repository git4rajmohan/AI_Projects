言語 / Languages: [English](README.md) | **日本語**

---

# Research Voice Agent — From a One-Line Prompt to a Finished Podcast

3 つのモードを持つ音声 AI パイプラインです。プロンプト、会議の文字起こし、または音声録音を与えると、少数精鋭の AI エージェントチームがリサーチし、レポートを書き、会話形式のスクリプトに変換し、MP3 として読み上げます — すべてのツール呼び出しがブラウザにライブでストリーミングされます。

> Google ADK · Ollama Cloud（`gpt-oss:120b`、組み込みの OpenAI→Ollama プロキシ経由） · FastAPI ·
> ddgs · yfinance · edge-tts · faster-whisper

## デモ動画

[![Research Voice Agent Demo](https://img.youtube.com/vi/5eGyakxnZzg/0.jpg)](https://youtu.be/5eGyakxnZzg)

## このプロジェクトが示すもの

- **Google ADK 上でのマルチエージェントオーケストレーション** — producer エージェント（リサーチ/ツール担当）が `AgentTool` を使って podcaster エージェントに委譲します。`AgentTool` は関数のように呼び出せるサブエージェントです
- **ツールに裏打ちされたリサーチ** — `ddgs` による Web 検索は**ADK コールバックで強制されるドメインホワイトリスト**（モデルは回避不可能）に制限され、すべてのクエリに鮮度ウィンドウが課され、`yfinance` によるリアルタイムの株価コンテキストも利用します
- **音声パイプライン** — edge-tts によるホストごとのニューラル音声（チャンク化ストリーム → 連結 MP3）と、独立したサブプロセスでの faster-whisper によるローカル文字起こし
- **UI の唯一の真実の源としてのコールバック** — 10 ステップの進行ステッパーは、エージェントが*実際にツールを呼び出した*ときだけ進みます。文字列マッチングには決して依存しません
- **1 つのモデルで複数の役割** — `gpt-oss:120b` がリサーチャー、ライター、脚本家、音声スペシャリストを務めます。専門性はファインチューニングではなく、指示・ツール・コールバックに宿ります

## なぜこのプロジェクトが存在するのか

テキストだけの LLM 出力ではなく、リサーチ、脚本生成、音声合成までを含む完全なマルチモーダル/音声 AI パイプラインを示すプロジェクトです。従来の方法でポッドキャストを作るには、リサーチ用のタブ、メモ文書、脚本の下書き、オーディオエディタ、マイクが必要です。このプロジェクトはその制作パイプライン全体を 1 つの Start ボタンに凝縮し、実行の様子をステップごとに可視化します。

## 3 つのモード

| モード | 入力 | 出力ファイル | ステップ数 |
|---|---|---|---|
| **AI News** | テキストプロンプト | `artifacts/news/ai_research_report.md` + `ai_today_podcast.mp3` | 10 |
| **Meeting Recap** | 貼り付けた文字起こし、または `.txt/.md/.vtt/.srt/.docx` ファイル | `artifacts/recap/meeting_recap.md` + `meeting_recap.mp3` | 9 |
| **Audio Summary** | 音声録音のアップロード（mp3/wav/m4a/…） | `artifacts/summaries/audio_summary.md` + 生の `transcript_*.txt` — **意図的にポッドキャストは生成しない** | 4 |

- **AI News** はホワイトリストされたニュースサイトを検索し、ライブの株価データで記事を補強し、監査可能な *Data Sourcing Notes* セクション付きの構造化レポートを書いた上で、エピソードを録音します
- **Meeting Recap** は Key Decisions、Discussion Summary、Action-Items テーブル、Open Questions を抽出します — 忠実性ルールとして、文字起こしにあることだけを扱い、欠けている詳細は「Not specified」となり、決して捏造しません
- **Audio Summary** はローカルで文字起こしを行い（最終サマリーのリクエスト以外は何もマシンの外に出ません）、タイムスタンプ付きのサマリーを書きます。進捗は文字起こしサブプロセスからライブでストリーミングされます（ハード上限 900 秒）

何も古びません。実行のたびに、そのモードの前回の成果物は `_old_<timestamp>` コピーとしてアーカイブされます。

## アーキテクチャ

```text
Browser (single-page UI, served by FastAPI)
   polls /api/status every 1.5 s · stepper · live log · report viewer · audio player
        ↓
podcast_ui.py — FastAPI + uvicorn on 127.0.0.1:8000
   REST endpoints · config.json persistence · artifact archiving (_old_*)
   lock-guarded STATE · one worker thread per run · 409 if busy
        ↓  imports engine as a module (same process)
lesson6_podcast_agent.py — ADK agent engine
   producer Agent (preset-built, 4 tools, guardrail callbacks)
   podcaster Agent reachable through AgentTool
   embedded OpenAI→Ollama proxy (FastAPI on 127.0.0.1:11435, daemon thread)
        ↓                              ↓                        ↓
   ddgs (whitelist + freshness)   yfinance (stock context)   edge-tts (MP3 per host)
                                   audio path only → faster-whisper in _transcribe_sub.py subprocess
```

**コード上の 2 つのエージェント** — producer は実行ごとにアクティブなトピックプリセット（目標、範囲、応答確認、金融ステップのバリエーション、ホストへの指示）から再構築されます。podcaster はツールを 1 つだけ持つスペシャリストです：

```python
root_agent = Agent(
    name="ai_news_researcher", model=LiteLlm(model=OLLAMA_MODEL),  # openai/gpt-oss:120b
    instruction=root_instruction(...),
    tools=[web_search, get_financial_context, save_news_to_markdown,
           AgentTool(agent=podcaster_agent)],            # sub-agent as a callable tool
    before_tool_callback=[filter_news_sources_callback, enforce_data_freshness_callback],
    after_tool_callback=[inject_process_log_after_search],
)
```

なぜ `output_schema` を使わないのか？ ADK は出力スキーマを設定すると**ツール使用が無効化される**ためです — ツール呼び出しの上に成り立つワークフローでは致命的です。Pydantic スキーマ（`AINewsReport`、`MeetingRecap`、`ActionItem`、`NewsStory`）は、指示の中で構造の指針として保持しています。

## ワークフロー（ニュース実行、10 ステップ）

1. **Acknowledge** — producer が目標を確認します（ユーザーに見えるメッセージはわずか 2 種類のうちの 1 つ）
2. **Search news** — `web_search` の結果はコールバックによってホワイトリスト + 鮮度ウィンドウにフィルタされます
3–4. **Extract tickers & fetch financials** — `get_financial_context` が yfinance 経由でデータを取得。データが欠けても「Not Available」となり、実行が停止することはありません
5–7. **Structure & save the report** — `save_news_to_markdown` が `ai_research_report.md` を書き出します。Report パネルはファイルが着地した瞬間に更新されます
8. **Write the script** — 設定されたホスト名・人数・ペルソナに一致する `Joe: … / Jane: …` の行を書きます
9. **Generate audio** — producer が脚本を podcaster エージェントへ引き渡します（AgentTool による委譲）。`generate_podcast_audio` がすべての `Speaker:` 行を正規表現で解析し、各ホストの edge-tts 音声で合成して、MP3 チャンクを 1 つのエピソードに連結します
10. **Confirm done**

ステッパーのピルは ADK のツールコールバックによって駆動されます — 灰 = 待機、琥珀 = 実行中、緑 = 完了、赤 = 失敗。ライブログには、すべてのツール呼び出し、フィルタされたすべてのドメイン、文字起こしの進捗率が表示されます。

**なぜオートコンティニューループが存在するのか:** Ollama のチャットモデルはテキストのみのメッセージでターンを終え、同じ応答内でツール呼び出しを出力しないためです。ワーカーは目標の成果物が存在するようになるまで "continue" でエージェントを促し、`max_auto_continue`（既定 10）で上限を設けています。これにより、固まった実行はハングする代わりにクリーンに失敗します。

## ガードレール（ADK コールバック — 強制であり、信頼ではない）

| コールバック | 強制内容 |
|---|---|
| `filter_news_sources_callback`（すべてのツールの前） | クエリをホワイトリストに書き換え、ホワイトリスト外ドメインの結果はモデルが見る前に破棄 |
| `enforce_data_freshness_callback`（すべてのツールの前） | すべての検索に鮮度ウィンドウ（既定は `week`）を強制 |
| `inject_process_log_after_search`（`web_search` の後） | フィルタリングログをツール結果に添付 — すべてのレポートに、ユーザーが監査できる *Data Sourcing Notes* セクションが付きます |
| `ui_step_tracker_before/_after`（podcast_ui.py） | ツール名をワークフローステップに対応付け、UI が進捗について嘘をつけないようにします |

ティッカーが欠けたら「Not Available」に、recap のフィールドが欠けたら「Not specified」に劣化します — 実行は途中で死ぬのではなく、必ず成果物を届けます。

## 技術スタック

| レイヤー | 技術 | 役割 |
|---|---|---|
| フロントエンド | Vanilla HTML/CSS/JS（サーバーファイルに埋め込み） | ステッパー、ライブログ、レポートビューアー、オーディオプレイヤー、設定パネル |
| API サーバー | 127.0.0.1:8000 上の FastAPI + uvicorn（`podcast_ui.py`） | REST エンドポイント、実行オーケストレーション、設定の永続化 |
| エージェントフレームワーク | Google ADK（`google-adk==1.22.1`、ピン留め） | Runner、セッション、関数ツール、`AgentTool` 委譲、コールバック |
| LLM | Ollama Cloud — LiteLLM 経由の `gpt-oss:120b` | 推論、リサーチ、レポート、脚本、サマリー |
| フォーマットブリッジ | 組み込みの OpenAI→Ollama プロキシ（127.0.0.1:11435 上の FastAPI） | OpenAI 方式のチャット/ツール呼び出しを Ollama のネイティブ API に翻訳 |
| Web 検索 | ddgs (DuckDuckGo) | 新しいニュース。ホワイトリスト + 鮮度はコールバックで強制 |
| 金融データ | yfinance | 言及されたティッカーの株価コンテキスト（非マーケット系プリセットではスキップ） |
| TTS | edge-tts（Microsoft ニューラル音声） | ホストごとの音声、連結された MP3 チャンク |
| STT | 独立サブプロセス内の faster-whisper（`_transcribe_sub.py`） | ローカル文字起こし、JSON 進捗行、900 秒のハード上限 |
| 設定 | `config.json` + python-dotenv | UI 設定の永続化。API キーは `.env` から |

## カスタマイズ

- **12 言語** — English、Japanese、Chinese、Tamil、Hindi、Spanish、French、German、Korean、Portuguese、Arabic、Russian。設定に従って実行全体（レポート、脚本、音声）が変わり、ホストはネイティブ音声に再マッピングされます
- **1〜4 人のホスト** — 名前、edge-tts 音声、ペルソナを個別に設定。実行せずに *Preview host* で即時確認できます
- **5 つのトピックプリセット** — AI + 市場ニュース（既定）、テック業界、リサーチ/学術、Entertainment · India、Custom。それぞれがプロンプトの事前入力、ドメインホワイトリスト、検索リージョン、エージェントの表示名/ステップラベルを切り替えます（非マーケット系プリセットでは金融ステップを自動スキップ）

## 実行方法

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then paste your key from https://ollama.com/settings/keys

.venv\Scripts\python.exe podcast_ui.py
# → http://127.0.0.1:8000  (the embedded proxy on :11435 starts automatically)
```

タブを選び、入力を与え、**▶ Start** を押します。News ならプロンプトを入力。Recap なら文字起こしを貼り付けるかファイルを読み込み。Audio summary なら Meeting Recap タブで録音をアップロードします。初回の文字起こしは一度だけ遅くなります（whisper モデルは一度だけダウンロードされ、起動時に事前ウォームアップされます）。

**完全ガイド：** [`userguide.html`](./userguide.html) — 4 タブ構成のウォークスルー（ピッチ、非技術者向け、技術者向け、用語集）に、ニュース実行全体のメッセージシーケンストレースも収録しています。

## API サーフェス（podcast_ui.py）

`GET /`（シングルページ UI） · `GET/POST /api/config` · `POST /api/run`（実行中は `409`） ·
`POST /api/stop` · `GET /api/status` · `GET /api/steps_config` · `GET /api/presets` ·
`GET /api/languages` · `GET /api/report?mode=` · `GET /api/audio?mode=&download=` ·
`POST /api/upload?filename=` · `GET /api/voice_preview`

## 主要な AI エンジニアリングの概念

- 会話型のハンドオフではなく、ツールとしてのサブエージェント（`AgentTool`）— 音声生成は 1 つのワークフローにおけるもう 1 つのステップにすぎません
- コールバックで強制されるガードレール（ドメインホワイトリスト、鮮度）— モデルは回避できません
- 組み込みの OpenAI→Ollama フォーマット翻訳プロキシ（ツール呼び出しの形状、配列コンテンツ、モデルプレフィックス）
- async 内の async の封じ込め：edge-tts の合成は専用スレッド上で独立したイベントループで実行され、whisper はサブプロセスで実行 — ADK の実行中ループには触れません
- シングルフライトロック付きの実行ごとスレッド。古い「running」状態は自己修復します

## 安全性 / 信頼性

- 検索は**before-tool コールバック**によってホワイトリストドメインに閉じ込められており、信頼によってではなく強制されています
- すべての株価照会はモデルの記憶ではなく、yfinance ツールを経由します
- recap モードの忠実性ルール：捏造された引用や決定は書かず、欠けている詳細は「Not specified」とします
- 音声はマシンの外に出ません — 文字起こしはローカルで実行され、クラウド LLM に渡るのはテキストのリクエストだけです
- 実行は 1 度に 1 つだけ（実行中は `409`）。文字起こしサブプロセスには 900 秒のハード上限があります

## テスト / 評価

*現在のリポジトリでは未記録* — このプロジェクトは自動テストスイートを同梱していません。userguide の検証手順（ステッパーがツールの発火時のみ進むこと、成果物が `artifacts/<mode>/` 以下に着地することの確認）が手動チェックに相当します。

## このプロジェクトが他と違う点

**エージェントが計画し、ツールが実行する**音声/マルチモーダルパイプラインです。リサーチはコールバックで囲まれ、音声は本物（ホストごとのニューラル音声）で、実行全体がブラウザにストリーミングされます。テキストを返すだけのチャットボットとは異なり、ここでの成果物は完成したレポート*と*再生可能な MP3 — 1 つのオープンウェイトモデル上で協調する 2 つの ADK エージェントが生み出します。

## AI 支援による開発

このプロジェクトは AI 支援のコーディングワークフローを用いて開発されました。アーキテクチャ、実装判断、テスト、デバッグ、検証は開発中に見直しと改善が行われました。
