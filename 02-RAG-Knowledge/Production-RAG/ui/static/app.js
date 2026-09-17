/* RAG Pipeline Visualizer — SPA logic */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  tab: "ingest",
  meta: null,          // PARAM_META from server
  values: null,        // current config values {tab: {step: {param: v}}}
  steps: null,         // STEP_DEFS
  selectedFiles: [],   // ingestion file paths
  runs: { ingest: null, query: null, eval: null, suite: null },
  selectedNode: null,  // {tab, key}
  activeRunId: null,   // server run_id while a suite is in flight (Stop button)
};

/* ── helpers ─────────────────────────────────────────────── */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── tabs ────────────────────────────────────────────────── */

function switchTab(tab) {
  state.tab = tab;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${tab}`));
}

/* ── workflow rendering ──────────────────────────────────── */

/* Hover text per workflow node: what actually happens in the step. */
const NODE_HELP = {
  ingest: {
    load: "Reads the selected files from disk (file pattern + encoding from config) and measures chars/words. Text is held in memory for the next steps.",
    chunk: "Splits each document into chunks using the configured strategy: structural (## / ### header boundaries), character (fixed windows with overlap), or semantic (embedding-similarity breakpoints). Shows per-doc counts and chunk previews.",
    embed: "Sends every chunk to the local embedding model (nomic-embed-text via Ollama localhost) and stores a 768-dim vector per chunk. Cloud Ollama has no embedding models — embeddings stay local.",
    store: "Deletes stale chunks of the selected docs, then upserts each chunk into the ChromaDB collection: id + raw text + embedding vector + metadata (this is what citations resolve to later).",
  },
  query: {
    embed_query: "Vectorizes your question with the same embedding model used at ingestion (must match, or vector spaces misalign). Shows dimensions, L2 norm and first 8 values.",
    retrieve: "Finds candidate chunks: hybrid = BM25 keyword ranking + vector similarity search (top_k × overfetch); semantic = pure vector similarity only. Shows both ranked lists with scores.",
    rerank: "Reciprocal Rank Fusion: merges the BM25 and vector rankings into one order using rrf_score = 1/(rank+k) summed over both lists; keeps the final top_k chunks.",
    augment: "Builds the LLM prompt: the system instruction (grounding rules + citation format) plus every retrieved chunk labeled [Chunk n - doc | section], followed by your question.",
    generate: "Calls the chat model (gpt-oss:120b on Ollama Cloud) with the prompt, streams back the grounded answer, and extracts the [Source: doc, Section: section] citations from the text.",
  },
  eval: {
    load_sections: "Reads all stored chunks from ChromaDB and groups them by section_title (doc_title + section). Stub sections and separator titles are skipped; up to Max sections are kept for generation.",
    generate_pairs: "For each section, the cloud LLM (gpt-oss:120b) writes question/reference-answer pairs answerable ONLY from that section. Also creates one multi-hop pair per doc and two negative cases (topic absent from the docs).",
    filter: "Auto-filters the candidates with the LLM: closed-book check (question answerable without the docs → rejected), grounding check (reference not supported by source → rejected), and embedding-based dedupe of near-identical questions.",
    review: "Shows every kept candidate with a keep-checkbox. Uncheck bad pairs, then press '✔ Freeze checked items' to write the frozen golden set file (eval/golden_set.jsonl) used by later evaluation runs.",
  },
  suite: {
    load_golden: "Reads the frozen golden set (eval/golden_set.jsonl) and reports per-kind counts and section coverage. The suite scores exactly these questions.",
    prepare: "Inspects the ChromaDB corpus (chunk count, dominant chunking strategy) and plans the legs: single mode uses the corpus as-is; ab mode re-ingests docs/ once per chunking strategy (structural, character, semantic).",
    run_questions: "Runs every golden question through the live pipeline (retrieve → prompt → generate) and scores it with deterministic metrics (recall@k, first relevant rank, citation coverage, must-term coverage, refusal correctness, latency). Writes one snapshot JSON per leg into eval/snapshots/.",
    compare: "Diffs each snapshot against the stored baseline (or the run's first snapshot if none) and emits the gate verdict: 🟢 pass (drops ≤ 0.05), 🟡 warn (0.05–0.15), 🔴 fail (> 0.15). Lists regressed question ids.",
  },
};

function renderWorkflow(tab) {
  const run = state.runs[tab];
  const wf = $(`#workflow-${tab}`);
  wf.innerHTML = "";
  const defs = state.steps[tab];
  defs.forEach((def) => {
    const step = run?.steps.find((s) => s.key === def.key) || { status: "idle", ...def };
    const node = document.createElement("div");
    node.className = `node ${step.status}`;
    node.dataset.key = def.key;
    node.title = NODE_HELP[tab]?.[def.key] || def.title;
    node.innerHTML = `
      <span class="node-icon">${def.icon}</span>
      <span class="node-title">${def.title}</span>
      ${step.duration_ms != null ? `<span class="node-duration">${step.duration_ms} ms</span>` : ""}
      <span class="node-status">${step.status === "idle" ? "○" : step.status === "running" ? "◐" : step.status === "completed" ? "●" : "✕"}</span>`;
    node.addEventListener("click", () => selectNode(tab, def.key));
    wf.appendChild(node);
  });
}

function setNodeStatus(tab, key, status, progressText) {
  const node = $(`#workflow-${tab}`).querySelector(`.node[data-key="${key}"]`);
  if (!node) return;
  node.classList.remove("running", "completed", "error");
  if (status) node.classList.add(status);
  const badge = node.querySelector(".node-status");
  badge.textContent = status === "running" ? "◐" : status === "completed" ? "✓" : status === "error" ? "✕" : "○";
  const run = state.runs[tab];
  const step = run?.steps.find((s) => s.key === key);
  if (step?.duration_ms != null) {
    let d = node.querySelector(".node-duration");
    if (!d) { d = document.createElement("span"); d.className = "node-duration"; node.insertBefore(d, badge); }
    d.textContent = `${step.duration_ms} ms`;
  }
  setNodeProgress(tab, key, status === "running" ? (progressText || "running…") : null);
}

/* Live progress line + bar under a running node (suite long steps). */
function setNodeProgress(tab, key, text, pct) {
  const node = $(`#workflow-${tab}`).querySelector(`.node[data-key="${key}"]`);
  if (!node) return;
  let line = node.querySelector(".node-progress");
  if (!text) {
    if (line) line.remove();
    return;
  }
  if (!line) {
    line = document.createElement("div");
    line.className = "node-progress";
    node.querySelector(".node-title").parentElement === node
      ? node.insertBefore(line, node.querySelector(".node-duration"))
      : node.appendChild(line);
  }
  line.innerHTML = `<span class="np-text">${esc(text)}</span>`
    + (pct != null ? `<span class="np-bar"><span class="np-fill" style="width:${Math.round(pct * 100)}%"></span></span>` : "");
}

/* Poll server-side suite progress while `run_questions` executes. */
let _progressTimer = null;
function startProgressPolling(runId, tab, key) {
  stopProgressPolling();
  const t0 = Date.now();
  _progressTimer = setInterval(async () => {
    try {
      const data = await api(`/api/suite/progress?run_id=${encodeURIComponent(runId)}`);
      const p = data.progress;
      if (!p) { stopProgressPolling(); return; }  // finished server-side
      const mins = Math.floor((Date.now() - t0) / 60000);
      const secs = Math.floor(((Date.now() - t0) % 60000) / 1000);
      const elapsed = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
      let text = `${p.phase} · ${elapsed}`;
      let pct = null;
      if (p.question_total > 0) {
        pct = p.question_index / p.question_total;
        text += ` · ${p.question_index}/${p.question_total} (${Math.round(pct * 100)}%)`;
        if (p.phase === "ragas-judging" && p.question_index === p.question_total) {
          text = `ragas-judging · ${elapsed} · finishing (computing scores…)`;
        }
      } else if (p.phase === "ragas-judging") {
        text += ` · preparing judge…`;
      }
      if (p.current_question && p.question_index < p.question_total) {
        text += ` — ${String(p.current_question).slice(0, 46)}`;
      }
      setNodeProgress(tab, key, text, pct);
    } catch { /* transient poll errors are fine */ }
  }, 2000);
}

function stopProgressPolling() {
  if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
}

async function selectNode(tab, key) {
  state.selectedNode = { tab, key };
  $$(`#workflow-${tab} .node`).forEach((n) => n.classList.toggle("selected", n.dataset.key === key));
  const run = state.runs[tab];
  if (!run) {
    if (tab === "suite") {
      // After a page reload the in-memory run is gone — fall back to the newest
      // persisted snapshot so node clicks still show data.
      await selectSuiteNodeFromServer(key);
      return;
    }
    renderEmptyDetail(tab);
    return;
  }
  const step = run.steps.find((s) => s.key === key);
  const result = run.results[key];
  if (tab === "suite") {
    openEvalPanel("suite-panel");  // node inspection happens inside the results panel
    $("#diff-view").innerHTML = renderSuiteDetail(key, step, result);
    return;
  }
  const detail = $(`#detail-${tab}`);
  if (!step) return;
  renderDetail(tab, key, step, result);
}

