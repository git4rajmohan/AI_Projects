言語 / Languages: [English](README.md) | **日本語**

---

# DocFlow — AI Document Intelligence & Invoice Approval Engine

**AI が読み取り、コードが判断し、人間がリスクを担う**請求書承認ワークフローです。請求書 PDF（画像のみのスキャンでも）は LLM がフィールドごとの信頼度付きで読み取りますが、金銭に関する判断はすべて決定論的な検証と順序付きポリシールールが行い、本当にリスクの高い請求書だけが、証拠一式と並べて提示された状態で人間のレビュアーに届きます。

> FastAPI · Streamlit · SQLite · PyMuPDF · Tesseract OCR · Ollama (live or mock) · pytest

## このプロジェクトが示すもの

- **ドキュメントインテリジェンス** — PDF テキストレイヤーの抽出（PyMuPDF）と、画像のみのスキャンに対する Tesseract OCR フォールバック。LLM による構造化フィールド抽出は**フィールドごとの信頼度スコア**付き
- **決定論的な判断コア** — 9 つの検証チェック、二重/三重 PO マッチング、順序付きポリシールール R001–R008。すべて純粋な Python で**LLM への依存ゼロ**
- **Human-in-the-loop 承認** — 証拠を先に見せるレビュアー UI（ドキュメント、フィールド、チェック結果、ルールの根拠を並列表示）で、approve / reject / request-info / correct-and-resubmit を実行
- **追記専用の監査証跡** — パイプラインの各ステージがイベントを追記し、UI のワークフローストリップは監査イベント*から*描画されるため、表示がデータベースと食い違うことはありません
- **測定可能な評価** — 10 の請求書シナリオに対する 6 レベルの評価ハーネスで、リスク加重エラースコア（クリティカルフィールドは ×5）を使用

## なぜこのプロジェクトが存在するのか

LLM が読み取り・抽出を担当し、決定論的な検証とポリシールールが金銭に関する判断を下す、本番スタイルのドキュメント AI ワークフローを示すプロジェクトです。リスクはレビューゲートを通じて人間が担います。LLM は優れた読み手ですが信頼できない判断者です。100 万円の支払いを、自信満々に間違えるのは高くつきます。そのためここでの抽出 LLM には、しきい値・承認・不正検知について一切の権限がありません。このパターンは契約審査、保険請求、医療事前承認にもそのまま一般化できます。

## アーキテクチャ

```text
                INVOICE (.pdf, even image-only)
                          ↓
              PyMuPDF text load (quality-graded)
                          ↓
              AI Field Extraction (Ollama or mock)
                structured JSON + per-field confidence
                          ↓
        ┌─────────────────┴─────────────────┐
        ↓                                   ↓
 Vendor Validation (9 checks)    Line-Item Arithmetic (recomputed in code)
        ↓                                   ↓
        └─────────────────┬─────────────────┘
                          ↓
              Invoice ↔ PO Match (two-way + AI line map, code-verified)
                          ↓
              Optional Goods-Receipt Match (three-way)
                          ↓
              Deterministic Policy Engine (R001–R008, first trigger wins)
                          ↓
              ┌───────────┴───────────┐
              ↓                       ↓
        AUTO_APPROVE          HUMAN_REVIEW / EXCEPTION / REJECT
              (¥<100k green)          ↓
                          Human Reviewer (Streamlit, evidence-first)
                          ↓
              Systems of Record (SQLite) + append-only Audit Trail
```

**ポリシーエンジンは（検証レポート、マッチングレポート、抽出済み請求書）の純粋関数**であり、AI を一切使わずにユニットテストされています。唯一の AI コンポーネントは抽出（`app/extraction/`）で、OpenAI 互換の LLM 呼び出しで構造化 JSON を返します。LLM はデータベースには触れず、金銭に関する判断も一切行いません。

## ワークフロー

1. **アップロード → パイプライン実行**: `received → extracted → validated → matched → policy_decided → outcome` の各ステージが請求書ステータスを更新し、次のステージへ進む前に監査イベントを追記します
2. **自動終了**: 10 万円未満のクリーンな請求書は自動承認（R008）。重複は挿入*前*に拒否（R001）され、ブロックイベントは元の請求書に記録されます。孤立行は発生しません
3. **人間のループ**（リスクがある場合のみ）: レビュアーはドキュメント、抽出フィールド、9 件すべてのチェック、マッチングレポート、発火したルールを確認した上で、承認・拒否・情報請求・フィールド修正のいずれかを行います（修正はパイプラインの**検証ステージから**再入力され、修正フィールドの信頼度は 1.0、それ以外は元のスコアを維持 — 信頼度のすり替えはありません）

## ポリシーエンジン — R001–R008（順序付き、最初に発火したルールが判断となり、発火したルールはすべて `reasons[]` に収集）

