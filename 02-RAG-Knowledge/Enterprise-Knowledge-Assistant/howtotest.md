# How to Test  EEnterprise Knowledge Assistant

Complete manual test guide: what to start, in what order, how to confirm the app is ready,
and the test cases to run with steps and test data.

> Automated suite: `pytest tests/` (30 tests)  Esee §6. This file covers the **manual/E2E** path.

---

## 1. What to start first (and why)

| # | Service | Purpose | Needs starting? |
|---|---------|---------|-----------------|
| 1 | **Local Ollama daemon** (`localhost:11434`) | Embeddings (`nomic-embed-text`)  Ecloud plan has NO embedding models | Usually auto-starts (Windows service / `ollama serve`) |
| 2 | **Qdrant** (`localhost:6333`) | Vector store (all 6 collections: chunks, entities, edges…) | **Yes  Ealways** |
| 3 | **Ollama Cloud** (`ollama.com`) | LLM `gpt-oss:120b` | No  Eremote API; only needs `OLLAMA_API_KEY` in `.env` |
| 4 | **Streamlit app** (`localhost:8501`) | The UI under test | **Yes  Ealways, after 1+2 are up** |

Startup order matters: **Ollama ↁEQdrant ↁE(verify) ↁEStreamlit**.
The app reads Qdrant/Cognee state lazily, so both must be up before you chat.

---

## 2. How to start  Eexact commands (PowerShell)

All commands assume project root:
`cd 02-RAG-Knowledge\Enterprise-Knowledge-Assistant   # from the repository root`

### 2a. Local Ollama daemon
```powershell
ollama list
```
- If a model list prints ↁEdaemon is up. If it errors ↁEstart it:
```powershell
ollama serve
```
(keep this terminal open, or run it as a service)

### 2b. Qdrant
⚠�E�EMust be started **with CWD = the `qdrant` folder**, or its storage lands in the wrong place:
```powershell
cd 02-RAG-Knowledge\Enterprise-Knowledge-Assistant   # from the repository root\qdrant
Start-Process .\qdrant.exe -WindowStyle Minimized
cd 02-RAG-Knowledge\Enterprise-Knowledge-Assistant   # from the repository root.
```

### 2c. Preflight  Econfirm ALL services before starting the app
```powershell
.\.venv\Scripts\python.exe scripts\check_services.py
```
Expected output  E**4 green lines** (values real, never fabricated):
```
✁ELocal Ollama daemon: daemon up at http://localhost:11434, 27 models listed
✁EEmbedding model 'nomic-embed-text': 'nomic-embed-text' available on local daemon
✁EOllama Cloud 'gpt-oss:120b': 'gpt-oss:120b' responded (2 chars) via https://ollama.com/api
✁EQdrant: up at http://localhost:6333, version 1.19.1
✁EALL CHECKS PASSED
```
❁EAny red line ↁEfix that service first (see §8 Troubleshooting).

