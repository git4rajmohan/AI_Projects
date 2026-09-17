# Use asyncio so the file can run as both a normal script and a pytest async test.
import asyncio
# Use csv to load the question/reference ground truth from the local CSV file.
import csv
# Use dataclasses to keep config and Aria payloads typed and simple.
from dataclasses import asdict, dataclass, field
# Use html utilities to decode fetched documentation pages into plain text.
import html
# Use json to parse streamed Aria events and normalized Baseten responses.
import json
# Use os to read environment variables from the current process.
import os
# Use re to strip HTML into compact context text.
import re
# Use sys to register a small compatibility shim before importing ragas
# and to reconfigure stdout to UTF-8 so non-ASCII characters from Aria
# answers do not crash on Windows consoles using cp932.
import sys
# Use types to create the compatibility module object dynamically.

# Force UTF-8 on stdout/stderr. On Windows the default codec (cp932) raises
# UnicodeEncodeError when the Aria response contains characters such as the
# em-dash (\u2013) that KB pages routinely include.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    # Python < 3.7 or a stream that cannot be reconfigured - fall back to
    # PYTHONIOENCODING which the operator can set externally.
    pass
import types
# Use Path to locate the local .env file next to this script.
from pathlib import Path
# Use Any for flexible payload handling.
from typing import Any

# Use pytest so the same logic can run as an automated test.
import pytest
# Use requests for the synchronous Aria and source fetch calls.
import requests
# Use dotenv to load the local .env file into the process environment.
from dotenv import load_dotenv
# Use AsyncOpenAI because ragas scoring runs asynchronously against the judge model.
from openai import AsyncOpenAI


# Point to the project-local environment file.
ENV_FILE = Path(__file__).with_name(".env")
# Keep the default CSV ground-truth file configurable at the top of the file.
DEFAULT_DATA_FILE = Path(__file__).with_name("testdata") / "ARIA_data.csv"
# Keep the default question configurable at the top of the file.
DEFAULT_QUESTION = "How many articles are there in the Selenium webdriver python course?"
# Keep the default passing threshold configurable at the top of the file.
DEFAULT_SCORE_THRESHOLD = 0.8
# Keep the number of retrieved contexts used for scoring configurable at the top of the file.
TOP_CONTEXT_COUNT = 3
# Keep the supported OpenAI-compatible completion suffixes configurable at the top of the file.
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")
# Keep the token request timeout configurable at the top of the file.
TOKEN_TIMEOUT_SECONDS = 60
# Keep the inference request timeout configurable at the top of the file.
INFERENCE_TIMEOUT_SECONDS = 120
# Keep the source page fetch timeout configurable at the top of the file.
SOURCE_FETCH_TIMEOUT_SECONDS = 60
# Keep fetched context pages bounded so ragas sees concise passages rather than full documents.
MAX_SOURCE_CONTEXT_CHARS = 3000


# Load settings from .env and force them to override any older shell variables.
load_dotenv(ENV_FILE, override=True)


def ensure_vertexai_compatibility() -> None:
    """Create a lightweight shim for an optional langchain module that ragas still imports."""

    if "langchain_community.chat_models.vertexai" in sys.modules:
        return

    vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass

    vertexai_module.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_module


# Apply the compatibility shim before importing ragas.
ensure_vertexai_compatibility()


# Import the ragas sample container used by the metric call.
from ragas import SingleTurnSample
# Import the modern ragas LLM factory used by collection metrics.
from ragas.llms import llm_factory
# Import the supported modern context precision metric.
from ragas.metrics.collections import ContextPrecisionWithoutReference


@dataclass(frozen=True)
class AppConfig:
    """Store all runtime configuration in one place."""

    llm_api_key: str
    llm_api_endpoint: str
    llm_base_url: str
    token_url: str
    inference_url: str
    license_key: str
    username: str
    password: str
    llm_model: str
    llm_temperature: float
    question: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    top_context_count: int = TOP_CONTEXT_COUNT