| ルール | 発火条件 | 判断 |
|---|---|---|
| R001 | 同一ベンダー + 同一請求書番号が記録済み | **REJECT**（挿入前にブロック） |
| R002 | 銀行口座 ≠ ベンダーマスタ | **HUMAN_REVIEW**（必須） |
| R003 | PO 番号が見つからない | **EXCEPTION** |
| R004 | いずれかのチェックが FAIL / MISMATCH | **EXCEPTION** |
| R005 | クリティカルフィールドの信頼度 < 0.6 | **HUMAN_REVIEW** |
| R006 | 合計 > ¥1,000,000 | **FINANCE_REVIEW** |
| R007 | 合計 ≥ ¥100,000 | **MANAGER_REVIEW** |
| R008 | すべて正常、< ¥100,000 | **AUTO_APPROVE** |

しきい値、許容誤差、信頼度の下限はすべて決定論的な `.env` 設定であり、LLM は決して見ることができません。

## 技術スタック

| 領域 | 技術 |
|---|---|
| LLM 抽出 | OpenAI 互換クライアント → Ollama（`gpt-oss:120b`）、live **または** mock モード |
| バックエンド | FastAPI（8 ルート）+ Pydantic v2 ワイヤモデル |
| レビュアー UI | Streamlit（薄い `requests` クライアント — DB への直接アクセスなし） |
| ドキュメント | PyMuPDF（テキストレイヤー + ラスタライズ）、pytesseract + Pillow（オプションの OCR） |
| ストレージ | SQLite（vendors、POs、receipts、invoices、exceptions、reviews、audit_events） |
| テスト | pytest — 101 passed, 1 skipped（スキップされたテストは実 LLM が必要） |

Mock ファースト設計：`.env` は初期状態で `EXTRACTION_MODE=mock` となっており、各サンプルの正解 JSON を再生します。パイプライン全体（検証 → マッチング → ポリシー → レビュー）が**LLM 依存ゼロ**で実行・テストでき、実 Ollama に切り替えるには環境変数を 1 つ変更するだけです。

## デモ

同梱アプリ（FastAPI + Streamlit レビュアー）を実際に動かしたスクリーンショットです。サイドバーで API アドレスとレビュアー名を設定します — 承認者名は*誰が何を承認したか*が監査記録の一部になるため、アクションボタンのゲートになっています。

**All Invoices** — 全シナリオの最終ステータスを一望：approved（d1, d4, d10）、rejected（d2, d8）、auto-approved（d9 — 収納箱に入ることすらなし）、info-requested（d5）、finance-parked（d7）：

![All Invoices page with per-invoice statuses](docs/screenshots/ui_allinvoices.png)

**判断バナー + ワークフローストリップ** — 請求書 d2（請求 150、PO は 100）では、発火したルール、根拠リスト、監査イベントから描画された 2 本のストリップを確認できます：🤖 ロボットのステップはすべて緑、🧍 人間のループは **rejected** で終了：

![Quantity-mismatch decision banner with workflow strips](docs/screenshots/ui_review_banner.png)

**証拠ファーストのレビュー** — レビュアーが生 PDF を読んで推測することはありません：片側にドキュメントと抽出フィールド、もう片側に 9 件すべての検証チェックとマッチングレポート：

![Evidence panel: document, extracted fields, validation checks](docs/screenshots/ui_review_evidence.png)

**請求書 vs PO — 明細単位** — 不一致の正確な箇所を並べて表示：Product A 🚨 150 vs 100、Product B ✅ 150 vs 150：

![Per-line invoice vs PO comparison table](docs/screenshots/ui_review_mismatch_table.png)

**PO が見つからない例外（d5）の人間ループ** — 実際の PO 番号が届くまで、ストリップは *info_requested* で停止します：

![Missing-PO exception parked at info_requested](docs/screenshots/ui_review_missing_po_banner.png)

- **例外収納箱（Exception inbox）**には人間の対応待ちの請求書だけが表示されます — 安全な少額請求書は決して現れません
- **監査タイムライン**エクスパンダー：ステージごとにタイムスタンプ付きイベントを 1 件記録し、数か月後でも再生可能

**完全ガイド：** [`userguide.html`](./userguide.html) — 4 タブ構成のウォークスルー（ピッチ、非技術者向け、技術者向け、用語集）。**シナリオのウォークスルー：** [`demo_script.md`](./demo_script.md)。段階的なテストマトリクス：[`howtotest.md`](./howtotest.md)。

## サンプルドキュメント（data/invoices/、10 シナリオ）

| sample | scenario | expected decision |
|---|---|---|
| `d1_normal` | normal ¥850k invoice, PO-12345 | MANAGER_REVIEW (R007 band) |
| `d2_qty_mismatch` | billed 150, PO says 100 | EXCEPTION (R004) |
| `d3_duplicate` | invoice number already paid | REJECT (R001), blocked pre-insert |
| `d4_bank_change` | bank account ≠ vendor master | HUMAN_REVIEW (R002) |
| `d5_missing_po` | PO-99999 not in the PO system | EXCEPTION (R003) |
| `d6_low_confidence` | degraded scan, confidence capped | HUMAN_REVIEW (R005) |
| `d7_high_value` | ¥1.2M invoice | FINANCE_REVIEW (R006) |
| `d8_currency_mismatch` | USD invoice vs JPY PO | EXCEPTION (R004) |
| `d9_small` | ¥60k, everything green | AUTO_APPROVE (R008) |
| `d10_scanned` | image-only scan (zero text layer) | MANAGER_REVIEW via OCR (HUMAN_REVIEW without Tesseract) |