### 2d. Start the app
```powershell
.\.venv\Scripts\python.exe -m streamlit run app\main.py
```
Terminal shows:
```
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

---

## 3. How to confirm the app is ready to test

Open **http://localhost:8501** in the browser and verify, in order:

1. **Sidebar ↁEDocuments**: lists **Indexed documents (11)**  Eall corpus PDFs
   (acceptable-use-policy, benefits-overview, code-of-conduct, expense-reimbursement-policy,
   holiday-schedule, information-security-policy, onboarding-guide, performance-review-policy,
   pto-and-leave-policy, public_counsel_employee_handbook, remote-work-policy).
2. **Sidebar ↁESystem Status**: click **Re-check services** **once** and WAIT  Ethe spinner runs
   ~10 E0 s (the Ollama Cloud ping is slow). Do **not** click repeatedly; each click restarts the
   checks. Expect **6 🟢 lines**:
   | Line | Expected detail |
   |------|-----------------|
   | Local Ollama daemon | daemon up at http://localhost:11434, 27 models listed |
   | Embedding model 'nomic-embed-text' | available on local daemon |
   | Ollama Cloud 'gpt-oss:120b' | responded (2 chars) via https://ollama.com/api |
   | Qdrant | up at http://localhost:6333, version 1.19.1 |
   | Cognee | Ready  E1604 nodes / 4605 relationships |
   | Knowledge base | Indexed  E131 chunks |
   *(A transient 🔴 Cognee "Could not set lock … Error 33" means two browser tabs read the graph
   simultaneously  Ere-check once more and it clears.)*
3. **Main area**: title + chat input box only (all controls moved to the sidebar).
4. **Sidebar**: Documents + System Status + Configuration + **⚙︁ERetrieval options**
   (strategy = `hybrid`), **🐞 Example questions**, **🧠 Knowledge graph view** (with
   What-is-this/How-to-read guidance), **Developer / debug mode** toggle (OFF by default).

**App is ready when: 11 docs listed + 6 green status lines + chat box present.**

---

## 4. Test cases

### TC-01  EGrounded answer with real citations (CORE)
**Steps:**
1. In the chat box type: `How many annual leave days do employees receive?`
2. Send (Enter).
3. Wait ~10 E0 s (hybrid retrieval + cloud LLM generation).
4. Expand the **Sources** expander under the answer.

**Expected:**
- Answer describes tiered annual vacation days by tenure (observed: 10 days years 1 E,
  15 days years 6 E0, 20 days year 11+)  Ewording may vary, numbers must come from policy text.
- Answer contains inline evidence refs like `[1]`…`[n]`.
- **Sources** lists REAL corpus filenames, e.g. `pto-and-leave-policy.pdf` and/or
  `public_counsel_employee_handbook.pdf`  Enever invented names, never page numbers.
- ❁EFail if: answer fabricates numbers not in policy, or sources are missing/unknown files.

### TC-02  EUnknown question ↁEno fabrication (CORE)
**Steps:**
1. Type: `What is the company's private jet travel policy?`
2. Send.

**Expected:**
- Polite "no information found in the documents"-style response (phrases like *not found*,
  *could not be found*, *no information*).
- **No** fabricated policy and **no** Sources block (or empty one).
- ❁EFail if the LLM invents a jet policy.

### TC-03  EHybrid retrieval trace (debug mode)
**Steps:**
1. Toggle **Developer / debug mode** ON (**sidebar**, bottom).
2. Re-ask: `How are remote work and information security related?`
3. Expand **🐞 Debug  Eretrieval trace**.

**Expected:**
- **Retrieval Strategy** = `hybrid`.
- **Vector Results**: 5 numbered hits with real filenames + scores + chunk ids.
- **Graph Entities/Relationships**: real triplets, e.g.
  `remote work policy ──is_a──> policy` (relationship names from the graph, not invented).
- **Evidence** block shows `[1]…[n]` chunk texts + `[G1]…[Gn]` triplets.
- Answer references both remote work and information security.

### TC-04  ERelationship question (graph leg)
**Steps:**
1. Ask: `Which policy governs remote work?`

**Expected:**
- Answer names the remote-work policy; debug trace (if on) shows ≥1 graph triplet mentioning
  "remote work"; Sources include `remote-work-policy.pdf` (via chunk hits).

### TC-05  ERetrieval strategy toggle
**Steps:**
1. Sidebar ↁE**⚙︁ERetrieval options**, set strategy to `vector`, re-ask TC-01's question.
2. Set back to `hybrid`.

**Expected:**
- `vector` strategy still answers with citations (no graph triplets in debug trace).
- Switching strategies does not error or re-ingest anything.

### TC-06  EExample questions shortcut
**Steps:**
1. Expand **Example questions** below the chat.
2. Click one.

**Expected:** the question is submitted and answered normally.

### TC-07  ECLI end-to-end (persistence, no re-ingestion)
**Steps** (in PowerShell, Streamlit can stay up for this read-only script):
```powershell
.\.venv\Scripts\python.exe scripts\ask_question.py
```
**Expected:**
- Prints a grounded answer + real source filenames.
- Starts fast (existing KB reused  Eproves nothing rebuilds on a fresh process).
- App terminal/log shows "11/11 skipped" style ledger behavior if ingestion were triggered  E
  it should NOT trigger any ingestion at all.

### TC-07b  EKnowledge-graph visualization (read-only, optional)
**Steps:**
1. Sidebar ↁE**🧠 Knowledge graph view**  Eread the **What is this? / How to read it**
   guidance (explains columns, relationships, importance, search, layout tabs).
2. Click **🕸�E�EOpen graph view** ↁEopens a new browser tab at
   `http://localhost:8501/app/static/graph_visualization.html`.