@dataclass(frozen=True)
class AriaSource:
    """One KB source returned by Aria."""

    title: str
    url: str


@dataclass(frozen=True)
class AriaAnswerPayload:
    """The Aria answer plus the retrieved contexts used for ragas scoring."""

    answer: str
    sources: list[AriaSource] = field(default_factory=list)
    retrieved_contexts: list[str] = field(default_factory=list)


def get_required_setting(name: str) -> str:
    """Read a required environment value and fail early if it is missing."""

    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def normalize_username(username: str) -> str:
    """Collapse escaped domain separators so credentials match the real login name."""

    return username.replace("\\\\", "\\")


def normalize_openai_base_url(endpoint: str) -> str:
    """Convert a full completions endpoint into the base URL expected by the OpenAI client."""

    normalized_endpoint = endpoint.rstrip("/")
    for suffix in OPENAI_COMPLETION_SUFFIXES:
        if normalized_endpoint.endswith(suffix):
            return normalized_endpoint[: -len(suffix)]
    return normalized_endpoint


def load_config() -> AppConfig:
    """Build the application configuration from top-level environment settings."""

    llm_api_endpoint = get_required_setting("LLM_API_ENDPOINT")
    return AppConfig(
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=llm_api_endpoint,
        llm_base_url=normalize_openai_base_url(llm_api_endpoint),
        token_url=get_required_setting("TOKEN_URL"),
        inference_url=get_required_setting("INFERENCE_URL"),
        license_key=get_required_setting("LICENSE_KEY"),
        username=normalize_username(get_required_setting("USERNAME")),
        password=get_required_setting("PASSWORD"),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        question=os.getenv("QUESTION", DEFAULT_QUESTION),
    )


# Build the shared configuration once at import time.
CONFIG = load_config()


def load_test_data_from_csv(path: Path) -> list[dict[str, str]]:
    """Load question/reference ground-truth rows from a UTF-8 CSV file.

    Expected columns: `question`, `reference`. Extra columns are kept in
    the returned dict but ignored by the scorer. Blank rows are skipped.
    """
    if not path.exists():
        raise FileNotFoundError(f"Test data CSV not found: {path}")

    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "question" not in reader.fieldnames:
            raise ValueError(
                f"CSV at {path} must contain a 'question' column. "
                f"Found columns: {reader.fieldnames}"
            )
        for row in reader:
            question = (row.get("question") or "").strip()
            reference = (row.get("reference") or "").strip()
            if not question:
                continue
            rows.append(
                {"question": question, "reference": reference, **{k: v for k, v in row.items() if k not in ("question", "reference")}}
            )
    if not rows:
        raise ValueError(f"No usable rows found in {path} (need a 'question' column with values).")
    return rows


def build_config_for_row(base: AppConfig, row: dict[str, str]) -> AppConfig:
    """Return a copy of `base` with the question swapped to the CSV row's question."""
    return AppConfig(**{**asdict(base), "question": row["question"]})


def normalize_response_content(response: Any) -> Any:
    """Move Baseten structured output into message.content so ragas can parse it."""

    for choice in getattr(response, "choices", []):
        message = getattr(choice, "message", None)
        if message is None:
            continue

        content = getattr(message, "content", None)
        reasoning_content = getattr(message, "reasoning_content", None)

        if not content and reasoning_content:
            content = reasoning_content.strip()

        if not content:
            continue

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            message.content = content
            continue

        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            message.content = json.dumps(parsed[0])
        elif isinstance(parsed, dict):
            message.content = json.dumps(parsed)
        else:
            message.content = content

    return response


def patch_async_client_for_baseten(client: AsyncOpenAI) -> AsyncOpenAI:
    """Patch the async client so Baseten responses look like standard OpenAI responses."""

    original_create = client.chat.completions.create

    async def create_with_normalized_content(*args, **kwargs):
        response = await original_create(*args, **kwargs)
        return normalize_response_content(response)

    client.chat.completions.create = create_with_normalized_content
    return client


