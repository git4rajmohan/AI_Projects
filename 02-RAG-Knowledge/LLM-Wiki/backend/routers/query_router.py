"""Query router — chat with wiki context, streaming SSE, save analysis pages."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Union

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from backend.config import load_config, is_llm_configured
from backend.services import llm_service, wiki_manager, ingest_service

router = APIRouter(prefix="/api/query", tags=["query"])

# Directory for uploaded chat images
IMAGES_DIR = Path(__file__).parent.parent.parent / "chat_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

QUERY_SYSTEM_PROMPT = """\
You are a knowledgeable assistant with access to a structured wiki knowledge base.
Answer the user's question using ONLY the wiki pages provided in the context.

CRITICAL RULES:
- Answer ONLY using information explicitly stated in the wiki context.
- Do NOT use your general knowledge, training data, or make assumptions.
- If the wiki context does not contain information to answer the question, say: "The wiki does not contain information about this topic."
- Do NOT invent or fabricate information that is not in the wiki context.
- Write answers in plain prose — do NOT use [[wiki-link]] notation.
- Be concise and precise.
- If you used wiki pages to answer, end with a ## References section listing each page title used (plain text, one per line). If you used NO wiki pages, omit the References section entirely — do NOT write [] or an empty list.
- After your answer, add: ## Confidence: N where N is 0-100 (100=fully supported by wiki, 0=no relevant info)."""

GENERAL_SYSTEM_PROMPT = """\
You are a helpful, knowledgeable assistant. Answer the user's question directly and concisely.
If you don't know the answer, say so clearly. Use markdown formatting where helpful."""


def _get_project_and_llm(project_id: str | None = None):
    cfg = load_config()
    pid = project_id or cfg.active_project_id
    if not pid:
        raise HTTPException(400, "No active project")
    project = next((p for p in cfg.projects if p.id == pid), None)
    if not project:
        raise HTTPException(404, "Project not found")
    return project, cfg.llm


class ChatMessage(BaseModel):
    role: str
    content: Union[str, list[dict]]  # string or list of content parts (text/image_url)


class QueryRequest(BaseModel):
    project_id: str | None = None
    messages: list[ChatMessage] = []
    mode: str = "wiki"  # "wiki" (default) or "general"
    retrieval_mode: str = "keyword"  # "keyword" (fast) or "semantic" (LLM-based page selection)
    # Legacy single-question field (fallback)
    question: str | None = None


class SaveAnalysisRequest(BaseModel):
    title: str
    content: str
    project_id: str | None = None


