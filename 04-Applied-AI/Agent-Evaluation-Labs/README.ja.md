言語 / Languages: [English](README.md) | **日本語**

# Agent Evaluation Labs — Arize Phoenix による LLM エージェントのオブザーバビリティ & 評価

**トレースされたエージェント実行から、採点された証拠、A/B プロンプト比較へ。**

[ポートフォリオ](../../README.ja.md) | [ユーザーガイド（英語）](Userguide.html)

Agent Evaluation Labs は、販売データ分析エージェント（ルーター + 3 ツール）を構築します。
すべての LLM 呼び出し・ツール呼び出し・SQL 実行が Arize Phoenix にトレースされ、
その記録された証拠を 4 つの評価ラボが採点します。操作は 1 つの Streamlit ダッシュボードから。
評価者はオブザーバーです。エージェントの実行方法を変えることはありません。
まずトレースし、記録されたスパンを採点し、変更前後を比較して、最も弱いコンポーネントを修正します。

## デモ動画

[![AIEvals Completedemovideo](https://img.youtube.com/vi/epIHy3CGpUY/0.jpg)](https://youtu.be/epIHy3CGpUY)

## このプロジェクトの目的

生の LLM エージェントはデモでは賢く見えますが、実際の利用では静かに失敗します。
正しいツールを選んだか？ 生成した SQL は質問に関連しているか？ 答えは明確か、
それとももっともらしいだけか？ プロンプトの変更が、以前動いていたものを静かに
劣化させていないか？ 計装がなければ推測しているだけです。計装があれば、
**評価駆動開発**ができます。このプロジェクトはその実践の計装部分であり、
RAG システムを評価するポートフォリオの RAG Evaluation Harness の
エージェント版コンパニオンです。

**ポイント:** 開発中にエージェントの経路を見せるのと同じ計装が、
後のリグレッションテストも支えます。

## 実証する機能

- **トレースファーストのアーキテクチャ** — エージェント実行は
  Phoenix（プロジェクト `evaluating-agent`）に `AgentRun` ルートスパンとして記録されます:
  `AgentRun → router_call → ツールスパン → ネストされた LLM スパン`。
  OpenInference による自動計装。ラボはその後にスパンへ問い合わせます。
- **完全なメッセージ軌跡が評価対象** — `run_agent()` はすべてのメッセージを
  `messages` にその場で追加し、`process_messages()` が
  `{tool_calls, tool_responses, final_output, path_length}` に
  `tool_call_id` で突き合わせて要約します。軌跡はその場で収集され、後から再構成されません。
- **1 つのダッシュボードに 4 つのラボ** — Lab 5（トレースデモ: 2 質問 + スパンツリー）、
  Lab 7（ルーター & スキル評価: 実際に記録されたツール呼び出し・SQL・回答への LLM ジャッジ +
  生成チャートコードを `exec()` するコード評価）、
  Lab 9（収束評価: 同一質問の 17 パラフレーズを経路効率で採点する Phoenix experiment）、
  Lab 11（総合評価: 7 質問に 5 評価者、その後 A/B 再実行）。
  「Run all」モードは非対話ラボを連続実行します。
- **トレース汚染のない LLM-as-judge** — `run_judge()` は生の HTTP + JSON モード
  （`response_format: json_object`）を使い、`suppress_tracing()` で包まれるため、
  ジャッジ呼び出しが評価対象のトレースにスパンとして現れることはありません
  （Phoenix 20.x で `phoenix.evals` API は削除されました。生 HTTP により
  ジャッジが計装から外れることも保証します）。
  ジャッジのラベル・スコア・完全な理由は span annotation として Phoenix に記録されます。
- **サブプロセスプロトコルで UI をジェネリックに** — `app.py` は
  `python eval.py <lab>` を起動して stdout をストリーミングし、
  2 つの規約（`Q:/A:` 回答マーカーと `__EVAL_UI__ {json}` スコア行）だけを解析します。
  この 2 形式を守る限り `eval.py` は自由に変更できます。
- **画面に表示される正直な失敗セマンティクス** — 「Run completed」は実行が完了した
  ことだけを意味し、すべてのチェックが合格したことを意味しません。
  ジャッジエラーは呼び出し側指定のデフォルトにフォールバックします。
  Lab 11 は SQL/チャートツール応答がない場合にそのチェックを合格扱いします
  （文書化されたスコープ制限であり、成功ではありません）。
  収束は効率のみを測定します。
- **記録された証拠** — `record_test.py` が各ラボをヘッドレス Chromium で
  エンドツーエンドに駆動し（Playwright・動画キャプチャ）、ラボごとに
  期待される UI 成果物を検証します。判定結果・動画・スクリーンショットは
  [test_videos/](test_videos/) に、視覚的レポートは
  [report](test_videos/report.html) に同梱されています。

## アーキテクチャ

```text
Streamlit app.py（ランチャー + レンダラー）
  -> サブプロセス: python eval.py <lab>
       -> utils.py: run_agent()
            ルーター LLM -> ツール呼び出し? -> lookup_sales_data (SQL -> parquet 上の DuckDB)
                                            -> analyze_sales_data (LLM が解釈)
                                            -> generate_visualization
                                               (JSON モードのチャート設定
                                                -> LLM が Python チャートコードを生成)
            すべての呼び出し = Phoenix スパン (OpenInference 自動計装)
       -> eval.py ラボがスパンへ問い合わせ / Phoenix experiments を実行
       -> LLM ジャッジ（生 HTTP・JSON モード・suppress_tracing）が記録された証拠を採点
       -> スコアは span annotation として Phoenix へ記録
  <- stdout プロトコル: "Q:/A:" 回答 + __EVAL_UI__ スコア行
ダッシュボードが回答・チェック別スコア表・ジャッジの理由・Phoenix リンクを表示
```

エージェント LLM とジャッジ LLM は同じ設定済み Ollama Cloud モデル
（既定 `gpt-oss:120b`）です。ジャッジ呼び出しは意図的に計装から外れています。

**技術構成：** Python · Streamlit · Arize Phoenix（ローカルサーバー、自動起動） ·
OpenInference/OpenTelemetry · OpenAI SDK（Ollama Cloud、OpenAI 互換） ·
DuckDB · Pydantic · Pandas · matplotlib/seaborn · Playwright（テスト記録） ·
Streamlit AppTest（単体チェック）

## ローカル実行（Windows PowerShell）

このプロジェクトのディレクトリで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env を編集して Ollama API キーを貼り付けてください
# （キーは https://ollama.com/settings/keys で作成します）
python -m streamlit run app.py
# -> http://localhost:8501（Phoenix は初回利用時に http://localhost:6006 で自動起動）
```

キーがなければエージェントは動きません。アプリは作成場所を正確に案内します。
実行には数分かかります。各エージェントターンは複数の実際の LLM 呼び出しを含むためです。
ダッシュボードが進行状況をライブでストリーミングします。
ヒント: まず Lab 5 を実行してください。1 つの質問のスパンツリーを見ることが、
他のラボが何を採点しているかを理解する最短の近道です。

### 各ラボの内容

| ラボ | 仕組み | 評価者 | 得られるもの |
|---|---|---|---|
| 5 · トレースデモ | 2 質問を `AgentRun` ルートスパンの下で実行 | — | 2 つの回答 + Phoenix のスパンツリー |
| 7 · ルーター & スキル評価 | スパンクエリ + LLM ジャッジ + コード評価 | Tool Calling (LLM) · SQL Gen (LLM) · Clarity (LLM) · Runnable Code (コード) | チェックごとのスコア + ジャッジの理由付き採点例 |
| 9 · 収束評価 | 17 パラフレーズの Phoenix experiment | Convergence (コード): 最短観測経路 ÷ この経路 | 収束スコア（データセットは再実行時に再利用） |
| 11 · 総合評価 | Phoenix experiments ×2 | Tool selection (LLM) · SQL result match (コード、桁比較) · Clarity (LLM) · Entity correctness (LLM) · Chart code runnable (コード、`exec`) | 比較される 2 つの実験実行（"Overall Experiment" / "v2"） |

対話型の Lab 3（チャット REPL。回答内のチャートコードを実行して保存）も
`python eval.py 3` で利用できます。ダッシュボードの run-all 連鎖からは除外されています。

## 記録された検証結果

各ラボは [record_test.py](record_test.py) がヘッドレス Chromium でアプリを駆動して
エンドツーエンドに検証しました。ラボを選択、実行、「Run finished」を待機、
期待される UI 成果物を検証、アプリと Phoenix のスクリーンショット取得まで行います。
以下の判定はその記録済み実行（2026-10-29）によるものです。生の証拠は
[test_videos/results.json](test_videos/results.json)、ラボごとの動画付きの完全な
[視覚的レポート](test_videos/report.html) を参照してください。

| ラボ | 判定 | 実行時間 | 合格した検証 |
|---|---|---|---|
| 5 トレース | ✅ 合格 | 1.9 分 | 回答メトリック + スパンツリー付き Traces セクション |
| 7 ルーター/スキル | ✅ 合格 | 12.5 分 | 評価スコア + "How this was tested" 採点例 |
| 9 収束 | ✅ 合格 | 1.9 分 | スコア表 + 収束詳細 + 技術ログ |
| 11 総合 | ✅ 合格 | 4.5 分 | スコア表（両実行） + 評価者詳細 + 技術ログ |

単体チェックは `test_app.py` にあります（モックされたサブプロセス上の
Streamlit AppTest: 回答レンダリング、`__EVAL_UI__` スコア表、ラボ別選択ガイド、
失敗パス、セッションリセット動作）。`python -m unittest test_app` で実行します。
注意: Phoenix サーバーが未起動の状態ではスイートは合格します。Phoenix が稼働中だと、
自動起動の readiness チェックが AppTest の 3 秒ウィジェットタイムアウトに間に合わない
ことがあります。

## 制限事項とスコープノート（アプリ内にも表示）

- Lab 7 のスコアは最新の実行だけでなく、一致するすべての保存済みプロジェクトスパンを対象とします。
- 収束は経路効率のみを測定します。短い経路は正しい答えを証明しません。
- Lab 11 の「ツール応答なし = 合格」はスコープ制限です。ツール選択も確認してください。
- LLM ジャッジは誤判定することがあります。すべての判定に完全な理由が付くため確認できます。
  コード評価は決定論的です。
- SQL 結果マッチングは桁の連結を比較するもので、結果の完全な意味論ではありません。

## 認証情報と安全上の注意

- 公開するのはプレースホルダーキーのテンプレート（`.env.example`）だけです。
  実際の `.env` は Git の対象外で、この公開コピーには含めていません。
  設定項目: `OLLAMA_API_KEY`、`OLLAMA_BASE_URL`、`OLLAMA_MODEL`、`PHOENIX_ENDPOINT`。
- ジャッジとエージェントは設計上 1 つのモデル/エンドポイントを共有します。
  `OLLAMA_MODEL` を変更すると分離できます。
- エージェントは LLM が生成した SQL（同梱 parquet 上の読み取り専用 DuckDB）と
  LLM が生成したチャートコード（matplotlib、Agg バックエンド）を実行します。
  生成されたチャートコードを他の場所で再利用するパターンにする前に、内容を確認してください。

## プロジェクト構成

| パス | 用途 |
|---|---|
| [app.py](app.py) | Streamlit ランチャー/レンダラー: `eval.py <lab>` を実行、出力を解析、スコア表を表示 |
| [eval.py](eval.py) | すべてのラボ: スパンクエリ評価、experiments、ジャッジ、データセット/再利用、A/B プロンプト切替 |
| [utils.py](utils.py) | エージェント本体: ルーターループ、3 ツール、Phoenix セットアップ、軌跡サマライザー |
| [test_app.py](test_app.py) | モックされたサブプロセス上の Streamlit AppTest 単体チェック |
| [record_test.py](record_test.py) | Playwright ドライバー: ラボ別の動画キャプチャ + 検証 + 判定 |
| [data/](data/) | 販売データセット（価格弾力性 + プロモーションの parquet）。DuckDB が読み取ります |
| [test_videos/](test_videos/) | 記録されたラボ実行: 動画、スクリーンショット、results.json、report.html |
| [Userguide.html](Userguide.html) | 図解付きの完全ガイド（英語）。ダウンロードしてブラウザーで開けます |