def build_async_client(config: AppConfig) -> AsyncOpenAI:
    """Create and patch the OpenAI-compatible async client used by ragas."""

    client = AsyncOpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    return patch_async_client_for_baseten(client)


def build_metric(config: AppConfig) -> ContextPrecisionWithoutReference:
    """Create the ragas context precision metric using the Baseten judge model."""

    client = build_async_client(config)
    llm = llm_factory(
        config.llm_model,
        client=client,
        temperature=config.llm_temperature,
    )
    return ContextPrecisionWithoutReference(llm=llm)


def extract_text_from_payload(payload: Any) -> str:
    """Extract assistant text from a range of possible response shapes."""

    if isinstance(payload, str):
        return payload

    if isinstance(payload, dict):
        for key in (
            "content",
            "text",
            "answer",
            "response",
            "output",
            "message",
            "generated_text",
            "completion",
            "reasoning_content",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        for key in ("data", "result", "results", "choices", "messages", "conversation", "items"):
            if key in payload:
                extracted = extract_text_from_payload(payload[key])
                if extracted:
                    return extracted

        for value in payload.values():
            extracted = extract_text_from_payload(value)
            if extracted:
                return extracted

    if isinstance(payload, list):
        for item in payload:
            extracted = extract_text_from_payload(item)
            if extracted:
                return extracted

    return ""


def html_to_text(markup: str) -> str:
    """Convert a fetched HTML page into a compact plain-text snippet."""

    without_scripts = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.IGNORECASE)
    without_styles = re.sub(r"<style[\s\S]*?</style>", " ", without_scripts, flags=re.IGNORECASE)
    without_tags = re.sub(r"<[^>]+>", " ", without_styles)
    normalized = html.unescape(without_tags)
    compact = re.sub(r"\s+", " ", normalized).strip()
    return compact[:MAX_SOURCE_CONTEXT_CHARS]