@router.post("/")
async def query(body: QueryRequest):
    # Resolve question from messages or legacy field
    question = body.question or ""
    if body.messages:
        last_user_msg = next(
            (m for m in reversed(body.messages) if m.role == "user"), None
        )
        if last_user_msg:
            # content can be a string or a list of content parts
            if isinstance(last_user_msg.content, str):
                question = last_user_msg.content
            elif isinstance(last_user_msg.content, list):
                # Extract text parts for keyword matching
                question = " ".join(
                    p.get("text", "") for p in last_user_msg.content if p.get("type") == "text"
                )

    if not question.strip():
        raise HTTPException(400, "Question is empty")

    # General Q&A mode — no wiki context needed, no project required
    if body.mode == "general":
        cfg = load_config()
        llm_cfg = cfg.llm
        if not is_llm_configured(llm_cfg):
            raise HTTPException(400, "LLM is not connected. Configure and test the LLM connection first.")

        prior_turns = [
            {"role": m.role, "content": m.content}
            for m in body.messages[:-1]
            if m.role in ("user", "assistant") and (
                (isinstance(m.content, str) and m.content.strip())
                or (isinstance(m.content, list) and any(p.get("text", "").strip() for p in m.content if p.get("type") == "text"))
            )
        ]

        # Use the full content (text + images) for the last user message
        last_user_msg = next(
            (m for m in reversed(body.messages) if m.role == "user"), None
        )
        last_content = last_user_msg.content if last_user_msg else question

        llm_messages = [
            {"role": "system", "content": GENERAL_SYSTEM_PROMPT},
            *prior_turns,
            {"role": "user", "content": last_content},
        ]

        async def general_stream():
            async for chunk in llm_service.stream_completion(llm_cfg, llm_messages):
                yield f"data: {json.dumps({'type': 'token', 'token': chunk})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(general_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Wiki Q&A mode (default) — requires project and wiki context
    project, llm_cfg = _get_project_and_llm(body.project_id)

    if not is_llm_configured(llm_cfg):
        raise HTTPException(400, "LLM is not connected. Configure and test the LLM connection first.")

    # Read index to find relevant pages
    index_path = wiki_manager._effective_root(project.root_path) / "wiki" / "index.md"
    if not index_path.exists():
        raise HTTPException(400, "Wiki index not found — ingest sources first")

    index_content = index_path.read_text(encoding="utf-8")

    # Find wiki pages relevant to the question
    is_local = llm_cfg.provider == "local-cpu"
    max_pages = 3 if is_local else 8

    if body.retrieval_mode == "semantic" and not is_local:
        # Semantic mode: use LLM to select relevant pages from the index
        relevant_pages = await _semantic_find_relevant_pages(
            llm_cfg, project.root_path, question, index_content, max_pages=max_pages
        )
    else:
        # Keyword mode: fast keyword matching on index slugs. Local CPU models also use
        # this path for reliability; semantic retrieval requires an extra LLM call.
        relevant_pages = _find_relevant_pages(project.root_path, question, index_content, max_pages=max_pages)

    if is_local:
        # For local models: extract only the most relevant paragraphs from entity/concept pages
        # to keep context small. But send FULL content for source pages since they are the
        # primary knowledge base and shouldn't be truncated.
        context_parts = []
        char_budget = 12000
        for page_path in relevant_pages:
            page = wiki_manager.read_page(project.root_path, page_path)
            if page:
                # Use the page title from frontmatter as the header (not the raw file path)
                page_title = page.get("frontmatter", {}).get("title", page_path)
                current_len = len("\n\n".join(context_parts))
                if page_path.startswith("sources/"):
                    # Source pages: send full content (they're the primary knowledge)
                    entry = f"## Wiki Page: {page_title}\n\n{page['content']}"
                else:
                    # Entity/concept/other pages: extract relevant snippets only
                    snippets = _extract_relevant_snippets(page["content"], question, max_chars=800)
                    if not snippets:
                        continue
                    entry = f"## Wiki Page: {page_title}\n\n{snippets}"
                if current_len + len(entry) > char_budget:
                    snippets = _extract_relevant_snippets(page["content"], question, max_chars=3000)
                    if snippets:
                        entry = f"## Wiki Page: {page_title}\n\n{snippets}"
                if current_len + len(entry) > char_budget:
                    continue
                context_parts.append(entry)
        context = "\n\n---\n\n".join(context_parts) if context_parts else "(no relevant content found)"
    else:
        # For cloud models: send full pages with a large budget
        context_parts = [f"## wiki/index.md\n\n{index_content}"]
        char_budget = 40000
        for page_path in relevant_pages:
            page = wiki_manager.read_page(project.root_path, page_path)
            if page:
                page_title = page.get("frontmatter", {}).get("title", page_path)
                entry = f"## Wiki Page: {page_title}\n\n{page['content']}"
                if len("\n\n".join(context_parts)) + len(entry) > char_budget:
                    break
                context_parts.append(entry)
        context = "\n\n---\n\n".join(context_parts)

    # Build message list — include prior turns for multi-turn context
    all_prior = [
        {"role": m.role, "content": m.content}
        for m in body.messages[:-1]  # exclude the last user message (added below)
        if m.role in ("user", "assistant") and (
            (isinstance(m.content, str) and m.content.strip())
            or (isinstance(m.content, list) and any(p.get("text", "").strip() for p in m.content if p.get("type") == "text"))
        )
    ]
    if is_local:
        # Small local models are easily anchored by the previous answer. Only include
        # chat history when the new question is clearly a follow-up.
        prior_turns = all_prior[-2:] if _is_followup_question(question) and len(all_prior) >= 2 else []
    else:
        prior_turns = all_prior

    # Build the user message — include wiki context + question + any images
    last_user_msg = next(
        (m for m in reversed(body.messages) if m.role == "user"), None
    )
    # If the last user message has images, include them as content parts
    if last_user_msg and isinstance(last_user_msg.content, list):
        # Prepend wiki context as text, keep image parts
        user_content = [
            {"type": "text", "text": f"## Wiki Context\n\n{context}\n\n## Question\n\n{question}"},
            *[p for p in last_user_msg.content if p.get("type") == "image_url"],
        ]
    else:
        user_content = f"## Wiki Context\n\n{context}\n\n## Question\n\n{question}\n\n---\nAnswer using ONLY the wiki context above. Output actual content, not descriptions. If you used wiki pages, end with:\n## References\n(one page title per line)\n## Confidence: N\nIf you used NO wiki pages, just write: ## Confidence: 0\nDo NOT write [] or empty lists."

    # Use a shorter system prompt for local models to save context
    sys_prompt = (
        "You answer questions using ONLY the wiki context provided. "
        "Do NOT use your general knowledge. "
        "If a generated entity/concept page conflicts with a source page, trust the source page. "
        "Write complete sentences that EXPLAIN each item — never just list IDs, codes, or abbreviations (like BR-01, REQ-5, etc.) without explaining what they mean. "
        "If the wiki contains named items (features, requirements, capabilities), describe what each one does in plain English. "
        "If the wiki does not contain the answer, say: 'The wiki does not contain information about this topic.' "
        "Do not use [[wiki-link]] syntax."
    ) if is_local else QUERY_SYSTEM_PROMPT

    # Keyword-based confidence as a preliminary indicator (sent immediately)
    keyword_confidence = _compute_confidence(question, context)

    llm_messages = [
        {"role": "system", "content": sys_prompt},
        *prior_turns,
        {"role": "user", "content": user_content},
    ]

    query_llm_cfg = llm_cfg
    if is_local:
        query_llm_cfg = llm_cfg.model_copy(
            update={"max_tokens": min(llm_cfg.max_tokens, 512)}
        )

    async def event_stream():
        # Send keyword-based confidence immediately so UI shows something
        yield f"data: {json.dumps({'type': 'confidence', 'score': keyword_confidence, 'source': 'keyword'})}\n\n"

        immediate_answer = _build_extractive_answer(context, question, require_structured=True)
        if is_local and immediate_answer:
            yield f"data: {json.dumps({'type': 'token', 'token': immediate_answer})}\n\n"
            yield f"data: {json.dumps({'type': 'confidence', 'score': keyword_confidence, 'source': 'retrieval-fallback'})}\n\n"
            citation_objects = [
                {"path": p, "title": _path_to_title(p)}
                for p in relevant_pages
                if p not in ("index.md", "overview.md")
            ]
            yield f"data: {json.dumps({'type': 'citations', 'pages': citation_objects})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        async def _generate_answer() -> str:
            chunks = []
            async for chunk in llm_service.stream_completion(query_llm_cfg, llm_messages):
                chunks.append(chunk)
            return "".join(chunks)

        # Try generating the answer. If the model returns an empty answer
        # (only References/Confidence with no actual content), retry once.
        max_attempts = 2 if is_local else 1
        answer_text = ""
        for attempt in range(max_attempts):
            # Collect full answer (non-streaming) so we can check validity before sending
            try:
                if is_local:
                    answer_text = await asyncio.wait_for(_generate_answer(), timeout=120)
                else:
                    answer_text = await _generate_answer()
            except asyncio.TimeoutError:
                fallback_answer = _build_extractive_answer(context, question)
                if fallback_answer:
                    yield f"data: {json.dumps({'type': 'token', 'token': fallback_answer})}\n\n"
                    yield f"data: {json.dumps({'type': 'confidence', 'score': keyword_confidence, 'source': 'retrieval-fallback'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'token', 'token': 'The local model took too long to answer, and no relevant wiki context was found. Try Keyword retrieval, ask a narrower question, or reduce the project size.'})}\n\n"
                    yield f"data: {json.dumps({'type': 'confidence', 'score': {'score': 0, 'label': 'Low', 'matched': 0, 'total': 0}, 'source': 'timeout'})}\n\n"
                citation_objects = [
                    {"path": p, "title": _path_to_title(p)}
                    for p in relevant_pages
                    if p not in ("index.md", "overview.md")
                ]
                yield f"data: {json.dumps({'type': 'citations', 'pages': citation_objects})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # Check if the answer has actual content (not just References/Confidence)
            # Strip out the References and Confidence sections and check if anything remains
            stripped = re.sub(r"##\s*References.*", "", answer_text, flags=re.DOTALL | re.IGNORECASE)
            stripped = re.sub(r"##\s*Confidence:[^\n]*", "", stripped, flags=re.IGNORECASE)
            stripped = stripped.strip()
            if len(stripped) > 20:  # Has real content
                break
            # If empty, retry with a different seed (local models sometimes generate nothing)
            if attempt < max_attempts - 1:
                import random as _r
                # Modify the prompt slightly to get a different generation
                llm_messages[-1] = {
                    "role": "user",
                    "content": str(llm_messages[-1].get("content", "")) + "\n\n(Please provide a detailed answer.)",
                }

        # Parse semantic confidence before any stripping (needs the raw ## Confidence: N)
        sem_conf = _parse_llm_confidence(answer_text)

        # Post-process for display: strip thinking blocks, ## References section
        # (shown as citation cards in the UI), bare [] empty lists, and the
        # ## Confidence line (surfaced separately in the UI confidence widget)
        answer_text = ingest_service._strip_thinking(answer_text)
        answer_text = re.sub(r'\n*##\s*References\b.*', '', answer_text, flags=re.DOTALL | re.IGNORECASE).rstrip()
        answer_text = re.sub(r'^\[\]\s*$', '', answer_text, flags=re.MULTILINE)
        answer_text = re.sub(r'\n*##\s*Confidence:[^\n]*', '', answer_text, flags=re.IGNORECASE).rstrip()
        if not answer_text.strip():
            answer_text = _build_extractive_answer(context, question)

        # Stream the cleaned answer to the client
        yield f"data: {json.dumps({'type': 'token', 'token': answer_text})}\n\n"

        if sem_conf is not None:
            yield f"data: {json.dumps({'type': 'confidence', 'score': sem_conf, 'source': 'llm'})}\n\n"

        # Convert path strings → citation objects {path, title} for the frontend.
        # Skip meta pages (index.md, overview.md) that are always included but aren't
        # specific sources for the answer.
        citation_objects = [
            {"path": p, "title": _path_to_title(p)}
            for p in relevant_pages
            if p not in ("index.md", "overview.md")
        ]
        yield f"data: {json.dumps({'type': 'citations', 'pages': citation_objects})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/save-analysis")