3. Wait for the layout to finish ("Laying out graph…" ↁE**"Done!"**, up to ~2 min).
4. Try: search `remote work`, click a node (source + provenance panels), switch Force/Story.

**Expected:**
- Interactive page "Cognee Knowledge Graph": **500 nodes / 1,394 edges** in column layout
  (Documents ↁEChunks ↁEEntities ↁETypes), node search, Story/Flow/Force layouts, dark mode,
  Schema/Memory/Semantic tabs; clicking a node shows its source chunk + provenance.
- CLI alternative (⚠�E�Estop Streamlit first  ELadybug lock):
  `.\.venv\Scripts\python.exe scripts\visualize_graph.py` ↁEwrites
  `data/graph_visualization.html` (2.8 MB); add `--full` for the entire graph (1604 nodes).
- ❁EFail if: the page never passes "Laying out graph…" (note: inside iframes the layout
  stalls at 0%  Ecognee's viz only works full-page, which is why the app opens a new tab),
  or "Could not set lock ... Error 33" (Streamlit still running during CLI export).

### TC-08  EUpload safety + processing (optional, writes to KB)

### TC-08  EUpload safety + processing (optional, writes to KB)
**Test data**  Ecreate `data/documents/travel-expense-note.txt` with exactly:
```
Company travel note (test document).
Employees must submit expense reports within 30 days of travel.
The per-diem meal allowance is 55 USD per day.
```
**Steps:**
1. Sidebar ↁEUpload documents ↁEselect the .txt file.
2. Confirm it appears in the Documents list (sidebar auto-refreshes).
3. Click **Process documents** and wait (one small file ≁E1 E min via cloud LLM).
4. Ask: `What is the per-diem meal allowance?`

**Expected:**
- Upload succeeds; filename unchanged (sanitized if needed).
- Process reports `Documents processed: 1`.
- Answer cites `travel-expense-note.txt` with **55 USD**.
- Clicking **Process documents** again ↁE"Nothing to process  EN file(s) already indexed"
  (hash-ledger duplicate detection).

### TC-09  EUnsafe filename rejection (optional, no KB writes)
**Test data:** a file named `bad name!.txt` (space + `!`  Eallowed chars pass) and one named
`..%2F..%2Fevil.txt` if you can force such a name via tooling.
**Expected:** UI either accepts-and-sanitizes to a safe name under `data/documents/`, or warns
"Rejected unsafe filename"  Enever writes outside `data/documents/`.

### TC-10  EClear knowledge base (⚠�E�EDESTRUCTIVE  Erun LAST only if required)
**Steps:**
1. Stop any other test. Note: re-ingesting the full corpus afterwards takes **~20 E6 min**.
2. Sidebar ↁE**Clear knowledge base** popover ↁE**Yes, clear everything**.
3. Verify: Documents list empties metadata, status shows Cognee "not ingested yet", 0 Qdrant
   collections.
4. Rebuild: `.\.venv\Scripts\python.exe scripts\ingest_corpus.py` (~20 E6 min; 11/11 processed
   first time, then 11/11 skipped on duplicate re-run).
5. Re-run TC-01 to confirm the rebuilt KB answers correctly.

**Expected:** source PDFs in `data/documents/` are KEPT; only vectors/graph/metadata are deleted.

---

## 5. Test data details (corpus ground truth)

Corpus: 11 PDFs in `data/documents/`. Known-answer facts (verified against the actual PDF text  E
use these to judge groundedness):

| Question topic | Document(s) | Ground-truth fact |
|---|---|---|
| Annual/vacation leave | `pto-and-leave-policy.pdf`, `public_counsel_employee_handbook.pdf` | Tiered by tenure  E10 days (early years), 15 (mid), 20 (11+ yrs); sick leave separate (10 days/80 hrs) |
| Remote work | `remote-work-policy.pdf` | Policy defines fully-remote / hybrid arrangements |
| Information security | `information-security-policy.pdf` | Access-control and device rules |
| Holidays | `holiday-schedule.pdf` | Company holiday calendar |
| Expenses | `expense-reimbursement-policy.pdf` | Submission deadlines/receipts |
| Conduct / AUP / onboarding / performance | respective PDFs | Standard policy content |

**Negative (not-in-corpus) questions for TC-02:** private jet policy, salary of the CEO,
2026 picnic schedule, quantum-computing policy  Enone of these exist in the corpus.

**Current KB state (for status-line expectations):** graph 1604 nodes / 4605 relationships,
131 chunks indexed, 6 Qdrant collections (`DocumentChunk_text`=131, `Entity_name`,
`EdgeType_relationship_name`, `EntityType_name`, `TextSummary_text`, `TextDocument_name`=11).
Extraction is LLM-driven, so re-ingested counts may differ slightly  Ethat is expected;
status lines just need plausible non-zero values.

---

## 6. Automated regression suite (after manual pass, or before release)

⚠�E�E**Stop Streamlit first** (Ctrl+C)  Ethe Ladybug graph DB file-locks and a second process's
pytest dies with "Could not set lock (.lbug, Error 33)".

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -v
```
Expected: **82 passed** in ~7 E min (config 9, groundedness 4, health 3, ingestion 4, qdrant 3,
retrieval 9, evidence-gate 9, bm25 7, fusion 7, golden-dataset 9, evaluation 18, plus the
Phase 1 E3 suites). The cloud-LLM leg auto-skips (never fails) if the paid endpoint is
unreachable. PowerShell note: read the `N passed` summary line, not the exit code (`2>&1`
wrapping makes benign stderr look like failure).

---

## 7. Pass criteria (definition of "everything works")

- [ ] `check_services.py` ↁE4/4 green
- [ ] UI ready state: 11 docs + 6 green status lines + chat box
- [ ] TC-01 grounded answer + real sources
- [ ] TC-02 unknown question ↁEnot-found, no fabrication
- [ ] TC-03 debug trace shows both vector + graph evidence
- [ ] TC-07 CLI answers from existing KB with zero re-ingestion
- [ ] (if run) TC-08 upload ↁEprocess ↁEcited answer ↁEduplicate skip
- [ ] `pytest tests\` ↁE82 passed

## 7b. Production-grade layer checks (enforcement gate + evaluation)

**Gate (manual, in the app or CLI):** ask *“Who won the 1998 FIFA World Cup final? E ↁE
the answer must be the standard refusal “I don't have enough evidence… Eand the debug
panel must show **Evidence gate: REFUSED** with “The LLM was not called. EA real policy
question must answer normally.

**Offline evaluation (stop Streamlit first; full run ~25 min):**

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --limit 6   # smoke, ~3 min
.\.venv\Scripts\python.exe scripts\evaluate_rag.py             # full 58-question run
```

Expected (6-question smoke, calibrated TOP_K=8): **all 5 metrics PASS and 6/6 questions
pass**. The full run writes `evaluation\results.json` + `results.csv` and applies the
quality gates from `data\eval\quality_gates.yaml`; exit code 1 = gate failure
(CI-ready). Baseline runs are stored in `evaluation\baseline*\` (gitignored).

## 8. Troubleshooting during testing

| Symptom | Cause / Fix |
|---|---|
| `check_services` Qdrant ❁E| qdrant.exe not started from the `qdrant` folder  Erestart per §2b |
| Status lines blank / spinner forever | One check cycle takes 10 E0 s; click Re-check **once** and wait. Repeated clicks restart the checks |
| 🔴 Cognee "Could not set lock … Error 33" | Two tabs/processes reading the graph at once  Eclose one, re-check; transient |
| sqlite3 "unable to open database file" | Cognee import-order bug  Ereport it, don't chase DB locks |
| "No documents indexed yet" but KB has data | Regenerate metadata: `DocumentManager(...).sync()`  Ethe sidebar now self-heals this on render |
| KB status "not ingested yet" / dataset not found | Re-ingest: `scripts\ingest_corpus.py` (~20 E6 min; ledger skips unchanged files) |
| Chat answer has no sources | Check debug trace: if vector hits are empty, Qdrant collection may be empty ↁEre-ingest |
| `visualize_graph.py` hangs after "HTML written" | Known cosmetic hang in cognee 1.4.2 post-export cleanup  Eif `data/graph_visualization.html` exists and ends with `</html>`, the export succeeded; Ctrl+C the script and open the file directly |
| Full wipe wanted | `scripts\reset_database.py --yes` (keeps the 11 PDFs)  Estop Streamlit first |
