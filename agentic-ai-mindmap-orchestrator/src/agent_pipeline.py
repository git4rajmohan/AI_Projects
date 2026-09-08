"""Multi-agent pipeline for mindmap generation with review loop.

Three agents collaborate:
1. Schema Creator  — analyzes text, produces a JSON mindmap schema
2. Schema Reviewer — evaluates the schema against quality criteria, gives feedback
3. Mindmap Creator — converts the approved schema into Markdown for markmap

The pipeline loops: create → review → revise → review → ... until approved (or max iterations).
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ─── Agent 1: Schema Creator ─────────────────────────────────────────────

SCHEMA_CREATOR_PROMPT = """\
You are a Schema Creator agent. Your job is to analyze text and produce a \
structured mindmap schema in JSON format.

Analyze the input text and create a hierarchical mindmap structure.

Rules:
- Identify the central topic (the main theme of the text)
- Create 3 to 7 major branches (key concepts)
- Each branch MUST have at least 2-3 subtopics
- Each subtopic SHOULD have further nested subtopics (2-3 levels deep) when the content supports it
- Do NOT create flat lists — group related items under parent subtopics
- For example, instead of 5 flat subtopics under a branch, group them into 2 categories with sub-items each
- Keep each node label concise — maximum 8 words
- **Bold key terms**: In each title, wrap the most important word or phrase in **bold** markers. \
  For example: "**GDPR** Compliance" or "**Gender bias** in hiring"
- **Descriptions**: Add a "description" field to each node (1 sentence, max 15 words) \
  providing brief context about what the node covers. This will appear as a hover tooltip.
- Capture the logical structure and key ideas, not every detail
- Use the language of the source text

Output ONLY a valid JSON object with this exact structure:
{
  "topic": "**Central Topic**",
  "description": "Brief description of the central topic",
  "branches": [
    {
      "title": "**Branch Title**",
      "description": "Brief description of this branch",
      "subtopics": [
        {
          "title": "**Sub-topic Title**",
          "description": "Brief description of this subtopic",
          "subtopics": [
            { "title": "**Detail**", "description": "Brief detail", "subtopics": [] }
          ]
        }
      ]
    }
  ]
}

Do NOT include any explanation, markdown formatting, or code fences. \
Output ONLY the raw JSON object.
"""

SCHEMA_REVISER_PROMPT = """\
You are a Schema Creator agent. You previously created a mindmap schema, \
and a reviewer has provided feedback. Your job is to revise the schema \
based on that feedback.

Here is your previous schema:
{previous_schema}

Here is the reviewer's feedback:
{feedback}

Apply the feedback to improve the schema. Keep the same JSON structure:
{{
  "topic": "Central Topic",
  "branches": [
    {{
      "title": "Branch Title",
      "subtopics": [
        {{ "title": "Sub-topic", "subtopics": [] }}
      ]
    }}
  ]
}}

Output ONLY the revised JSON object. No explanation, no code fences.
"""

# ─── Agent 2: Schema Reviewer ────────────────────────────────────────────

SCHEMA_REVIEWER_PROMPT = """\
You are a Schema Reviewer agent. Your job is to evaluate a mindmap schema \
against quality criteria and decide whether to approve it or request changes.

Here is the mindmap schema to review:
{schema}

Here is the original source text (for reference):
{source_text}

Evaluate the schema against these criteria:
1. COVERAGE: Does the schema capture all major topics from the source text? \
   Are any important concepts missing?
2. BALANCE: Are the branches roughly equal in depth and detail? \
   No branch should be overwhelmingly large or trivially small.
3. CONCISENESS: Are all node labels 8 words or fewer?
4. HIERARCHY: Is the depth appropriate? The schema MUST NOT be flat. \
   Each branch should have subtopics, and most subtopics should have further \
   nested subtopics (at least 2-3 levels of nesting). If a branch has only flat \
   subtopics with no deeper nesting, request that related subtopics be grouped \
   under parent categories. Not too deep (5+ levels). 3-4 levels is ideal.
5. ACCURACY: Do the branch titles and subtopics accurately reflect the \
   content of the source text?
6. STRUCTURE: Is the JSON valid and well-formed? Are subtopics arrays present \
   (even if empty)?

Output ONLY a valid JSON object with this exact structure:
{{
  "approved": true_or_false,
  "feedback": "Specific, actionable feedback. If approved, say 'Schema approved. No changes needed.' If not approved, list each issue and what should be changed."
}}

Do NOT include any explanation outside the JSON. Output ONLY the raw JSON object.
"""

# ─── Agent 3: Mindmap Creator ────────────────────────────────────────────

MINDMAP_CREATOR_PROMPT = """\
You are a Mindmap Creator agent. Your job is to convert an approved mindmap \
JSON schema into Markdown headings for rendering with markmap.

Here is the approved schema:
{schema}

Convert it to Markdown using these rules:
- The "topic" field becomes the single # heading (central node)
- Each branch "title" becomes a ## heading
- Each subtopic "title" becomes a ### heading
- Deeper subtopics get ####, #####, etc.
- Keep labels exactly as they appear in the schema
- Output ONLY the Markdown headings — no explanation, no code fences