/** Suite node click with no in-memory run: serve the newest snapshot instead. */
async function selectSuiteNodeFromServer(key) {
  openEvalPanel("suite-panel");
  const view = $("#diff-view");
  try {
    const data = await api("/api/eval/snapshots");
    const latest = data.snapshots?.[0];
    if (!latest) {
      view.innerHTML = `<p class="detail-sub">No runs yet — press ▶ Run evaluation suite.</p>`;
      return;
    }
    if (key === "run_questions" || key === "load_golden" || key === "prepare") {
      const snap = await api(`/api/eval/snapshot/${latest.snapshot_id}`);
      const fake = {
        leg_index: 1, legs_total: 1, leg: "(last run)", strategy: latest.config?.strategy,
        snapshot_id: snap.snapshot_id, elapsed_ms: snap.elapsed_ms,
        corpus_strategy: snap.config?.corpus_strategy, aggregate: snap.aggregate,
        ragas: snap.ragas,
      };
      view.innerHTML = `<p class="detail-sub">Showing the newest snapshot ${esc(latest.snapshot_id)} (in-memory run was lost on page reload).</p>`
        + renderSuiteDetail(key === "run_questions" ? "run_questions" : key, { title: "Last run", status: "completed", icon: "🏃" }, key === "run_questions" ? fake : null);
      if (key !== "run_questions") {
        // load_golden / prepare: show their real server-side info too
        view.innerHTML = `<p class="detail-sub">Showing newest snapshot ${esc(latest.snapshot_id)} — click a node after running the suite for step-specific data.</p>` + view.innerHTML;
      }
    } else if (key === "compare") {
      const d = await api(`/api/eval/diff?id=${encodeURIComponent(latest.snapshot_id)}`);
      view.innerHTML = `<p class="detail-sub">Diff of the newest snapshot ${esc(latest.snapshot_id)} vs baseline (in-memory run was lost on page reload).</p>`
        + suiteDiffBlock({ ...d, strategy: d.current_id });
    }
  } catch (e) {
    view.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}

function renderEmptyDetail(tab) {
  $(`#detail-${tab}`).innerHTML = `<div class="detail-empty">Click a workflow node to inspect its data.</div>`;
}

/* ── config panel ────────────────────────────────────────── */

/* The suite tab's PARAM_META sections (setup/retrieve/generate/ragas) are NOT
   step keys — map each section to the card title shown in the config panel. */
const SUITE_SECTION_TITLES = {
  setup: "⚙️ Suite setup — config",
  retrieve: "🔍 Suite retrieval — config",
  generate: "💬 Suite generation — config",
  ragas: "🧪 Ragas scoring (Phase 2) — config",
};

/* Collapse-all helper: config cards render as <details class="config-step">;
   the first card of each panel stays open, the rest start collapsed. */
function makeConfigCard(titleHtml, sectionKey) {
  const card = document.createElement("details");
  card.className = "config-step";
  if (sectionKey) card.dataset.section = sectionKey;
  const summary = document.createElement("summary");
  summary.innerHTML = `<span>${titleHtml}</span><span class="chev">▸</span>`;
  card.appendChild(summary);
  return card;
}

function renderConfigPanel(tab) {
  const host = $(`#config-${tab}`);
  host.innerHTML = "";
  if (tab === "suite") { renderSuiteConfigPanel(host); return; }
  const defs = state.steps[tab];
  let cardIdx = 0;
  defs.forEach((def) => {
    const params = state.meta[tab][def.key] || [];
    if (!params.length) return;
    const card = makeConfigCard(`${def.icon} ${def.title} — config`);
    card.open = cardIdx === 0;  // first card open, rest collapsed
    cardIdx++;
    params.forEach((p) => {
      const val = state.values[tab]?.[def.key]?.[p.id] ?? p.default;
      const row = document.createElement("div");
      row.className = "cfg-row";
      row.dataset.param = p.id;
      if (p.visible_if) {
        const cond = p.visible_if;
        row.classList.add("cond");
        row.dataset.depends = cond.param;
        row.dataset.equals = cond.equals;
      }
      let field;
      if (p.type === "select") {
        field = `<select data-pid="${p.id}">${p.options.map((o) =>
          `<option value="${esc(o)}" ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
      } else if (p.type === "textarea") {
        field = `<textarea data-pid="${p.id}">${esc(val)}</textarea>`;
      } else {
        field = `<input data-pid="${p.id}" type="${p.type === "int" ? "number" : p.type === "float" ? "number" : "text"}" step="${p.type === "float" ? "0.1" : "1"}" value="${esc(val)}">`;
      }
      row.innerHTML = `
        <span class="cfg-label">${esc(p.label)} <span class="help-dot" data-help="${esc(p.help)}">?</span></span>
        ${field}`;
      card.appendChild(row);
    });
    host.appendChild(card);
  });
  applyVisibility(tab);
  host.querySelectorAll("select").forEach((sel) => sel.addEventListener("change", () => {
    applyVisibility(tab);
    collectValues(tab);
  }));
  host.querySelectorAll("input, textarea").forEach((inp) => inp.addEventListener("change", () => collectValues(tab)));
}

function renderSuiteConfigPanel(host) {
  const defs = state.meta.suite;
  let cardIdx = 0;
  Object.keys(defs).forEach((section) => {
    const params = defs[section] || [];
    if (!params.length) return;
    const card = makeConfigCard(SUITE_SECTION_TITLES[section] || section, section);
    card.open = cardIdx === 0;
    cardIdx++;
    params.forEach((p) => {
      const val = state.values.suite?.[section]?.[p.id] ?? p.default;
      const row = document.createElement("div");
      row.className = "cfg-row";
      row.dataset.param = p.id;
      if (p.visible_if) {
        const cond = p.visible_if;
        row.classList.add("cond");
        row.dataset.depends = cond.param;
        row.dataset.equals = cond.equals;
      }
      let field;
      if (p.type === "select") {
        field = `<select data-pid="${p.id}">${p.options.map((o) =>
          `<option value="${esc(o)}" ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
      } else {
        field = `<input data-pid="${p.id}" type="${p.type === "int" ? "number" : p.type === "float" ? "number" : "text"}" step="${p.type === "float" ? "0.1" : "1"}" value="${esc(val)}">`;
      }
      row.innerHTML = `
        <span class="cfg-label">${esc(p.label)} <span class="help-dot" data-help="${esc(p.help)}">?</span></span>
        ${field}`;
      card.appendChild(row);
    });
    host.appendChild(card);
  });
  applyVisibility("suite");
  host.querySelectorAll("select").forEach((sel) => sel.addEventListener("change", () => {
    applyVisibility("suite");
    collectValues("suite");
  }));
  host.querySelectorAll("input, textarea").forEach((inp) => inp.addEventListener("change", () => collectValues("suite")));
}

function applyVisibility(tab) {
  const sel = (tab2, step, pid) => $(`#config-${tab2} .config-step [data-pid="${pid}"]`)?.closest(".cfg-row") || null;
  // chunk strategy drives char/semantic visibility via visible_if metadata
  $$(`#config-${tab} .cfg-row.cond`).forEach((row) => {
    const pid = row.querySelector("[data-pid]").dataset.pid;
    const param = state.meta[tab].flatMap?.(null) || [];
    // find the param meta for visible_if
    let visible = true;
    for (const [section, params] of Object.entries(state.meta[tab])) {
      const p = params.find((x) => x.id === pid && x.visible_if);
      if (p) {
        // suite cards carry their section name; other tabs use visible_if.step
        const depStep = row.closest(".config-step")?.dataset.section || p.visible_if.step;
        const depVal = getConfigValue(tab, depStep, p.visible_if.param);
        visible = depVal === p.visible_if.equals;
        break;
      }
    }
    row.classList.toggle("hidden", !visible);
  });
  sel; // noop
}

function getConfigValue(tab, step, pid) {
  const el = $(`#config-${tab} .config-step [data-pid="${pid}"]`);
  if (el) return el.value;
  const meta = state.meta?.[tab]?.[step]?.find((p) => p.id === pid);
  return meta ? (state.values[tab]?.[step]?.[pid] ?? meta.default) : undefined;
}

function collectValues(tab) {
  const vals = state.values[tab] || {};
  $$(`#config-${tab} .config-step`).forEach((card) => {
    const stepName = card.dataset.section || findStepForCard(tab, card);
    if (!stepName) return;
    vals[stepName] = vals[stepName] || {};
    card.querySelectorAll("[data-pid]").forEach((el) => {
      vals[stepName][el.dataset.pid] = el.type === "number" ? Number(el.value) : el.value;
    });
  });
  state.values[tab] = vals;
}

function findStepForCard(tab, cardEl) {
  const idx = Array.from(cardEl.parentElement.children).filter((c) => c.classList.contains("config-step")).indexOf(cardEl);
  const stepsWithParams = state.steps[tab].filter((s) => (state.meta[tab][s.key] || []).length);
  return stepsWithParams[idx]?.key;
}

async function persistConfig() {
  try {
    collectValues("ingest"); collectValues("query"); collectValues("eval"); collectValues("suite");
    await api("/api/config", { method: "POST", body: JSON.stringify(state.values) });
  } catch (e) { console.warn("persist config failed", e); }
}

/* ── ingestion flow ──────────────────────────────────────── */

function renderSelectedFiles() {
  const host = $("#selected-files");
  host.innerHTML = "";
  state.selectedFiles.forEach((f) => {
    const chip = document.createElement("span");
    chip.className = "file-chip";
    chip.innerHTML = `📄 ${esc(f.name || f)} <button title="Remove">✕</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.selectedFiles = state.selectedFiles.filter((x) => x !== f);
      renderSelectedFiles();
    });
    host.appendChild(chip);
  });
  $("#ingest-run").disabled = !state.selectedFiles.length;
}

async function openBrowse() {
  const modal = $("#browse-modal");
  modal.classList.remove("hidden");
  await browsePath("");
}

async function browsePath(path) {
  try {
    const data = await api(`/api/browse?path=${encodeURIComponent(path)}`);
    state.browse = data;
    $("#browse-path").textContent = `📁 ${data.path || "."}`;
    $("#browse-up").disabled = !data.parent;
    const list = $("#browse-list");
    list.innerHTML = "";
    data.dirs.forEach((d) => {
      const item = document.createElement("div");
      item.className = "browser-item";
      item.innerHTML = `<span class="icon">📁</span><span>${esc(d.name)}</span>`;
      item.addEventListener("click", () => browsePath(d.path));
      list.appendChild(item);
    });
    data.files.forEach((f) => {
      const item = document.createElement("div");
      item.className = "browser-item";
      item.innerHTML = `<input type="checkbox" data-path="${esc(f.path)}"><span class="icon">📄</span><span>${esc(f.name)}</span>
        <span class="fmeta">${f.words != null ? f.words + " words" : ""}</span>`;
      list.appendChild(item);
    });
  } catch (e) {
    toast(e.message, "error");
  }
}

function browseOk() {
  const checked = $$("#browse-list input[type=checkbox]:checked");
  checked.forEach((cb) => {
    const p = cb.dataset.path;
    if (!state.selectedFiles.some((f) => (f.path || f) === p)) {
      state.selectedFiles.push({ path: p, name: p.split("/").pop() });
    }
  });
  renderSelectedFiles();
  $("#browse-modal").classList.add("hidden");
}

/* ── run orchestration ───────────────────────────────────── */

async function runTab(tab) {
  const suiteMode = tab === "suite";
  const apiTab = suiteMode ? "suite" : tab;
  const btn = $(`#${tab === "ingest" ? "ingest" : tab === "eval" && !suiteMode ? "eval" : suiteMode ? "suite" : "query"}-run`);
  const btnLabel = btn.textContent;

  // If a suite run is already active, this click means STOP it.
  if (suiteMode && state.activeRunId) {
    btn.disabled = true;
    btn.textContent = "⏹ Stopping… (finishing current call)";
    try {
      await api("/api/suite/stop", { method: "POST", body: JSON.stringify({ run_id: state.activeRunId }) });
      toast("⏹ Stop requested — aborting after the current LLM call (≤ a few seconds)", "warn");
    } catch (e) {
      toast(e.message, "error");
      btn.disabled = false;
    }
    return;  // the running step loop will notice the cancel flag and return
  }

  btn.disabled = true;
  btn.textContent = "⏳ Running…";
  await persistConfig();
  try {
    const payload = tab === "ingest"
      ? { files: state.selectedFiles.map((f) => f.path || f), config: state.values.ingest }
      : suiteMode
        ? { config: state.values.suite }
        : tab === "eval"
          ? { config: state.values.eval }
          : { query: $("#query-input").value, config: state.values.query };
    const start = await api(`/api/${apiTab}/start`, { method: "POST", body: JSON.stringify(payload) });
    state.runs[suiteMode ? "suite" : tab] = { steps: start.steps, results: {} };
    state.activeRunId = start.run_id;
    state.runCancelled = false;
    if (tab === "eval" && !suiteMode) state.evalRunId = start.run_id;
    renderWorkflow(suiteMode ? "suite" : tab);
    if (suiteMode) {
      // running indicator on the run button: click again to STOP the run
      btn.disabled = false;
      btn.textContent = "⏹ Stop suite";
      btn.dataset.stopping = "0";
      btn.classList.add("stoppable");
      $("#diff-view").innerHTML = "";
    } else {
      renderEmptyDetail(tab);
    }

    for (let i = 0; i < start.steps.length; i++) {
      const key = start.steps[i].key;
      setNodeStatus(suiteMode ? "suite" : tab, key, "running");
      if (suiteMode && (key === "run_questions")) {
        startProgressPolling(start.run_id, "suite", key);
      } else if (suiteMode && (key === "compare" || key === "prepare" || key === "load_golden")) {
        // short steps: still show a live elapsed ticker
        startProgressPolling(start.run_id, "suite", key);
      }
      const res = await api(`/api/${apiTab}/step`, {
        method: "POST", body: JSON.stringify({ run_id: start.run_id, step_index: i }),
      });
      stopProgressPolling();
      const rtab = suiteMode ? "suite" : tab;
      // sync the client-side step record (status, duration, error) from the server
      const stored = state.runs[rtab].steps.find((s) => s.key === key);
      if (stored && res.step) {
        stored.status = res.step.status;
        stored.duration_ms = res.step.duration_ms;
        stored.error = res.step.error;
      }
      state.runs[rtab].results[key] = res.result;
      setNodeStatus(rtab, key, res.status === "completed" ? "completed" : res.status === "cancelled" ? "cancelled" : "error");
      renderWorkflowDurations(rtab);
      if (res.status === "error") {
        toast(`Step '${key}' failed: ${res.result.error || "unknown"}`, "error");
        selectNode(rtab, key);
        break;
      }
      if (res.status === "cancelled") {
        toast(`⏹ Run stopped — step '${key}' cancelled`, "warn");
        btn.disabled = false;
        btn.textContent = btnLabel;
        state.activeRunId = null;
        break;
      }
    }
    // self-closing success banner once every step of the pipeline is done
    const rtab = suiteMode ? "suite" : tab;
    if (state.runs[rtab].steps.every((s) => s.status === "completed")) {
      if (tab === "ingest") {
        const total = state.runs[rtab].results?.store?.collection_total;
        toast(total != null
          ? `✅ Ingestion completed successfully — ${total} chunks in the collection`
          : "✅ Ingestion completed successfully", "success");
      } else if (suiteMode) {
        const diffs = state.runs.suite.results?.compare?.diffs || [];
        const worst = diffs.some((d) => d.verdict === "FAIL") ? "🔴"
          : diffs.some((d) => d.verdict === "WARN") ? "🟡" : diffs.length ? "🟢" : "";
        toast(`${worst || "✅"} Suite completed — ${diffs.length ? "gate verdict " + diffs.map((d) => d.verdict).join("/") : "snapshot(s) written"}`, "success");
        await loadSnapshots();
        openEvalPanel("suite-panel");
        selectNode("suite", "compare");
      } else if (tab === "eval") {
        const awaiting = state.runs.eval.results?.review?.awaiting;
        const frozen = state.runs.eval.results?.review?.frozen;
        toast(awaiting > 0
          ? `✅ Generation completed — ${awaiting} candidates awaiting review`
          : `✅ Golden set frozen — ${frozen} items`, "success");
        if (awaiting > 0) {
          selectNode("eval", "review");
          $("#eval-freeze").disabled = false;
        } else {
          await loadGolden();
        }
      } else {
        toast("✅ Query completed successfully", "success");
      }
    }
    refreshCollectionBadge();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    stopProgressPolling();
    btn.disabled = false;
    btn.textContent = btnLabel;
    btn.classList.remove("stoppable");
    state.activeRunId = null;
    if (tab === "ingest") $("#ingest-run").disabled = !state.selectedFiles.length;
  }
}

function renderWorkflowDurations(tab) {
  const run = state.runs[tab];
  if (!run) return;
  run.steps.forEach((s) => {
    const node = $(`#workflow-${tab}`).querySelector(`.node[data-key="${s.key}"]`);
    if (!node) return;
    let d = node.querySelector(".node-duration");
    if (s.duration_ms != null) {
      if (!d) {
        d = document.createElement("span");
        d.className = "node-duration";
        const badge = node.querySelector(".node-status");
        node.insertBefore(d, badge);
      }
      d.textContent = `${s.duration_ms} ms`;
    }
  });
}

/* ── detail renderers ────────────────────────────────────── */

function renderEmptyDetail(tab) {
  const host = $(`#detail-${tab}`);
  host.style.display = "";  // empty hint is still useful after a reset
  host.innerHTML = `<div class="detail-empty">Click a workflow node to inspect its data.</div>`;
  // collapse the hint to a thin strip so it doesn't eat the column
  host.classList.add("empty-hint");
}

function renderDetail(tab, key, step, result) {
  const host = $(`#detail-${tab}`);
  if (!step) return;
  host.style.display = "";  // reveal the detail panel (hidden while empty)
  host.classList.remove("empty-hint");
  const dur = step.duration_ms != null ? ` · ${step.duration_ms} ms` : "";
  let body = "";

  if (step.status === "error") {
    body = `<div class="error-box">${esc(step.error || "Unknown error")}</div>`;
  } else if (result) {
    body = tab === "ingest" ? renderIngestDetail(key, result)
      : tab === "eval" ? renderEvalDetail(key, result)
      : renderQueryDetail(key, result);
  } else {
    body = `<div class="detail-empty">This step has not run yet. Press ▶ Run to execute the workflow.</div>`;
  }

  host.innerHTML = `
    <h3 class="detail-title">${step.icon} ${esc(step.title)}</h3>
    <p class="detail-sub">status: ${esc(step.status)}${dur}</p>
    ${body}`;
}

function kv(items) {
  return `<dl class="kv">${items.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}

function dataTable(rows, cols) {
  if (!rows?.length) return `<p class="detail-sub">No rows.</p>`;
  const tip = (c) => {
    const t = c.tip || tipFor(c.label);
    return t ? ` title="${esc(t)}"` : "";
  };
  return `<table class="data"><thead><tr>${cols.map((c) => `<th${tip(c)}>${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r, i) => `<tr>${cols.map((c) => {
      const cls = c.cls ? c.cls(r, i) : "";
      return `<td${cls ? ` class="${esc(cls)}"` : ""}>${esc(c.get(r, i))}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table>`;
}

function chunkCards(chunks) {
  return chunks.map((c) => `
    <div class="chunk-card">
      <div class="meta"><span>#${c.chunk_index}</span><span>${esc(c.doc_title)}</span>${c.section_title ? `<span>${esc(c.section_title)}</span>` : ""}<span>${c.words} words</span>${c.has_code_block ? "<span>⌨️ code</span>" : ""}${c.has_table ? "<span>▦ table</span>" : ""}</div>
      ${metaTags(c.metadata)}
      <pre>${esc(c.preview)}</pre>
    </div>`).join("");
}

/* Chips for the metadata fields that would be stored in ChromaDB. */
function metaTags(md) {
  if (!md || !Object.keys(md).length) return "";
  const chips = Object.entries(md).map(([k, v]) =>
    `<span class="meta-tag"><b>${esc(k)}</b>=${esc(v)}</span>`).join("");
  return `<div class="meta-tags"><span class="meta-label">metadata</span>${chips}</div>`;
}

/* Full metadata as a key/value list (for the "what's stored" views). */
function metaKv(md) {
  return kv(Object.entries(md || {}).map(([k, v]) => [k, v]));
}

/* One "what ChromaDB stores for this chunk" row: id + text + metadata + vector. */
function storedChunkCard(sc, dims) {
  return `
    <div class="chunk-card stored">
      <div class="stored-grid">
        <div class="stored-cell">
          <div class="stored-label">ID</div>
          <div class="stored-val mono">${esc(sc.id)}</div>
        </div>
        <div class="stored-cell">
          <div class="stored-label">Raw text (first 300 chars)</div>
          <pre class="stored-val">${esc(sc.text)}</pre>
        </div>
        <div class="stored-cell">
          <div class="stored-label">Metadata (shown for citations)</div>
          <div class="stored-val">${metaKv(sc.metadata)}</div>
        </div>
        <div class="stored-cell">
          <div class="stored-label">Embedding — ${dims} dims, first 8 values</div>
          <div class="stored-val vec-preview">[${sc.embedding_preview.map((v) => v.toFixed(5)).join(", ")}, …]</div>
        </div>
      </div>
    </div>`;
}

function renderIngestDetail(key, r) {
  if (key === "load") {
    return `<div class="detail-section"><h4>Files loaded</h4>${dataTable(r.files, [
      { label: "File", get: (f) => f.title },
      { label: "Chars", get: (f) => f.chars },
      { label: "Words", get: (f) => f.words },
    ])}</div>`;
  }
  if (key === "chunk") {
    return `
      <div class="detail-section"><h4>Strategy</h4>${kv([["strategy", r.strategy], ["params", JSON.stringify(r.params)]])}</div>
      <div class="detail-section"><h4>Per document</h4>${dataTable(r.per_doc, [
        { label: "Document", get: (d) => d.title },
        { label: "Chunks", get: (d) => d.chunk_count },
        { label: "Broken code", get: (d) => d.broken_code },
        { label: "Broken table", get: (d) => d.broken_table },
      ])}</div>
      <div class="detail-section"><h4>Chunk previews (first ${r.chunks.length})</h4>${chunkCards(r.chunks)}</div>`;
  }
  if (key === "embed") {
    return `<div class="detail-section"><h4>Embedding summary</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.chunks_embedded}</div><div class="k">chunks</div></div>
        <div class="stat-box"><div class="v">${r.dimensions}</div><div class="k">dimensions</div></div>
      </div>
      ${kv([["model", r.model], ["endpoint", r.endpoint]])}</div>`;
  }
  if (key === "store") {
    return `<div class="detail-section"><h4>Store summary</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.upserted}</div><div class="k">upserted</div></div>
        <div class="stat-box"><div class="v">${r.deleted_stale}</div><div class="k">stale deleted</div></div>
        <div class="stat-box"><div class="v">${r.collection_total}</div><div class="k">collection total</div></div>
      </div>
      ${kv([["chroma_path", r.chroma_path], ["collection", r.collection_name]])}</div>
      <div class="detail-section"><h4>What ChromaDB stores per chunk (first ${r.stored_chunks?.length || 0} of ${r.collection_total})</h4>
      <p class="detail-sub">Every chunk is persisted as: <b>id</b> + <b>raw text</b> + <b>embedding vector</b> + <b>metadata</b>. Citations in the answer are looked up from this metadata.</p>
      ${(r.stored_chunks || []).map((sc) => storedChunkCard(sc, sc.embedding_dimensions)).join("")}</div>`;
  }
  return "";
}

function renderQueryDetail(key, r) {
  if (key === "embed_query") {
    return `<div class="detail-section"><h4>Query</h4><div class="answer-box">${esc(r.query)}</div></div>
      <div class="detail-section"><h4>Embedding</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.dimensions}</div><div class="k">dimensions</div></div>
        <div class="stat-box"><div class="v">${r.norm}</div><div class="k">L2 norm</div></div>
      </div>
      ${kv([["model", r.model], ["endpoint", r.endpoint]])}
      <h4 style="margin-top:12px">First 8 values</h4>
      <div class="vec-preview">[${r.first_values.map((v) => v.toFixed(4)).join(", ")}, …]</div></div>`;
  }
  if (key === "retrieve") {
    return `
      <div class="detail-section"><h4>Retriever</h4>${kv([["retriever", r.retriever], ["top_k", r.top_k], ["corpus size", r.corpus_size]])}</div>
      ${r.bm25?.length ? `<div class="detail-section"><h4>BM25 keyword ranking</h4>${dataTable(r.bm25, [
        { label: "Doc", get: (x) => x.doc_title },
        { label: "Section", get: (x) => x.section_title },
        { label: "Score", get: (x) => x.score },
        { label: "Preview", get: (x) => x.preview },
      ])}</div>` : ""}
      ${r.vector?.length ? `<div class="detail-section"><h4>Vector similarity ranking</h4>${dataTable(r.vector, [
        { label: "Doc", get: (x) => x.doc_title },
        { label: "Section", get: (x) => x.section_title },
        { label: r.retriever === "semantic" ? "Distance" : "Distance", get: (x) => x.score },
        { label: "Preview", get: (x) => x.preview },
      ])}
      <div class="detail-section"><h4>Stored metadata of these chunks</h4>
        ${r.vector.map((x) => `
          <div class="chunk-card">
            <div class="meta"><span>${esc(x.doc_title)}</span><span>${esc(x.section_title)}</span><span>${esc(x.score)} ${esc(x.score_key || "")}</span></div>
            ${metaTags(x.metadata)}
          </div>`).join("")}
      </div>` : ""}`;
  }
  if (key === "rerank") {
    return `<div class="detail-section"><h4>Reciprocal Rank Fusion — final order</h4>
      ${dataTable(r.fused, [
        { label: "Rank", get: (x, i) => i + 1 },
        { label: "Doc", get: (x) => x.doc_title },
        { label: "Section", get: (x) => x.section_title },
        { label: "RRF", get: (x) => x.score },
        { label: "BM25 #", get: (x) => x.bm25_rank ?? "–" },
        { label: "Vec #", get: (x) => x.vector_rank ?? "–" },
      ])}</div>`;
  }
  if (key === "augment") {
    return `<div class="detail-section"><h4>System prompt</h4><pre class="prompt-pre">${esc(r.system)}</pre></div>
      <div class="detail-section"><h4>User prompt (chunks ${r.chunks_used})</h4><pre class="prompt-pre">${esc(r.user)}</pre></div>`;
  }
  if (key === "generate") {
    const textHtml = esc(r.text).replace(/\[Source: .+?, Section: .+?\]/g, (m) => `<span class="citation-chip">${esc(m)}</span>`);
    return `<div class="detail-section"><h4>Answer <span style="text-transform:none;color:var(--muted)">· model ${esc(r.model)}</span></h4>
      <div class="answer-box">${textHtml}</div></div>
      ${r.citations?.length ? `<div class="detail-section"><h4>Citations (${r.citations.length}) — parsed from the answer text</h4>${r.citations.map((c) => `<span class="citation-chip">${esc(c)}</span>`).join("")}</div>` : ""}
      ${r.sources?.length ? `<div class="detail-section"><h4>Source chunks — citations resolve to this metadata</h4>
        ${r.sources.map((s) => `
          <div class="chunk-card">
            <div class="meta"><span>#${s.rank}</span><span>${esc(s.doc_title)}</span><span>${esc(s.section_title)}</span><span>chunk ${esc(s.chunk_index)}</span></div>
            ${metaTags(s.metadata)}
            <pre>${esc(s.preview)}…</pre>
          </div>`).join("")}</div>` : ""}`;
  }
  return "";
}

/* ── evaluation: golden set (Phase 0, run-based) ────────── */

function renderEvalDetail(key, r) {
  if (key === "load_sections") {
    return `<div class="detail-section"><h4>Sections from vector store</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.total_sections}</div><div class="k">total sections</div></div>
        <div class="stat-box"><div class="v">${r.used}</div><div class="k">used (max)</div></div>
      </div></div>
      <div class="detail-section"><h4>Section list</h4>${dataTable(r.sections, [
        { label: "Document", get: (s) => s.doc_title },
        { label: "Section", get: (s) => s.section_title },
        { label: "Chars", get: (s) => s.chars },
      ])}</div>`;
  }
  if (key === "generate_pairs") {
    return `<div class="detail-section"><h4>Generation</h4>${kv([
      ["candidates", r.candidates?.length || 0],
      ["elapsed", r.elapsed_ms + " ms"],
    ])}</div>
    <div class="detail-section"><h4>Candidate Q/A pairs (${r.candidates?.length || 0})</h4>
    ${(r.candidates || []).map((c) => `
      <div class="chunk-card">
        <div class="meta"><span class="gkind">${esc(c.kind)}</span><span>${esc(c.doc_title)}</span><span>${esc(c.section_title)}</span></div>
        <div class="gq"><b>Q:</b> ${esc(c.question)}</div>
        <div class="ga"><b>A:</b> ${esc(c.reference_answer)}</div>
      </div>`).join("")}</div>`;
  }
  if (key === "filter") {
    return `<div class="detail-section"><h4>Filter summary</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.generated}</div><div class="k">generated</div></div>
        <div class="stat-box"><div class="v">${r.closed_book_rejected ?? 0}</div><div class="k">closed-book rej.</div></div>
        <div class="stat-box"><div class="v">${r.grounding_rejected ?? 0}</div><div class="k">grounding rej.</div></div>
        <div class="stat-box"><div class="v">${r.deduped ?? 0}</div><div class="k">deduped</div></div>
        <div class="stat-box"><div class="v">${r.kept}</div><div class="k">kept</div></div>
      </div></div>
      ${r.rejected?.length ? `<div class="detail-section"><h4>Rejected items</h4>${dataTable(r.rejected, [
        { label: "Question", get: (x) => x.question },
        { label: "Reason", get: (x) => x.reason },
      ])}</div>` : ""}`;
  }
  if (key === "review") {
    if (r.awaiting > 0) {
      return `<div class="detail-section"><h4>Awaiting review — ${r.awaiting} candidates</h4>
        <p class="detail-sub">Uncheck any bad pairs, then press <b>✔ Freeze checked items</b>. Previously frozen: ${r.previous_count}.</p>
        ${(r.candidates || []).map((c) => `
          <div class="chunk-card golden-item">
            <div class="meta">
              <span><input type="checkbox" class="golden-ck" data-gid="${esc(c.id)}" checked> keep</span>
              <span class="gkind">${esc(c.kind)}</span>
              <span>${esc(c.doc_title)}</span>
              <span>${esc(c.section_title)}</span>
            </div>
            <div class="gq"><b>Q:</b> ${esc(c.question)}</div>
            <div class="ga"><b>A:</b> ${esc(c.reference_answer)}</div>
          </div>`).join("")}</div>`;
    }
    return `<div class="detail-section"><h4>Frozen</h4>${kv([
      ["frozen", r.frozen], ["path", r.frozen_path], ["previous count", r.previous_count],
    ])}</div><div class="detail-section"><h4>Frozen items</h4>
    ${(r.candidates || []).map((c) => `
      <div class="chunk-card">
        <div class="meta"><span class="gkind">${esc(c.kind)}</span><span>${esc(c.section_title)}</span></div>
        <div class="gq"><b>Q:</b> ${esc(c.question)}</div>
      </div>`).join("")}</div>`;
  }
  return "";
}

async function freezeGolden() {
  const run = state.runs.eval;
  const ids = new Set($$("#detail-eval .golden-ck:checked").map((ck) => ck.dataset.gid));
  let approved = [];
  if (ids.size && run?.results?.review?.candidates) {
    approved = run.results.review.candidates.filter((c) => ids.has(c.id));
  } else if (run?.results?.review) {
    // nothing checked -> fall back to run_id based pending_freeze on server (freeze all kept)
    approved = [];
  }
  try {
    const res = await api("/api/eval/golden/freeze", {
      method: "POST", body: JSON.stringify({ approved, run_id: state.evalRunId }),
    });
    toast(`Golden set frozen: ${res.frozen} items`, "success");
    $("#eval-freeze").disabled = true;
    await loadGolden();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadGolden() {
  try {
    const data = await api("/api/eval/golden");
    const panel = $("#golden-panel");
    const host = $("#golden-list");
    const count = data.frozen?.length || 0;
    $("#golden-count").textContent = count;
    if (count) {
      panel.style.display = "";
      host.innerHTML = `<p class="detail-sub" style="margin-bottom:10px">${esc(data.path)}</p>
      ${data.frozen.map((c) => `
        <div class="chunk-card">
          <div class="meta"><span class="gkind">${esc(c.kind)}</span><span>${esc((c.expected_sections || []).map((s) => s.section_title).join(" + ") || "(negative case)")}</span><span>${esc(c.generated_at || "")}</span></div>
          <div class="gq"><b>Q:</b> ${esc(c.question)}</div>
          <div class="ga"><b>A:</b> ${esc(c.reference_answer)}</div>
        </div>`).join("")}`;
    } else {
      panel.style.display = "none";
    }
  } catch {}
}

/* ── evaluation: regression suite (Phase 1) ─────────────── */

const AGG_LABELS = {
  recall_at_k: ["Recall@k", "higher"],
  recall_section: ["Recall (section q)", "higher"],
  recall_multihop: ["Recall (multi-hop)", "higher"],
  first_relevant_rank: ["Avg first rank", "lower"],
  citation_coverage: ["Citation coverage", "higher"],
  must_term_coverage: ["Must-term coverage", "higher"],
  refusal_accuracy: ["Refusal accuracy", "higher"],
  mean_total_ms: ["Mean latency (ms)", "lower"],
  p95_total_ms: ["p95 latency (ms)", "lower"],
};

/* Hover help for every metric column: what it is + expected range.
   Applied automatically wherever a dataTable column label matches. */
const METRIC_HELP = {
  "Recall@k": "Fraction of questions where a correct chunk was retrieved in the top-k. Range 0–1; 1.0 = every question found its source. <1 suggests retrieval gaps.",
  "Recall (section q)": "Recall@k computed only on single-section questions. Range 0–1.",
  "Recall (multi-hop)": "Recall@k computed only on multi-hop questions (need 2+ docs). Range 0–1; usually lower than section recall.",
  "Avg rank": "Average position of the FIRST correct chunk in the retrieved list. Range 1–k; 1.0 = always first. Lower is better; >2 means relevant chunks arrive late.",
  "Citation coverage": "Fraction of [Source: ...] citations in answers that match actually-retrieved chunks. Range 0–1; 1.0 = every citation is real. Low values may flag hallucinated citations — but headerless chunking (character/semantic) can also under-match section labels.",
  "Must-term coverage": "Fraction of significant terms from the reference answer that appear in the generated answer. Range 0–1; higher = more complete answers. This snapshot truncates answers at 400 chars, which depresses the score.",
  "Refusal accuracy": "Fraction of negative (unanswerable) questions where the pipeline correctly refused instead of hallucinating. Range 0–1; 1.0 = refuses all negatives.",
  "Mean latency (ms)": "Average end-to-end time per question (retrieve + generate). Watch relative change: +25% = warn, +60% = fail.",
  "p95 latency (ms)": "95th-percentile per-question time — the slow tail. +25% = warn, +60% = fail.",
  Faithfulness: "Ragas LLM-judge: share of claims in the answer that are supported by the retrieved chunks. Range 0–1; ≥0.6 is good, <0.3 means many unsupported claims. Slightly depressed here by 400-char answer truncation.",
  "Ctx precision": "Ragas: are the RELEVANT chunks ranked high in the retrieved list (noise above pushes it down). Range 0–1; higher = cleaner retrieval ordering.",
  "Ctx recall": "Ragas: does the retrieved context cover everything the reference answer needs. Range 0–1; low = retrieval missed source material.",
  "Answer relevancy": "Ragas: how on-topic the answer is for the question (embedding similarity of generated follow-up questions). Range 0–1.",
  "Recall@k": "Fraction of questions where a correct chunk was retrieved in the top-k. Range 0–1; 1.0 = every question found its source.",
  Rank: "Position of the first correct chunk in the retrieved list (1 = top). Lower is better.",
  "Cite cov.": "Fraction of [Source: ...] citations that match retrieved chunks. Range 0–1.",
  ms: "Wall-clock time for this question (retrieve + generate), milliseconds.",
  "Q-id": "Golden-set question ID (from eval/golden_set.jsonl).",
  Kind: "Question type: section (single doc section), multi-hop (needs 2+ docs), negative (unanswerable — should refuse).",
  Question: "The question text asked to the pipeline.",
  Snapshot: "Snapshot ID (file eval/snapshots/<id>.json).",
  When: "When the run finished (UTC timestamp).",
  Strategy: "Chunking strategy used: structural (H2/H3 headers), character (fixed windows), semantic (embedding-based topic splits). current-corpus = whatever is ingested right now.",
  Retriever: "Search method: hybrid (BM25 + vector, fused via RRF) or semantic (vector-only).",
  Label: "Optional name given to the run.",
  scored: "Questions judged by the ragas judge (negative/empty rows skipped).",
  skipped: "Questions NOT judged (negative cases, empty answers, no chunks).",
  "judge time": "Total time spent ragas-judging this snapshot.",
  failed: "⚠️ = ALL metric calls failed for this question (judge JSON/model hiccup).",
};

/* Append a compact "range/meaning" hint under hover for metric-ish labels. */
function tipFor(label) {
  const h = METRIC_HELP[label];
  if (!h) return undefined;
  return h.replace(/\s+/g, " ").slice(0, 220);
}

/* Snapshot created_at (UTC ISO) → readable local "MM-DD HH:MM". */
function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ── metric health coloring ───────────────────────────────
   green = within target, amber = borderline, red = poor.
   Thresholds per metric; latency judged on absolute ms. */
const HEALTH_BANDS = {
  faithfulness:        { good: 0.6,  mid: 0.3 },   // <0.3 poor, 0.3-0.6 borderline, ≥0.6 good
  context_precision:   { good: 0.6,  mid: 0.3 },
  context_recall:      { good: 0.6,  mid: 0.3 },
  answer_relevancy:    { good: 0.6,  mid: 0.3 },
  recall_at_k:         { good: 0.9,  mid: 0.7 },
  recall_section:      { good: 0.9,  mid: 0.7 },
  recall_multihop:     { good: 0.8,  mid: 0.6 },
  citation_coverage:   { good: 0.8,  mid: 0.4 },
  must_term_coverage:  { good: 0.7,  mid: 0.5 },
  refusal_accuracy:    { good: 0.9,  mid: 0.7 },
  first_relevant_rank: { good: 1.3,  mid: 2.0, lower: true },  // ≤1.3 good, ≤2.0 borderline, else poor
};

/** "good" | "mid" | "bad" | null (unscored) for a metric value. */
function healthOf(metric, v) {
  if (v == null || isNaN(Number(v))) return null;
  const b = HEALTH_BANDS[metric];
  if (!b) return null;
  const n = Number(v);
  if (b.lower) return n <= b.good ? "good" : n <= b.mid ? "mid" : "bad";
  return n >= b.good ? "good" : n >= b.mid ? "mid" : "bad";
}

/* Latency bands (absolute ms): ≤4000 good, ≤8000 borderline, else poor. */
function healthOfLatency(ms) {
  if (ms == null || isNaN(Number(ms))) return null;
  return ms <= 4000 ? "good" : ms <= 8000 ? "mid" : "bad";
}

/** Table-cell class for a metric value: "score-good" | "score-mid" | "score-bad" | "". */
function clsFor(metric, v) {
  const h = healthOf(metric, v);
  return h ? `score-${h}` : "";
}

function metricCell(r) {
  const cls = r.verdict === "improve" ? "up" : r.verdict === "regress" ? "down" : "flat";
  const arrow = r.verdict === "improve" ? " ▲" : r.verdict === "regress" ? " ▼" : "";
  const cur = r.metric.includes("_ms") ? r.current : r.current;
  const delta = r.delta == null ? "–"
    : r.metric.includes("_ms") ? `${r.delta}`
    : (Math.abs(r.delta) < 0.005 ? "=" : `${r.delta > 0 ? "+" : ""}${r.delta}`);
  return `<td class="${cls}">${esc(String(cur))} <span class="mini-label">${esc(delta)}${arrow}</span></td>`;
}

function verdictBanner(v, extra = "") {
  const map = { PASS: ["pass", "🟢 PASS — no meaningful regression"],
                WARN: ["warn", "🟡 WARN — regression above 0.05 on some metrics"],
                FAIL: ["fail", "🔴 FAIL — regression above 0.15"] };
  const [cls, label] = map[v] || ["pass", v];
  return `<div class="verdict-banner ${cls}"><b>${esc(label)}</b>${extra ? " — " + esc(extra) : ""}</div>`;
}

function renderSuiteDetail(key, step, r) {
  if (step?.status === "error") {
    return `<div class="detail-section"><h4>${esc(step.title)}</h4><div class="error-box">${esc(step.error || "Unknown error")}</div></div>`;
  }
  if (!r) {
    return `<div class="detail-section"><h4>${esc(step?.title || key)}</h4><p class="detail-sub">This step has not run yet. Press ▶ Run evaluation suite.</p></div>`;
  }
  if (key === "load_golden") {
    return `<div class="detail-section"><h4>Golden set loaded</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.count}</div><div class="k">questions</div></div>
        <div class="stat-box"><div class="v">${r.sections_covered}</div><div class="k">sections covered</div></div>
        ${Object.entries(r.by_kind || {}).map(([k, v]) => `<div class="stat-box"><div class="v">${v}</div><div class="k">${esc(k)}</div></div>`).join("")}
      </div>
      ${kv([["file", r.path]])}</div>
      <div class="detail-section"><h4>Section coverage</h4>${dataTable(r.coverage?.map(([s, n]) => ({ s, n })), [
        { label: "Expected section", get: (x) => x.s },
        { label: "Questions", get: (x) => x.n },
      ])}</div>`;
  }
  if (key === "prepare") {
    return `<div class="detail-section"><h4>Corpus + plan</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${r.corpus_size}</div><div class="k">chunks in corpus</div></div>
        <div class="stat-box"><div class="v">${esc(r.corpus_strategy)}</div><div class="k">corpus strategy</div></div>
      </div>
      ${kv([["mode", r.mode]])}
      ${r.strategies ? kv([["legs", r.strategies.join(" → ")]]) : ""}
      ${r.warning ? `<div class="warn-box">⚠️ ${esc(r.warning)}</div>` : ""}
      ${r.missing_expected_sections ? `<p class="detail-sub">${r.missing_expected_sections} items lack expected_sections.</p>` : ""}</div>`;
  }
  if (key === "run_questions") {
    return `<div class="detail-section"><h4>Leg ${r.leg_index}/${r.legs_total}: ${esc(r.leg)} (${esc(r.strategy)})</h4>
      <div class="embed-stats">
        <div class="stat-box"><div class="v">${esc(r.snapshot_id)}</div><div class="k">snapshot id</div></div>
        <div class="stat-box"><div class="v">${r.elapsed_ms >= 60000 ? (r.elapsed_ms / 60000).toFixed(1) + " min" : Math.round(r.elapsed_ms / 1000) + " s"}</div><div class="k">elapsed</div></div>
        <div class="stat-box"><div class="v">${esc(r.corpus_strategy)}</div><div class="k">corpus strategy</div></div>
      </div></div>
      <div class="detail-section"><h4>Aggregate</h4>${kv(Object.entries(r.aggregate || {}).map(([k, v]) => [AGG_LABELS[k]?.[0] || k, v]))}</div>
      ${renderRagasSection(r.ragas)}`;
  }
  if (key === "compare") {
    return renderCompare(r);
  }
  return "";
}

function renderCompare(r) {
  const rows = (r.snapshots || []).map((s) => ({
    id: s.snapshot_id, strategy: s.strategy, corpus: s.corpus_size,
    recall: s.aggregate?.recall_at_k, rank: s.aggregate?.first_relevant_rank,
    cit: s.aggregate?.citation_coverage, ms: s.aggregate?.mean_total_ms,
    faith: s.ragas?.aggregate?.faithfulness, cprec: s.ragas?.aggregate?.context_precision,
  }));
  return `
    <div class="detail-section">
      <span class="baseline-chip ${r.has_baseline ? "" : "none"}" id="baseline-chip">${r.has_baseline ? `📌 baseline: ${esc(r.baseline_id)}` : "📌 no baseline set — diffs compare against this run's first snapshot"}</span>
      ${(r.diffs || []).map((d) => suiteDiffBlock(d)).join("")}
      ${r.cross_leg?.length ? `<h4>Cross-leg comparison (vs first leg)</h4>${r.cross_leg.map((d) => suiteDiffBlock(d)).join("")}` : ""}
    </div>
    <div class="detail-section"><h4>Snapshots written this run</h4>${dataTable(rows, [
      { label: "Snapshot", get: (x) => x.id },
      { label: "Strategy", get: (x) => x.strategy },
      { label: "Corpus", get: (x) => x.corpus },
      { label: "Recall@k", get: (x) => x.recall ?? "–", cls: (x) => clsFor("recall_at_k", x.recall) },
      { label: "Avg rank", get: (x) => x.rank ?? "–", cls: (x) => clsFor("first_relevant_rank", x.rank) },
      { label: "Citation cov.", get: (x) => x.cit ?? "–", cls: (x) => clsFor("citation_coverage", x.cit) },
      { label: "Faithfulness", get: (x) => x.faith ?? "–", cls: (x) => clsFor("faithfulness", x.faith) },
      { label: "Ctx precision", get: (x) => x.cprec ?? "–", cls: (x) => clsFor("context_precision", x.cprec) },
      { label: "Mean ms", get: (x) => x.ms, cls: (x) => { const h = healthOfLatency(x.ms); return h ? `score-${h}` : ""; } },
    ])}</div>
    <div class="detail-section"><h4>Actions</h4>
      <p class="detail-sub">Use the snapshot list below to set a baseline, open or delete snapshots.</p>
    </div>`;
}

/* ── ragas (Phase 2) render helpers ─────────────────────── */

const RAGAS_LABELS = {
  faithfulness: "Faithfulness",
  context_precision: "Ctx precision",
  context_recall: "Ctx recall",
  answer_relevancy: "Answer relevancy",
};

function ragasMetricCellV(row, metric) {
  const v = row[metric];
  return v == null ? "–" : String(v);
}

function renderRagasSection(rblock) {
  if (!rblock) return "";
  if (rblock.error) {
    return `<div class="detail-section"><h4>Ragas (LLM judge)</h4><div class="warn-box">⚠️ Ragas did not run: ${esc(rblock.error)}</div></div>`;
  }
  const agg = rblock.aggregate || {};
  const errs = rblock.errors || [];
  const healthCls = (m) => {
    const h = healthOf(m, agg[m]);
    return h ? ` v-${h}` : "";
  };
  return `<div class="detail-section"><h4>Ragas (LLM judge · ${esc(rblock.judge_model || "?")})</h4>
    <div class="embed-stats">
      ${(rblock.metrics || []).map((m) => `<div class="stat-box${healthCls(m)}"><div class="v">${agg[m] == null ? "–" : esc(String(agg[m]))}</div><div class="k">${esc(RAGAS_LABELS[m] || m)}</div></div>`).join("")}
      <div class="stat-box"><div class="v">${rblock.n_scored ?? 0}</div><div class="k">scored</div></div>
      ${rblock.n_skipped ? `<div class="stat-box"><div class="v">${rblock.n_skipped}</div><div class="k">skipped</div></div>` : ""}
      <div class="stat-box"><div class="v">${rblock.elapsed_ms >= 60000 ? (rblock.elapsed_ms / 60000).toFixed(1) + " min" : Math.round((rblock.elapsed_ms || 0) / 1000) + " s"}</div><div class="k">judge time</div></div>
    </div>
    ${(rblock.per_question || []).length ? dataTable(rblock.per_question, [
      { label: "Q-id", get: (x) => x.id },
      ...((rblock.metrics || []).map((m) => ({ label: RAGAS_LABELS[m] || m, get: (x) => ragasMetricCellV(x, m), cls: (x) => clsFor(m, x[m]) }))),
      { label: "failed", get: (x) => x.failed ? "⚠️" : "" },
    ]) : ""}
    ${errs.length ? `<p class="detail-sub">⚠️ ${errs.map((e) => esc(e)).join(" · ")}</p>` : ""}
  </div>`;
}

/** Judge notes for the snapshot detail view. */
function ragasDetailRows(snap) {
  const rblock = snap?.ragas;
  if (!rblock || rblock.error) return "";
  const errs = rblock.errors || [];
  // Data-quality notes, not just API errors: failed rows + all-zero scores.
  const perq = rblock.per_question || [];
  const failedIds = perq.filter((q) => q.failed).map((q) => q.id);
  const metrics = rblock.metrics || [];
  const zeroIds = perq
    .filter((q) => !q.failed && metrics.every((m) => (q[m] ?? null) === 0))
    .map((q) => q.id);
  const lines = [];
  errs.forEach((e) => lines.push(`⚠️ ${e}`));
  if (failedIds.length) lines.push(`⚠️ ${failedIds.length} question(s) failed ALL metric calls (judge hiccup): ${failedIds.join(", ")}`);
  if (zeroIds.length) lines.push(`ℹ️ ${zeroIds.length} question(s) scored 0 on every metric — the judge found no supported claims / no relevant context (low-quality answers or retrieval miss): ${zeroIds.join(", ")}`);
  if (!lines.length) lines.push("All judged questions scored cleanly (no failures, no all-zero rows).");
  return `<div class="detail-section"><h4>Ragas judge notes</h4>
    ${lines.map((e) => `<p class="detail-sub">${esc(e)}</p>`).join("")}
  </div>`;
}

/** Open a collapsible eval panel (golden-panel / suite-panel) if closed. */
function openEvalPanel(panelId) {
  const panel = $(`#${panelId}`);
  if (panel && panel.style.display !== "none") panel.open = true;
}

function suiteDiffBlock(d) {
  return `
    <h4>${esc(d.strategy || "run")} vs ${esc(d.baseline_id || "(this run's first snapshot)")} — ${d.icon} ${esc(d.verdict)}</h4>
    ${verdictBanner(d.verdict, d.worst_metric ? `worst: ${d.worst_metric} (−${d.worst_drop})` : "")}
    <table class="data"><thead><tr><th>Metric</th><th>Baseline</th><th>Current</th><th>Δ</th></tr></thead><tbody>
      ${(d.metrics || []).map((row) => `<tr><td>${esc(AGG_LABELS[row.metric]?.[0] || row.metric)}</td>
        <td>${row.baseline ?? "–"}</td>${metricCell(row)}</tr>`).join("")}
    </tbody></table>
    ${(d.regressed_ids || []).length ? `<p class="detail-sub"><b>Regressed questions:</b> ${d.regressed_ids.map((q) => esc(q.id) + (q.rank ? ` (rank ${esc(q.rank)})` : "")).join(", ")}</p>` : ""}
    ${(d.regressed_ids || []).length ? `<details><summary class="detail-sub">Regressed question details</summary>
      ${d.regressed_ids.map((q) => `<div class="chunk-card"><span class="gkind">${esc(q.id)}</span> <span>${esc(q.question)}</span><div class="mini-label">recall ${esc(q.recall)}${q.rank ? ` · rank ${esc(q.rank)}` : ""}</div></div>`).join("")}
    </details>` : ""}`;
}

async function loadSnapshots() {
  try {
    const data = await api("/api/eval/snapshots");
    const host = $("#suite-list");
    const panel = $("#suite-panel");
    const count = data.snapshots?.length || 0;
    $("#suite-count").textContent = count;
    if (!count) {
      panel.style.display = "none";
      host.innerHTML = `<p class="detail-sub">No snapshots yet — press ▶ Run evaluation suite.</p>`;
      return;
    }
    panel.style.display = "";
    host.innerHTML = `<div class="detail-section"><h4>Snapshots (${data.snapshots.length})</h4>${dataTable(data.snapshots, [
      { label: "Snapshot", get: (x) => x.snapshot_id },
      { label: "When", get: (x) => fmtWhen(x.created_at) },
      { label: "Strategy", get: (x) => x.config?.strategy },
      { label: "Retriever", get: (x) => x.config?.retriever },
      { label: "Recall@k", get: (x) => x.aggregate?.recall_at_k ?? "–", cls: (x) => clsFor("recall_at_k", x.aggregate?.recall_at_k) },
      { label: "Avg rank", get: (x) => x.aggregate?.first_relevant_rank ?? "–", cls: (x) => clsFor("first_relevant_rank", x.aggregate?.first_relevant_rank) },
      { label: "Faithfulness", get: (x) => x.ragas?.aggregate?.faithfulness ?? "–", cls: (x) => clsFor("faithfulness", x.ragas?.aggregate?.faithfulness) },
      { label: "Ctx prec.", get: (x) => x.ragas?.aggregate?.context_precision ?? "–", cls: (x) => clsFor("context_precision", x.ragas?.aggregate?.context_precision) },
      { label: "Ctx rec.", get: (x) => x.ragas?.aggregate?.context_recall ?? "–", cls: (x) => clsFor("context_recall", x.ragas?.aggregate?.context_recall) },
      { label: "Label", get: (x) => x.label || "" },
    ])}</div>`;
    // action buttons per snapshot
    data.snapshots.forEach((s) => {
      const wrap = document.createElement("div");
      wrap.className = "detail-section snap-actions";
      wrap.innerHTML = `
        <span class="gkind">${esc(s.snapshot_id)}</span>
        ${data.baseline?.snapshot_id === s.snapshot_id ? `<span class="baseline-chip">📌 baseline</span>` : ""}
        <button class="btn mini-btn" data-act="baseline" data-id="${esc(s.snapshot_id)}">Set as baseline</button>
        <button class="btn mini-btn" data-act="open" data-id="${esc(s.snapshot_id)}">Open detail</button>
        <button class="btn mini-btn" data-act="diff" data-id="${esc(s.snapshot_id)}">Diff vs baseline</button>
        <button class="btn mini-btn" data-act="del" data-id="${esc(s.snapshot_id)}">🗑</button>`;
      wrap.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => snapshotAction(b.dataset.act, b.dataset.id)));
      host.appendChild(wrap);
    });
  } catch {}
}

/* ── snapshot one-line report + recommendation ────────────── */
function snapshotReport(snap) {
  const a = snap.aggregate || {};
  const rag = snap.ragas && !snap.ragas.error ? (snap.ragas.aggregate || {}) : {};
  const recall = a.recall_at_k, rank = a.first_relevant_rank,
        cit = a.citation_coverage, must = a.must_term_coverage,
        ref = a.refusal_accuracy, faith = rag.faithfulness,
        cprec = rag.context_precision, crec = rag.context_recall;
  const f = (v, d = 2) => (v == null ? null : Number(v).toFixed(d));

  // Build the one-line summary from what exists.
  const bits = [];
  if (recall != null) bits.push(`retrieval found the right chunk for ${Math.round(recall * 100)}% of questions`);
  if (rank != null) bits.push(`correct chunk typically at position #${f(rank, 2)}`);
  if (faith != null) bits.push(`answers are ${Math.round(faith * 100)}% grounded in retrieved text`);
  if (crec != null) bits.push(`retrieved text covers ${Math.round(crec * 100)}% of what reference answers need`);
  if (ref != null) bits.push(`refusal on unanswerable questions ${Math.round(ref * 100)}%`);
  if (a.mean_total_ms != null) bits.push(`avg ${a.mean_total_ms} ms/question`);
  const line = bits.length ? bits.join(", ") : "no scored metrics recorded for this run";

  // Health verdict: red if any core metric is out of band.
  const states = [healthOf("recall_at_k", recall), healthOf("first_relevant_rank", rank),
                  healthOf("faithfulness", faith), healthOf("context_recall", crec),
                  healthOf("refusal_accuracy", ref)].filter(Boolean);
  const icon = states.includes("bad") ? "🔴" : states.includes("mid") ? "🟡" : "🟢";

  // Recommendations, most important first.
  const recs = [];
  if (crec != null && healthOf("context_recall", crec) !== "good")
    recs.push("retrieval is missing source content — raise top_k (e.g. 5→8), or try a chunking strategy with more overlap (character/structural), or re-ingest with smaller chunks");
  if (cprec != null && healthOf("context_precision", cprec) !== "good")
    recs.push("relevant chunks rank too low in the list — tune rrf_k (try 20), or give BM25/vector different weights in hybrid_search");
  if (faith != null && healthOf("faithfulness", faith) !== "good")
    recs.push("answers contain unsupported claims — check that top-k chunks actually contain the answer (low ctx recall above compounds this); also verify temperature 0 and that citations resolve");
  if (cit != null && cit < 0.4 && a.citation_coverage != null)
    recs.push("citation coverage is low — headerless chunking (character/semantic) stores generic section labels, so [Source: ...] often won't match; this is partly cosmetic");
  if (ref != null && ref < 0.9)
    recs.push("the pipeline answers questions it should refuse — strengthen refusal instructions in the system prompt");
  if (!recs.length)
    recs.push("results look healthy — set this snapshot as the baseline and use Diff vs baseline to catch future regressions");

  return `<div class="detail-section"><h4>${icon} One-line report</h4>
    <div class="report-line">${esc(line)}</div>
    <div class="report-recs">${recs.map((r, i) => `<p class="detail-sub">${i === 0 ? "<b>Recommendation:</b> " : ""}${esc(r)}</p>`).join("")}</div>
  </div>`;
}

async function snapshotAction(act, id) {
  try {
    if (act === "baseline") {
      await api("/api/eval/baseline", { method: "POST", body: JSON.stringify({ snapshot_id: id }) });
      toast(`📌 Baseline set to ${id}`, "success");
      await loadSnapshots();
    } else if (act === "open") {
      openEvalPanel("suite-panel");
      const snap = await api(`/api/eval/snapshot/${id}`);
      // ragas per-question scores live in snap.ragas.per_question, keyed by
      // row id — merge them into the rows so the table shows judged scores.
      const ragasByid = {};
      (snap.ragas?.per_question || []).forEach((pq) => { ragasByid[pq.id] = pq; });
      $("#diff-view").innerHTML = `${snapshotReport(snap)}<div class="detail-section"><h4>Snapshot ${esc(id)} — per-question results</h4>${dataTable(snap.results?.map((row) => {
        const rq = ragasByid[row.id] || {};
        return {
          id: row.id, kind: row.kind, q: (row.question || "").slice(0, 60),
          recall: row.recall_at_k, rank: row.first_relevant_rank,
          cov: row.citation_coverage, ms: row.total_ms,
          faith: rq.faithfulness, cprec: rq.context_precision,
          crec: rq.context_recall,
        };
      }) || [], [
        { label: "Q-id", get: (x) => x.id }, { label: "Kind", get: (x) => x.kind },
        { label: "Question", get: (x) => x.q }, { label: "Recall", get: (x) => x.recall ?? "–", cls: (x) => clsFor("recall_at_k", x.recall) },
        { label: "Rank", get: (x) => x.rank ?? "–", cls: (x) => clsFor("first_relevant_rank", x.rank) },
        { label: "Cite cov.", get: (x) => x.cov ?? "–", cls: (x) => clsFor("citation_coverage", x.cov) },
        { label: "Faithfulness", get: (x) => x.faith ?? "–", cls: (x) => clsFor("faithfulness", x.faith) },
        { label: "Ctx prec.", get: (x) => x.cprec ?? "–", cls: (x) => clsFor("context_precision", x.cprec) },
        { label: "Ctx rec.", get: (x) => x.crec ?? "–", cls: (x) => clsFor("context_recall", x.crec) },
        { label: "ms", get: (x) => x.ms, cls: (x) => { const h = healthOfLatency(x.ms); return h ? `score-${h}` : ""; } },
      ])}</div>
      ${renderRagasSection(snap.ragas)}${ragasDetailRows(snap)}`;
    } else if (act === "diff") {
      openEvalPanel("suite-panel");
      const d = await api(`/api/eval/diff?id=${encodeURIComponent(id)}`);
      $("#diff-view").innerHTML = suiteDiffBlock({ ...d, strategy: d.current_id });
    } else if (act === "del") {
      if (!confirm(`Delete snapshot ${id}?`)) return;
      await api(`/api/eval/snapshot/${id}`, { method: "DELETE" });
      toast(`Snapshot ${id} deleted`, "success");
      await loadSnapshots();
    }
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ── collection badge ────────────────────────────────────── */

async function refreshCollectionBadge() {
  try {
    const s = await api("/api/collection/status");
    const badge = $("#collection-badge");
    badge.classList.remove("badge-green", "badge-gray", "badge-red");
    badge.classList.add(s.exists && s.count > 0 ? "badge-green" : "badge-gray");
    $("#collection-count").textContent = s.count;
    badge.title = s.exists
      ? `Collection '${s.collection_name}' @ ./${s.chroma_path} — ${Object.entries(s.documents || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "empty"}`
      : "Collection not created yet — run ingestion first";
  } catch {}
}

/* ── boot ────────────────────────────────────────────────── */

async function boot() {
  // tabs
  $$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

  const cfg = await api("/api/config");
  state.meta = cfg.meta;
  state.values = cfg.values;
  state.steps = cfg.steps;

  ["ingest", "query", "eval"].forEach((tab) => {
    renderWorkflow(tab);
    renderConfigPanel(tab);
  });
  renderWorkflow("suite");
  renderConfigPanel("suite");

  // default file selection: docs/ folder
  try {
    const docs = await api("/api/docs");
    state.selectedFiles = docs.files.map((f) => ({ path: f.path, name: f.title }));
    renderSelectedFiles();
  } catch {}

  // collection badge + clear button
  refreshCollectionBadge();

  // ingestion controls
  $("#browse-btn").addEventListener("click", openBrowse);
  $("#browse-close").addEventListener("click", () => $("#browse-modal").classList.add("hidden"));
  $("#browse-cancel").addEventListener("click", () => $("#browse-modal").classList.add("hidden"));
  $("#browse-ok").addEventListener("click", browseOk);
  $("#browse-up").addEventListener("click", () => state.browse?.parent && browsePath(state.browse.parent));
  $("#ingest-run").addEventListener("click", () => runTab("ingest"));

  // query controls
  $("#query-run").addEventListener("click", () => runTab("query"));
  $("#query-input").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runTab("query");
  });

  // evaluation tab (golden set workflow + regression suite workflow)
  $("#eval-run").addEventListener("click", () => runTab("eval"));
  $("#eval-freeze").addEventListener("click", freezeGolden);
  $("#suite-run").addEventListener("click", () => runTab("suite"));
  loadGolden();
  loadSnapshots();

  // reset config
  $("#reset-config").addEventListener("click", async () => {
    const res = await api("/api/config/reset", { method: "POST" });
    state.values = res.values;
    ["ingest", "query", "eval"].forEach((tab) => renderConfigPanel(tab));
    toast("Configuration reset to defaults", "success");
  });
}

boot().catch((e) => toast(`Boot failed: ${e.message}`, "error"));