def fetch_source_context(source: AriaSource) -> str:
    """Fetch one Aria KB source URL and convert it into a ragas context string."""

    response = requests.get(source.url, timeout=SOURCE_FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    text = html_to_text(response.text)
    if source.title:
        return f"{source.title}\n{text}"
    return text


class AriaClient:
    """Minimal Aria client used for answer generation and source lookup."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._access_token: str | None = None

    def _get_token_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _get_inference_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        response = requests.post(
            self.config.token_url,
            headers=self._get_token_headers(),
            data={
                "username": f"{self.config.license_key}|user:{self.config.username}",
                "password": self.config.password,
                "create": "account,user",
            },
            timeout=TOKEN_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        for key in ("access_token", "token", "jwt", "id_token"):
            token = payload.get(key)
            if token:
                self._access_token = token
                return token

        raise ValueError("Aria token response did not include an access token.")

    def _build_inference_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "user_message": prompt,
            "mode": "flash",
        }

    def ask_with_sources(self, prompt: str, top_context_count: int) -> AriaAnswerPayload:
        """Ask Aria one question and convert returned KB sources into retrieved contexts."""

        response = requests.post(
            self.config.inference_url,
            json=self._build_inference_payload(prompt),
            headers=self._get_inference_headers(),
            stream=False,
            timeout=INFERENCE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        buffer = ""
        final_content = ""
        final_sources: dict[str, dict[str, str]] = {}

        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue

            buffer += chunk
            while "\x00" in buffer:
                part, buffer = buffer.split("\x00", 1)
                part = part.strip()
                if not part:
                    continue

                try:
                    payload = json.loads(part)
                except json.JSONDecodeError:
                    continue

                event = payload.get("event", {})
                data = event.get("data", {}) or {}
                sources = data.get("sources", {}) or {}
                if isinstance(sources, dict):
                    final_sources.update(sources)

                if event.get("type") == "response":
                    final_content = data.get("content", final_content)

        if not final_content:
            final_content = extract_text_from_payload(response.json())

        sources = [
            AriaSource(title=item.get("title", ""), url=item.get("url", ""))
            for item in final_sources.values()
        ]

        retrieved_contexts: list[str] = []
        for source in sources[:top_context_count]:
            if not source.url:
                continue
            try:
                retrieved_contexts.append(fetch_source_context(source))
            except requests.RequestException:
                fallback_text = "\n".join(part for part in (source.title, source.url) if part)
                if fallback_text:
                    retrieved_contexts.append(fallback_text)

        if not retrieved_contexts and final_content:
            retrieved_contexts.append(final_content)

        return AriaAnswerPayload(
            answer=final_content,
            sources=sources,
            retrieved_contexts=retrieved_contexts,
        )


def build_answer_prompt(question: str) -> str:
    """Build the Aria prompt used to answer the question from the knowledge base."""

    return question


async def fetch_aria_answer_payload(config: AppConfig, aria_client: AriaClient) -> AriaAnswerPayload:
    """Ask Aria for the answer and the KB contexts that will be judged by ragas."""

    prompt = build_answer_prompt(config.question)
    return await asyncio.to_thread(aria_client.ask_with_sources, prompt, config.top_context_count)


def build_sample(config: AppConfig, aria_response: AriaAnswerPayload) -> SingleTurnSample:
    """Convert the Aria response into the ragas sample object used for scoring."""

    return SingleTurnSample(
        user_input=config.question,
        response=aria_response.answer,
        retrieved_contexts=aria_response.retrieved_contexts[: config.top_context_count],
    )


async def calculate_context_precision(
    config: AppConfig,
    metric: ContextPrecisionWithoutReference,
    sample: SingleTurnSample,
) -> float:
    """Run the built-in ragas metric and return only the numeric score value."""

    score = await metric.ascore(
        user_input=sample.user_input,
        response=sample.response,
        retrieved_contexts=sample.retrieved_contexts,
    )
    return score.value


async def run_context_precision(config: AppConfig = CONFIG) -> float:
    """Execute the Aria RAG plus Baseten judge workflow."""

    os.environ["OPENAI_API_KEY"] = config.llm_api_key
    metric = build_metric(config)
    aria_client = AriaClient(config)
    aria_response = await fetch_aria_answer_payload(config, aria_client)
    print(asdict(aria_response))
    sample = build_sample(config, aria_response)

    try:
        score = await calculate_context_precision(config, metric, sample)
    except Exception as exc:
        print(
            "Aria retrieval or Baseten ragas scoring failed. Check LLM_API_ENDPOINT, OPENAI_API_KEY, TOKEN_URL, INFERENCE_URL, and LLM_MODEL in .env."
        )
        print(f"Configured Aria endpoint: {config.inference_url}")
        print(f"Configured judge endpoint: {config.llm_base_url}")
        print(f"Configured model: {config.llm_model}")
        raise exc

    print(score)
    return score


async def run_context_precision_for_rows(
    base_config: AppConfig,
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Run the Aria + ragas pipeline once per CSV row and collect per-row results.

    Each result row is shaped like:
        {
            "index": int,
            "question": str,
            "reference": str,
            "answer": str,
            "score": float | None,
            "error": str | None,
        }
    """
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        per_row_config = build_config_for_row(base_config, row)
        print()
        print("=" * 80)
        print(f"[{index}/{len(rows)}] {row['question']}")
        print("=" * 80)
        entry: dict[str, Any] = {
            "index": index,
            "question": row["question"],
            "reference": row.get("reference", ""),
            "answer": "",
            "score": None,
            "error": None,
        }
        try:
            os.environ["OPENAI_API_KEY"] = per_row_config.llm_api_key
            metric = build_metric(per_row_config)
            aria_client = AriaClient(per_row_config)
            aria_response = await fetch_aria_answer_payload(per_row_config, aria_client)
            entry["answer"] = aria_response.answer
            print(f"Aria answer: {aria_response.answer}")
            sample = build_sample(per_row_config, aria_response)
            score = await calculate_context_precision(per_row_config, metric, sample)
            entry["score"] = float(score)
            print(f"Context precision score: {score}")
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"FAILED: {entry['error']}")
        results.append(entry)
    return results