Example:
# Central Topic
## Branch One
### Sub-point A
### Sub-point B
## Branch Two
### Sub-point C
"""


# ─── LLM helper ──────────────────────────────────────────────────────────

def _get_client(base_url: Optional[str] = None) -> OpenAI:
    url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAI(base_url=url, api_key="ollama")


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    base_url: Optional[str] = None,
    temperature: float = 0.3,
) -> str:
    """Make a single LLM call and return the response text."""
    client = _get_client(base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's just ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping code fences if present."""
    cleaned = _strip_code_fences(text)
    return json.loads(cleaned)


# ─── Schema → Markdown converter ─────────────────────────────────────────

def schema_to_markdown(schema: dict) -> str:
    """Convert a mindmap JSON schema to Markdown headings.

    Hierarchy:
      #  = topic (level 0)
      ## = branch (level 1)
      ### = first-level subtopic (level 2)
      #### = second-level subtopic (level 3)
      etc.

    Includes descriptions as HTML comments for hover tooltips.
    """
    topic = schema.get('topic', 'Mindmap')
    topic_desc = schema.get('description', '')
    topic_line = f"# {topic}"
    if topic_desc:
        topic_line += f" <!-- {topic_desc} -->"
    lines = [topic_line]

    def _render_subtopics(subtopics: list, level: int):
        for item in subtopics:
            prefix = "#" * (level + 2)  # level 1 → ###, level 2 → ####, etc.
            title = item.get('title', '')
            desc = item.get('description', '')
            line = f"{prefix} {title}"
            if desc:
                line += f" <!-- {desc} -->"
            lines.append(line)
            if item.get("subtopics"):
                _render_subtopics(item["subtopics"], level + 1)

    for branch in schema.get("branches", []):
        title = branch.get('title', '')
        desc = branch.get('description', '')
        line = f"## {title}"
        if desc:
            line += f" <!-- {desc} -->"
        lines.append(line)
        if branch.get("subtopics"):
            _render_subtopics(branch["subtopics"], 1)  # start at level 1 → ###

    return "\n".join(lines)


# ─── Pipeline ────────────────────────────────────────────────────────────

def run_agent_pipeline(
    text: str,
    model: str,
    base_url: Optional[str] = None,
    max_iterations: int = 3,
    progress_callback=None,
) -> dict:
    """Run the multi-agent mindmap generation pipeline.

    Args:
        text: The input text to convert into a mindmap.
        model: Ollama model name.
        base_url: Ollama API base URL.
        max_iterations: Maximum review-revise loops before giving up.
        progress_callback: Optional callable(message: str) for status updates.

    Returns:
        A dict with keys:
            - "markdown": The final Markdown string
            - "schema": The final approved JSON schema
            - "iterations": Number of review iterations performed
            - "review_history": List of review feedback strings
            - "approved": Whether the schema was approved by the reviewer
    """
    def _log(msg):
        if progress_callback:
            progress_callback(msg)

    review_history = []
    approved = False

    # ── Step 1: Create initial schema ────────────────────────────────
    _log("🤖 Agent 1 (Schema Creator): Analyzing text and creating schema...")
    raw_schema = _call_llm(SCHEMA_CREATOR_PROMPT, text, model, base_url, temperature=0.3)
    schema = _parse_json(raw_schema)
    _log("✅ Schema created. Sending to reviewer...")

    # ── Step 2: Review loop ──────────────────────────────────────────
    for iteration in range(1, max_iterations + 1):
        _log(f"🔍 Agent 2 (Schema Reviewer): Reviewing schema (iteration {iteration}/{max_iterations})...")

        reviewer_prompt = SCHEMA_REVIEWER_PROMPT.format(
            schema=json.dumps(schema, indent=2, ensure_ascii=False),
            source_text=text[:8000],  # Truncate very long source text
        )
        raw_review = _call_llm(
            "You are a Schema Reviewer agent. Output only valid JSON.",
            reviewer_prompt,
            model,
            base_url,
            temperature=0.2,
        )
        review = _parse_json(raw_review)
        feedback = review.get("feedback", "")
        approved = review.get("approved", False)
        review_history.append(feedback)

        if approved:
            _log("✅ Schema approved by reviewer!")
            break

        _log(f"❌ Reviewer requested changes. Feedback: {feedback[:200]}...")

        if iteration < max_iterations:
            # ── Step 3: Revise schema based on feedback ───────────────
            _log("🤖 Agent 1 (Schema Creator): Revising schema based on feedback...")
            reviser_prompt = SCHEMA_REVISER_PROMPT.format(
                previous_schema=json.dumps(schema, indent=2, ensure_ascii=False),
                feedback=feedback,
            )
            raw_revised = _call_llm(
                "You are a Schema Creator agent. Output only valid JSON.",
                reviser_prompt,
                model,
                base_url,
                temperature=0.3,
            )
            schema = _parse_json(raw_revised)
            _log("✅ Schema revised. Sending back to reviewer...")
        else:
            _log("⚠️ Max iterations reached. Using last schema.")

    # ── Step 4: Create final Markdown from approved schema ──────────
    _log("🎨 Agent 3 (Mindmap Creator): Converting schema to Markdown...")
    # Use the programmatic converter — it's deterministic and reliable
    markdown = schema_to_markdown(schema)
    _log("✅ Mindmap created!")

    return {
        "markdown": markdown,
        "schema": schema,
        "iterations": len(review_history),
        "review_history": review_history,
        "approved": approved,
    }