サンプルは `tools/make_sample_invoices.py` で決定論的に再生成できます。各サンプルにはモック抽出と評価ハーネスが使う `*_ground_truth.json` が付属します。

## 実行方法

```bash
py -3.11 -m venv .venv
.venv/Scripts/pip install -r requirements.txt
copy .env.example .env    # then paste your Ollama key (or keep EXTRACTION_MODE=mock for offline)

# eval harness: 10 scenarios through the real pipeline → evaluation/report.md + results.json
.venv/Scripts/python.exe -m evaluation.run_eval

# API (terminal 1) — seed the DB first if data/docflow.db is missing
.venv/Scripts/python.exe -c "import app.db; app.db.seed('data/docflow.db')"
.venv/Scripts/python.exe -m uvicorn app.api.main:app --port 8000

# reviewer UI (terminal 2)
.venv/Scripts/python.exe -m streamlit run ui/reviewer.py

# tests
.venv/Scripts/python.exe -m pytest tests/ -q
```

各シナリオのセットアップと検証手順は [`howtotest.md`](./howtotest.md) にあります。プロジェクトは Windows 上の **Python 3.11/3.12** で開発されました。

## API ルート（app/api/main.py）

`GET /health` · `POST /invoices/upload` · `GET /invoices[?status=]` · `GET /invoices/{id}`
（監査イベントから組み立て） · `GET /invoices/{id}/audit` · `GET /invoices/{id}/document` ·
`POST /invoices/{id}/review` · `DELETE /invoices/{id}`（再テスト用削除、シード済みフィクスチャは拒否） · `GET /exceptions`

## テスト / 評価

```bash
.venv/Scripts/python.exe -m pytest tests/ -q          # 101 passed, 1 skipped (live LLM)
.venv/Scripts/python.exe -m evaluation.run_eval       # 6-level harness → report.md
```

評価ハーネスは 10 シナリオすべてを新しい DB で実パイプラインに通し、フィールド精度（クリティカルフィールド `total_amount` / `bank_account` / `vendor` は ×5 で重み付け）、マッチング精度、例外の検出率、誤承認、レイテンシ（平均 + p95）、削減されたレビュー時間の推定値を報告します。最新の同梱結果は [`evaluation/report.md`](./evaluation/report.md) にあります。サンプル評価セットでの結果は、**判断精度 1.0、マッチング精度 1.0、例外検出率 1.0、誤承認 0** です。これらは **10 のシード済みシナリオに対するサンプル/プロジェクト評価の結果**であり、一般的な本番性能の主張ではありません。

## 主要な AI エンジニアリングの概念

- フィールドごとの信頼度スコアリングと OCR フォールバックを備えたドキュメント AI
- 純粋関数としての決定論的ポリシーエンジン（判断パスに LLM を含まない）
- 証拠ファースト UI による Human-in-the-loop レビュー
- UI の状態機械を駆動する追記専用の監査証跡
- Mock ファーストの LLM テスト（オフラインで再生可能なデモとテストスイート）

## 安全性 / 信頼性

- 重複ガードは**挿入前**（孤立行なしの冪等性）
- 金額計算は常にコード側で再計算 — LLM が明記した合計金額は決して信用しません
- すべてのチェックは毎回の実行で必ず出力されます（チェックの欠落自体が不審です）
- OCR の優雅な劣化：Tesseract バイナリがなければ、画像のみのページは低品質として読み込まれ → 人間レビューへ。500 エラーにはなりません
- 修正は検証チェーン全体を再実行します（信頼度のすり替えなし）

## プロジェクト構成

```text
app/           ingest, extraction, validation, matching, policy, workflow, audit, api
ui/            Streamlit reviewer (thin API client, zero DB access)
data/          sample invoices + ground truth (DB & uploads are gitignored, created at runtime)
evaluation/    6-level eval harness → report.md + results.json
tests/         pytest per phase (conftest regenerates samples)
tools/         make_sample_invoices.py, build_userguide.py, capture_screens.py
```

## このプロジェクトが他と違う点

LLM を*読み取り*に限定したドキュメント AI です。決定論的で順序付きのポリシーエンジンが金銭に関する判断をすべて行い、リスクの高い少数派は人間が担い、追記専用の監査証跡がすべての判断を再生可能にします。chat-with-PDF 型のデモとは異なり、ここでの AI コンポーネントは意図的に「信頼しない」対象であり、価値はその周囲にあります。

## AI 支援による開発

このプロジェクトは AI 支援のコーディングワークフローを用いて開発されました。アーキテクチャ、実装判断、テスト、デバッグ、検証は開発中に見直しと改善が行われました。