def summarize_results(results: list[dict[str, Any]], threshold: float) -> None:
    """Print a compact summary table plus the average score."""
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    scored = [r["score"] for r in results if r["score"] is not None]
    avg = sum(scored) / len(scored) if scored else 0.0
    passed = sum(1 for r in results if r["score"] is not None and r["score"] > threshold)
    failed_rows = [r for r in results if r["score"] is not None and r["score"] <= threshold]
    error_rows = [r for r in results if r["error"]]

    for r in results:
        status = "ERR " if r["error"] else ("PASS" if (r["score"] or 0) > threshold else "FAIL")
        score_str = f"{r['score']:.4f}" if r["score"] is not None else "-"
        print(f"  #{r['index']:<2}  {status}  score={score_str}  q={r['question'][:70]}")
    print()
    print(f"Total rows : {len(results)}")
    print(f"Scored     : {len(scored)}")
    print(f"Passed     : {passed}")
    print(f"Failed     : {len(failed_rows)}")
    print(f"Errors     : {len(error_rows)}")
    print(f"Average    : {avg:.4f}")
    print(f"Threshold  : {threshold}")


@pytest.mark.asyncio
async def test_context_precision() -> None:
    """Pytest entry point that validates the score stays above the configured threshold.

    When `ARIA_DATA_FILE` env var points to a CSV with multiple rows, the
    average score across all rows must exceed the configured threshold.
    Otherwise the single-env-var question is used.
    """
    data_path = Path(os.getenv("ARIA_DATA_FILE", str(DEFAULT_DATA_FILE)))
    if data_path.exists():
        rows = load_test_data_from_csv(data_path)
        results = await run_context_precision_for_rows(CONFIG, rows)
        scored = [r["score"] for r in results if r["score"] is not None]
        assert scored, "No rows produced a score"
        avg = sum(scored) / len(scored)
        assert avg > CONFIG.score_threshold, f"Average score {avg} below threshold {CONFIG.score_threshold}"
    else:
        score = await run_context_precision()
        assert score > CONFIG.score_threshold


def main() -> int:
    """Run the script directly and return a shell-friendly exit code.

    Honors these CLI flags:
        --data <path>   Path to the question/reference CSV.
                        Defaults to testdata/ARIA_data.csv.
        --question <q>  Single question to evaluate (skips CSV loading).
    If neither flag is provided, falls back to ARIA_DATA_FILE env var,
    then to the default CSV path.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Run Test1 context precision over a CSV of questions.")
    parser.add_argument("--data", type=Path, default=None, help="Path to CSV with question,reference columns.")
    parser.add_argument("--question", type=str, default=None, help="Run a single question (skip CSV).")
    args = parser.parse_args()

    if args.question is not None:
        # Single-question mode: keep original behaviour.
        try:
            asyncio.run(run_context_precision())
        except Exception:
            print("No score produced.")
            return 1
        return 0

    data_path = args.data or Path(os.getenv("ARIA_DATA_FILE", str(DEFAULT_DATA_FILE)))
    try:
        rows = load_test_data_from_csv(data_path)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    except ValueError as exc:
        print(str(exc))
        return 1

    print(f"Loaded {len(rows)} row(s) from {data_path}")

    try:
        results = asyncio.run(run_context_precision_for_rows(CONFIG, rows))
    except Exception:
        print("No score produced.")
        return 1

    summarize_results(results, CONFIG.score_threshold)
    # Non-zero exit if any row failed or errored so CI can pick it up.
    any_failure = any(
        r["error"] is not None or (r["score"] is not None and r["score"] <= CONFIG.score_threshold)
        for r in results
    )
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