def save_analysis(body: SaveAnalysisRequest):
    project, _ = _get_project_and_llm(body.project_id)
    today = date.today().isoformat()

    # Generate a slug from the title
    slug = re.sub(r"[^\w\s-]", "", body.title.lower())
    slug = re.sub(r"[\s]+", "-", slug.strip())[:60]
    filename = f"analyses/{today}-{slug}.md"

    file_content = (
        f"---\ntitle: \"{body.title}\"\ntype: analysis\ncreated: {today}\nupdated: {today}\n---\n\n"
        f"# {body.title}\n\n"
        f"{body.content}\n"
    )

    wiki_manager.write_wiki_page(project.root_path, filename, file_content)
    wiki_manager.append_log(
        project.root_path,
        f"## [{today}] analysis | {body.title[:80]}",
    )
    return {"ok": True, "path": filename}


@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload a chat image. Returns a URL to access the stored image."""
    ALLOWED = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    MAX_BYTES = 10 * 1024 * 1024  # 10 MB

    if file.content_type not in ALLOWED:
        raise HTTPException(400, "Unsupported image type. Use JPEG, PNG, GIF, or WebP.")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(400, "Image exceeds 10 MB limit.")

    ext = Path(file.filename or "upload").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    (IMAGES_DIR / filename).write_bytes(content)
    return {"url": f"/api/query/image/{filename}", "filename": filename}


@router.get("/image/{filename}")
async def serve_image(filename: str):
    """Serve a previously uploaded chat image."""
    safe = Path(filename).name  # strip any path components to prevent directory traversal
    path = IMAGES_DIR / safe
    if not path.exists() or not str(path.resolve()).startswith(str(IMAGES_DIR.resolve())):
        raise HTTPException(404, "Image not found.")
    return FileResponse(path)


def _parse_llm_confidence(answer_text: str) -> dict | None:
    """Parse '## Confidence: N' from the end of the LLM answer.
    Returns a confidence dict with score, label, matched, total — or None if not found."""
    match = re.search(r"##\s*Confidence:\s*(\d+)", answer_text, re.IGNORECASE)
    if not match:
        return None
    score = int(match.group(1))
    score = max(0, min(100, score))  # Clamp 0-100
    if score >= 75:
        label = "High"
    elif score >= 40:
        label = "Medium"
    elif score > 0:
        label = "Low"
    else:
        label = "None"
    return {"score": score, "label": label, "matched": 0, "total": 0}


def _path_to_title(p: str) -> str:
    """Convert a wiki path into a display title."""
    name = Path(p).name
    stem = name.split('.')[0]
    return stem.replace("-", " ").replace("_", " ").title()


def _is_followup_question(question: str) -> bool:
    """Return true when the current question depends on prior chat context."""
    q = question.strip().lower()
    followup_markers = (
        "it", "this", "that", "these", "those", "above", "previous", "same",
        "more", "also", "them", "they", "there", "explain more", "tell me more",
    )
    return any(re.search(rf"\b{re.escape(marker)}\b", q) for marker in followup_markers)


def _build_extractive_answer(context: str, question: str, require_structured: bool = False) -> str:
    """Build a simple answer directly from retrieved wiki context.

    This keeps local CPU queries useful when a small model times out or returns an
    empty completion after retrieval already found relevant source material.
    """
    if not context or context == "(no relevant content found)":
        return ""

    question_terms = _query_terms(question)
    role_terms = {"role", "responsibilit", "responsibility", "responsible", "team", "raci", "member"}
    invoice_terms = {"invoice", "invoic", "billing", "bill", "pdf"}
    risk_terms = {"risk", "register", "mitigate", "mitigation", "strategy", "plan"}
    calendar_terms = {
        "calendar", "sprint", "phase", "week", "schedule", "milestone", "deliverable",
        "uat", "testing", "deployment", "closure", "initiation", "planning", "design",
        "go", "live", "golive",
    }
    project_summary_terms = {
        "project", "requirement", "objective", "scope", "core", "goal", "purpose",
        "overview", "summary", "business",
    }

    pages: list[tuple[str, str]] = []
    for block in re.split(r"\n\n---\n\n", context):
        match = re.match(r"## Wiki Page: ([^\n]+)\n\n(.*)", block, flags=re.DOTALL)
        if match:
            pages.append((match.group(1).strip(), match.group(2).strip()))

    # If the question is about roles/responsibilities and a RACI table is present,
    # return the table directly. This is usually clearer than a weak generated summary.
    if question_terms & role_terms:
        for title, body in pages:
            if "| Activity |" in body and "R = Responsible" in body:
                table_lines = []
                in_table = False
                for line in body.splitlines():
                    if line.startswith("| Activity |"):
                        in_table = True
                    if in_table and line.startswith("|"):
                        table_lines.append(line)
                        continue
                    if in_table:
                        break

                legend_match = re.search(
                    r"Legend:\s*\n\s*R\s*=\s*Responsible\s*\n\s*A\s*=\s*Accountable\s*\n\s*C\s*=\s*Consulted\s*\n\s*I\s*=\s*Informed",
                    body,
                    flags=re.IGNORECASE,
                )
                legend = legend_match.group(0) if legend_match else "Legend:\nR = Responsible\nA = Accountable\nC = Consulted\nI = Informed"
                return (
                    "The wiki identifies team roles and responsibilities through a RACI matrix. "
                    "Use the legend below to read each activity assignment.\n\n"
                    + "\n".join(table_lines[:24])
                    + "\n\n"
                    + legend
                )

    if question_terms & risk_terms:
        requested_risk_ids = {risk_id.upper() for risk_id in re.findall(r"\br\d+\b", question.lower())}
        risk_lines: list[str] = []
        for title, body in pages:
            if "Risk Register" not in title and "| Risk ID |" not in body:
                continue
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped.startswith("| R"):
                    continue
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if len(cells) < 9 or not re.fullmatch(r"R\d+", cells[0]):
                    continue
                risk_id, description, category, probability, impact, score, mitigation, owner, status = cells[:9]
                if requested_risk_ids and risk_id not in requested_risk_ids:
                    continue
                risk_lines.append(
                    f"- **{risk_id}** ({category}, score {score}, {status}): {description}. "
                    f"Mitigation: {mitigation}. Owner: {owner}."
                )

        if risk_lines:
            deduped = list(dict.fromkeys(risk_lines))
            return "The risk register lists these risks and mitigation strategies:\n\n" + "\n".join(deduped[:20])

    if question_terms & invoice_terms:
        invoice_lines: list[str] = []
        for title, body in pages:
            for line in body.splitlines():
                stripped = line.strip()
                normalized = stripped.lower()
                if "invoice" in normalized:
                    invoice_lines.append(f"- {stripped.lstrip('- ').strip()} ({title})")
        if invoice_lines:
            deduped = list(dict.fromkeys(invoice_lines))
            return (
                "Invoice management is covered in the wiki as customer access to invoice information and downloads.\n\n"
                + "\n".join(deduped[:8])
            )

    if question_terms & calendar_terms:
        sprint_numbers = set(re.findall(r"sprint\s*(\d+)", question.lower()))
        week_numbers = set(re.findall(r"\b(?:wk|week)\s*(\d+)\b", question.lower()))
        calendar_lines: list[str] = []
        focused_calendar_terms = question_terms & {"uat", "testing", "deployment", "closure", "initiation", "planning", "design"}
        for title, body in pages:
            if "Team Calendar" not in title and "Sprint / Phase" not in body:
                continue
            for line in body.splitlines():
                stripped = line.strip()
                normalized = stripped.lower()
                if (
                    not stripped
                    or stripped.startswith("#")
                    or stripped.startswith("Week\t")
                    or stripped.startswith("Week ")
                    or re.match(r"-\s+\*\*[^*]+\*\*:", stripped)
                ):
                    continue
                if week_numbers:
                    if any(re.match(rf"wk\s+{re.escape(n)}\b", normalized) for n in week_numbers):
                        calendar_lines.append(stripped)
                elif sprint_numbers:
                    if any(f"sprint {n}" in normalized or f"sprint{n}" in normalized for n in sprint_numbers):
                        calendar_lines.append(stripped)
                elif "uat" in focused_calendar_terms:
                    if "uat" in normalized:
                        calendar_lines.append(stripped)
                elif focused_calendar_terms:
                    if any(term in normalized for term in focused_calendar_terms) or ("deployment" in focused_calendar_terms and "go-live" in normalized):
                        calendar_lines.append(stripped)
                elif any(term in normalized for term in ("sprint", "uat", "testing", "deployment", "closure", "initiation", "planning", "design", "go-live")):
                    calendar_lines.append(stripped)

        if calendar_lines:
            deduped = list(dict.fromkeys(calendar_lines))
            if week_numbers:
                week_label = ", ".join(f"Week {n}" for n in sorted(week_numbers, key=int))
                return f"{week_label} is listed in the team calendar as:\n\n" + "\n".join(f"- {line}" for line in deduped[:6])
            if sprint_numbers:
                sprint_label = ", ".join(f"Sprint {n}" for n in sorted(sprint_numbers))
                return f"{sprint_label} is listed in the team calendar as:\n\n" + "\n".join(f"- {line}" for line in deduped[:6])
            if "uat" in question_terms:
                return "UAT is planned in the team calendar as:\n\n" + "\n".join(f"- {line}" for line in deduped[:8])
            return "The team calendar contains these schedule entries:\n\n" + "\n".join(f"- {line}" for line in deduped[:24])

    if question_terms & project_summary_terms:
        project_summary_answer = _build_project_summary_answer(pages, question)
        if project_summary_answer:
            return project_summary_answer

    generic_table_answer = _build_table_row_answer(pages, question)
    if generic_table_answer:
        return generic_table_answer

    selected: list[str] = []
    for title, body in pages:
        paragraphs = re.split(r"\n\n+", body)
        scored: list[tuple[int, str]] = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph or paragraph.startswith("---"):
                continue
            paragraph_terms = {_normalize_word(w) for w in re.findall(r"\w+", paragraph.lower())}
            score = len(question_terms & paragraph_terms)
            if score:
                scored.append((score, paragraph))
        scored.sort(reverse=True, key=lambda item: item[0])
        for _, paragraph in scored[:2]:
            selected.append(f"From {title}:\n{paragraph}")
            if sum(len(item) for item in selected) > 3500:
                break
        if sum(len(item) for item in selected) > 3500:
            break

    if require_structured:
        return ""

    if selected:
        return "The local model did not return generated prose, but the retrieved wiki context contains these relevant details:\n\n" + "\n\n".join(selected)

    return "The local model did not return generated prose, but relevant wiki pages were retrieved. Review the cited pages for the source details."


def _build_project_summary_answer(pages: list[tuple[str, str]], question: str) -> str:
    """Build an extractive answer for project purpose, scope, objectives, and requirements."""
    question_terms = _retrieval_terms(question)
    trigger_terms = {
        "project", "requirement", "objective", "scope", "core", "goal", "purpose",
        "overview", "summary", "business",
    }
    if not (question_terms & trigger_terms):
        return ""

    overview: list[str] = []
    objectives: list[str] = []
    requirements: list[str] = []
    scope: list[str] = []

    for title, body in pages:
        if title.lower() in {"wiki index", "overview"}:
            continue

        for heading in ("Project Overview", "Executive Summary"):
            section = _extract_markdown_section(body, heading)
            if section:
                for paragraph in re.split(r"\n\s*\n", section):
                    cleaned = _clean_fact_line(paragraph)
                    if cleaned and not cleaned.lower().startswith(("document version history", "business requirements document")):
                        overview.append(f"{cleaned} ({title})")
                        break

        for line in _extract_markdown_section(body, "Business Objectives").splitlines():
            cleaned = _clean_fact_line(line)
            if cleaned and (cleaned.startswith("BO-") or cleaned.lower().startswith(("reduce", "achieve", "launch", "onboard", "provide"))):
                objectives.append(f"{cleaned} ({title})")

        for line in _extract_markdown_section(body, "Business Requirements").splitlines():
            cleaned = _clean_fact_line(line)
            if cleaned and re.match(r"BR-\d+:", cleaned):
                requirements.append(f"{cleaned} ({title})")

        project_scope = _extract_markdown_section(body, "Project Scope")
        for line in project_scope.splitlines():
            cleaned = _clean_fact_line(line)
            if cleaned and not cleaned.upper().startswith(("IN SCOPE", "OUT OF SCOPE")):
                scope.append(f"{cleaned} ({title})")

    overview = list(dict.fromkeys(overview))
    objectives = list(dict.fromkeys(objectives))
    requirements = list(dict.fromkeys(requirements))
    scope = list(dict.fromkeys(scope))

    if not (overview or objectives or requirements or scope):
        return ""

    parts = ["The core requirement of this project is captured in the retrieved source pages as follows:"]
    if overview:
        parts.append("\n**Project purpose**\n" + "\n".join(f"- {line}" for line in overview[:2]))
    if requirements:
        parts.append("\n**Core business requirements**\n" + "\n".join(f"- {line}" for line in requirements[:12]))
    if scope:
        parts.append("\n**In-scope capabilities**\n" + "\n".join(f"- {line}" for line in scope[:8]))
    if objectives:
        parts.append("\n**Business objectives**\n" + "\n".join(f"- {line}" for line in objectives[:6]))

    return "\n".join(parts)


def _extract_markdown_section(body: str, heading: str) -> str:
    """Return content under a markdown heading, plus BRD bullet sections with bold labels."""
    escaped = re.escape(heading)
    heading_match = re.search(rf"^##+\s+{escaped}\s*$", body, flags=re.IGNORECASE | re.MULTILINE)
    if heading_match:
        start = heading_match.end()
        next_heading = re.search(r"^##+\s+", body[start:], flags=re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        return body[start:end].strip()

    bullet_match = re.search(
        rf"^-\s*\*\*{escaped}\*\*:\s*(.*?)(?=\n-\s*\*\*[^*]+\*\*:|\n##+\s+|\Z)",
        body,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return bullet_match.group(1).strip() if bullet_match else ""


def _clean_fact_line(line: str) -> str:
    line = re.sub(r"^[-•–\s]+", "", line.strip())
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def _build_table_row_answer(pages: list[tuple[str, str]], question: str) -> str:
    """Return matching rows from markdown or tab-separated tables in retrieved pages."""
    question_terms = _retrieval_terms(question)
    if not question_terms:
        return ""
    requested_codes = {code.lower() for code in re.findall(r"\b[a-z]+\d+\b", question.lower())}

    scored_rows: list[tuple[int, str, str]] = []
    for row in _iter_table_rows(pages):
        searchable = " ".join([row["title"], *row["headers"], *row["cells"]])
        row_terms = _query_terms(searchable)
        if requested_codes and not (requested_codes & row_terms):
            continue
        hits = question_terms & row_terms
        if not hits:
            continue

        header_hits = question_terms & _query_terms(" ".join(row["headers"]))
        title_hits = question_terms & _query_terms(row["title"])
        score = len(hits) * 10 + len(header_hits) * 4 + len(title_hits) * 3
        formatted = _format_table_row(row)
        row_id = row["cells"][0].lower() if row["cells"] and re.fullmatch(r"[a-z]+\d+", row["cells"][0].lower()) else formatted
        scored_rows.append((score, f"{row['title'].lower()}:{row_id}", formatted))

    if not scored_rows:
        return ""

    scored_rows.sort(reverse=True, key=lambda item: item[0])
    deduped = []
    seen_keys = set()
    for _, key, row in scored_rows:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
    return "The retrieved table rows contain these matching details:\n\n" + "\n".join(deduped[:12])


def _iter_table_rows(pages: list[tuple[str, str]]):
    for title, body in pages:
        if title.lower() in {"wiki index", "overview"}:
            continue
        yield from _iter_markdown_table_rows(title, body)
        yield from _iter_tab_table_rows(title, body)


def _iter_markdown_table_rows(title: str, body: str):
    lines = body.splitlines()
    index = 0
    while index + 1 < len(lines):
        header_line = lines[index].strip()
        separator_line = lines[index + 1].strip()
        if not (header_line.startswith("|") and separator_line.startswith("|")):
            index += 1
            continue

        headers = _split_markdown_row(header_line)
        if not headers or not _is_markdown_separator_row(separator_line):
            index += 1
            continue

        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            cells = _split_markdown_row(lines[index].strip())
            if cells and not _is_markdown_separator_row(lines[index].strip()):
                yield {"title": title, "headers": headers, "cells": cells}
            index += 1


def _iter_tab_table_rows(title: str, body: str):
    rows = []
    for line in body.splitlines():
        stripped = line.strip()
        if "\t" not in stripped:
            if len(rows) >= 2:
                yield from _rows_from_tab_group(title, rows)
            rows = []
            continue
        rows.append([cell.strip() for cell in stripped.split("\t")])

    if len(rows) >= 2:
        yield from _rows_from_tab_group(title, rows)


def _rows_from_tab_group(title: str, rows: list[list[str]]):
    headers = rows[0]
    if len(headers) < 2:
        return
    for cells in rows[1:]:
        if len(cells) < 2:
            continue
        yield {"title": title, "headers": headers, "cells": cells}


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator_row(line: str) -> bool:
    cells = _split_markdown_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _format_table_row(row: dict) -> str:
    pairs = []
    for header, cell in zip(row["headers"], row["cells"]):
        if cell and cell != "-":
            pairs.append(f"{header}: {cell}")
    if not pairs:
        pairs = [cell for cell in row["cells"] if cell and cell != "-"]
    return f"- **{row['title']}**: " + "; ".join(pairs)


def _normalize_word(w: str) -> str:
    """Normalize a word for matching — strips trailing 's' for singular/plural matching."""
    w = w.lower()
    aliases = {
        "calender": "calendar",
        "calenders": "calendar",
    }
    if w in aliases:
        return aliases[w]
    # Simple stemming: remove trailing 's' or 'es' for basic plural matching
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 3:
        return w[:-2]
    if w.endswith("s") and len(w) > 2:
        return w[:-1]
    return w


def _query_terms(text: str) -> set[str]:
    """Tokenize and normalize query text for keyword retrieval.

    Keeps the original token, and also splits compact forms like sprint4 into
    sprint + 4 so user phrasing matches spreadsheet rows and page titles.
    """
    terms: set[str] = set()
    for word in re.findall(r"\w+", text.lower()):
        normalized = _normalize_word(word)
        terms.add(normalized)
        split_match = re.fullmatch(r"([a-z]+)(\d+)", normalized)
        if split_match:
            terms.add(_normalize_word(split_match.group(1)))
            terms.add(split_match.group(2))
    return terms


_RETRIEVAL_STOP_WORDS = {
    "the", "a", "an", "is", "are", "what", "which", "how", "of", "in", "to", "for",
    "and", "or", "on", "at", "by", "this", "that", "it", "from", "with", "be", "was",
    "were", "has", "have", "had", "do", "does", "did", "will", "would", "can", "could",
    "should", "shall", "may", "might", "must", "i", "you", "he", "she", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "about",
    "into", "than", "then", "so", "if", "as", "not", "no", "yes", "give", "show", "tell",
    "list", "explain", "describe", "summarize", "when",
}


def _retrieval_terms(text: str) -> set[str]:
    return _query_terms(text) - _RETRIEVAL_STOP_WORDS


def _score_source_file(path: Path, question_terms: set[str]) -> int:
    """Score source pages by filename plus extracted body/table row content."""
    name_score = len(question_terms & _query_terms(path.stem.replace("-", " ").replace("_", " ")))
    score = name_score * 20

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return score

    body_terms = _query_terms(text)
    score += len(question_terms & body_terms) * 5

    for line in text.splitlines():
        line_terms = _query_terms(line)
        hits = len(question_terms & line_terms)
        if not hits:
            continue
        score += hits
        if "\t" in line or line.lower().startswith("wk ") or "|" in line:
            score += hits * 10
        if line_terms & {"calendar", "sprint", "uat", "testing", "milestone", "deliverable"}:
            score += hits * 4

    return score


def _compute_confidence(question: str, context: str) -> dict:
    """Compute a confidence score based on keyword overlap between question and context.
    Returns a dict with score (0-100), label, and matched/total keywords."""
    stop_words = {"the", "a", "an", "is", "are", "what", "which", "how", "of", "in", "to", "for", "and", "or", "on", "at", "by", "this", "that", "it", "from", "with", "be", "was", "were", "has", "have", "had", "do", "does", "did", "will", "would", "can", "could", "should", "shall", "may", "might", "must", "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "about", "into", "than", "then", "so", "if", "as", "not", "no", "yes", "give", "me", "show", "tell", "list", "explain", "describe"}
    question_words_norm = _query_terms(question) - stop_words
    
    context_words = set(re.findall(r"\w+", context.lower()))
    context_words_norm = {_normalize_word(w) for w in context_words}
    
    matched = question_words_norm & context_words_norm
    total = len(question_words_norm)
    
    if total == 0:
        score = 0
    else:
        score = int((len(matched) / total) * 100)
    
    if score >= 75:
        label = "High"
    elif score >= 40:
        label = "Medium"
    elif score > 0:
        label = "Low"
    else:
        label = "None"
    
    return {"score": score, "label": label, "matched": len(matched), "total": total}


def _find_relevant_pages(wiki_root: str, question: str, index_content: str, max_pages: int = 8) -> list[str]:
    """Extract page paths from index that are relevant to the question."""
    wiki = wiki_manager._effective_root(wiki_root) / "wiki"
    # Extract all [[slug]] or [[slug|display]] references from index
    all_links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", index_content)
    question_words_norm = _retrieval_terms(question)

    scored: list[tuple[int, str]] = []
    for slug in all_links:
        slug_words = set(re.findall(r"\w+", slug.lower()))
        slug_words_norm = {_normalize_word(w) for w in slug_words}
        score = len(question_words_norm & slug_words_norm)
        if score > 0:
            scored.append((score, slug))

    # Sort by relevance, take top N
    scored.sort(reverse=True)
    result = []
    for _, slug in scored[:max_pages]:
        resolved = wiki_manager.resolve_wikilink(wiki_root, slug)
        if resolved:
            result.append(resolved)

    # Always include index and overview
    for special in ["index.md", "overview.md"]:
        if (wiki / special).exists() and special not in result:
            result.insert(0, special)

    # Always include all source pages so the LLM has access to full content.
    # Sort keyword-relevant source files first so they're included within the char budget.
    sources_dir = wiki / "sources"
    if sources_dir.exists():
        source_pages: list[tuple[int, str]] = []
        for src_file in sources_dir.glob("*.md"):
            if src_file.name == "index.md":
                continue
            rel = f"sources/{src_file.name}"
            source_pages.append((_score_source_file(src_file, question_words_norm), rel))

        source_pages.sort(reverse=True)
        source_rels = [rel for _, rel in source_pages]
        source_matches = [rel for score, rel in source_pages if score > 0]
        source_fallbacks = [rel for score, rel in source_pages if score <= 0]

        # Put body-matching source pages before generated entity pages. Source pages
        # preserve tables/spreadsheets and should win when the query matches their rows.
        specials = [p for p in result if p in ("index.md", "overview.md")]
        non_special = [p for p in result if p not in ("index.md", "overview.md") and p not in source_rels]
        result = specials + source_matches + non_special + source_fallbacks

    return result


async def _semantic_find_relevant_pages(
    llm_cfg, wiki_root: str, question: str, index_content: str, max_pages: int = 8
) -> list[str]:
    """Use the LLM to semantically select which wiki pages are relevant to the question.
    This is slower than keyword matching but handles synonyms and semantic equivalence."""
    wiki = wiki_manager._effective_root(wiki_root) / "wiki"
    # Extract all [[slug]] or [[slug|display]] references and their descriptions from index
    all_links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", index_content)

    # Build a compact list of available pages for the LLM to choose from
    page_list = "\n".join(f"- {slug}" for slug in all_links[:50])  # cap at 50 to fit context

    select_prompt = (
        f"Available wiki pages:\n{page_list}\n\n"
        f"Question: {question}\n\n"
        f"List the page names that are most relevant to answering this question. "
        f"Consider synonyms and semantic meaning, not just keyword matches. "
        f"Return only the page names, one per line, up to {max_pages}. "
        f"If none are relevant, return 'NONE'."
    )

    try:
        selector_cfg = llm_cfg
        if llm_cfg.provider == "local-cpu":
            selector_cfg = llm_cfg.model_copy(update={"max_tokens": min(llm_cfg.max_tokens, 256)})
        response = await asyncio.wait_for(
            llm_service.chat_completion(
                selector_cfg,
                [
                    {"role": "system", "content": "You select relevant wiki pages. Return only page names, one per line."},
                    {"role": "user", "content": select_prompt},
                ],
            ),
            timeout=45 if llm_cfg.provider == "local-cpu" else None,
        )
    except Exception:
        # Fallback to keyword matching if LLM call fails
        return _find_relevant_pages(wiki_root, question, index_content, max_pages)

    # Parse LLM response — extract page names
    selected = []
    for line in response.strip().split("\n"):
        line = line.strip().strip("-*•").strip()
        if not line or line.upper() == "NONE":
            continue
        # Try to resolve the page name to a file path
        resolved = wiki_manager.resolve_wikilink(wiki_root, line)
        if resolved:
            selected.append(resolved)
        else:
            # Try matching against all_links
            for slug in all_links:
                if line.lower() in slug.lower() or slug.lower() in line.lower():
                    resolved = wiki_manager.resolve_wikilink(wiki_root, slug)
                    if resolved and resolved not in selected:
                        selected.append(resolved)
                        break

    # Always include index and overview
    for special in ["index.md", "overview.md"]:
        if (wiki / special).exists() and special not in selected:
            selected.insert(0, special)

    # Fallback: if LLM returned nothing useful, use keyword matching
    if len(selected) <= 2:
        return _find_relevant_pages(wiki_root, question, index_content, max_pages)

    # Also include source pages so semantic mode can verify entity pages against
    # original source material. The query context builder enforces the char budget.
    question_words = set(re.findall(r"\w+", question.lower()))
    question_words_norm = {_normalize_word(w) for w in question_words}
    sources_dir = wiki / "sources"
    if sources_dir.exists():
        def _src_key(f: Path) -> int:
            name_words = set(re.findall(r"\w+", f.name.lower()))
            name_words_norm = {_normalize_word(w) for w in name_words}
            return -len(question_words_norm & name_words_norm)

        for src_file in sorted(sources_dir.glob("*.md"), key=_src_key):
            if src_file.name == "index.md":
                continue
            rel = f"sources/{src_file.name}"
            if rel not in selected:
                selected.append(rel)

    return selected


def _extract_relevant_snippets(page_content: str, question: str, max_chars: int = 800) -> str:
    """Extract paragraphs from a wiki page that are most relevant to the question.
    Used for local models to keep context small and focused."""
    question_words = set(re.findall(r"\w+", question.lower()))
    # Remove common stop words
    stop_words = {"the", "a", "an", "is", "are", "what", "which", "how", "of", "in", "to", "for", "and", "or", "on", "at", "by", "this", "that", "it", "from", "with", "be", "was", "were", "has", "have", "had", "do", "does", "did", "will", "would", "can", "could", "should", "shall", "may", "might", "must", "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "about", "into", "than", "then", "so", "if", "as", "not", "no", "yes"}
    question_words = question_words - stop_words
    # Normalize for singular/plural matching
    question_words_norm = {_normalize_word(w) for w in question_words}

    # Split content into paragraphs/sections
    paragraphs = re.split(r"\n\n+", page_content)
    scored = []
    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped or para_stripped.startswith("---"):
            continue
        para_words = set(re.findall(r"\w+", para_stripped.lower()))
        para_words_norm = {_normalize_word(w) for w in para_words}
        score = len(question_words_norm & para_words_norm)
        if score > 0:
            scored.append((score, para_stripped))

    # Sort by relevance score, take top paragraphs up to max_chars
    scored.sort(reverse=True, key=lambda x: x[0])
    result = []
    total = 0
    for score, para in scored:
        if total + len(para) > max_chars:
            break
        result.append(para)
        total += len(para)

    # If nothing matched, return the first few paragraphs as fallback
    if not result:
        for para in paragraphs:
            para = para.strip()
            if para and not para.startswith("---") and not para.startswith("title:"):
                if total + len(para) > max_chars:
                    break
                result.append(para)
                total += len(para)

    return "\n\n".join(result) if result else page_content[:max_chars]


# ── Image upload for chat ────────────────────────────────────────────────────

@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image for use in chat. Returns the image URL."""
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    
    # Generate unique filename
    ext = Path(file.filename or "").suffix or ".png"
    img_id = f"{uuid.uuid4().hex[:12]}{ext}"
    img_path = IMAGES_DIR / img_id
    
    content = await file.read()
    img_path.write_bytes(content)
    
    return {"url": f"/api/query/images/{img_id}", "filename": file.filename}


@router.get("/images/{img_id}")
def serve_image(img_id: str):
    """Serve an uploaded chat image."""
    img_path = IMAGES_DIR / img_id
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path))
