import pytest
from ragas import SingleTurnSample, MultiTurnSample
from ragas.messages import HumanMessage, AIMessage
# Newer "collections" API returns MetricResult with .value and .reason,
# which lets us explain the score in the UI. (The older ragas.metrics.*
# classes return raw floats and don't expose per-metric reasoning.)
from ragas.metrics.collections import (
    AgentGoalAccuracy,
    Faithfulness,
    TopicAdherence,
)

from utils import load_test_data, get_llm_response


# ============================================================================
# CONFIG  -  tweak any of these values and re-run the test.
# Every value you might want to swap lives in this single block. Nothing
# below this line needs to be edited to change behaviour.
# ============================================================================
CONFIG = {
    # ---- Pass / fail thresholds (0.0 - 1.0). All three must be exceeded. ----
    "score_thresholds": {
        "topic_adherence": 0.8,
        "agent_goal_accuracy": 0.8,
        "faithfulness": 0.8,
    },

    # ---- The multi-turn conversation the AI had with the user. ------------
    # Add/remove HumanMessage / AIMessage entries freely.
    "conversation": [
        HumanMessage(
            content="how many articles are there in the selenium webdriver python course?"
        ),
        AIMessage(
            content="There are 23 articles in the Selenium WebDriver Python course."
        ),
        HumanMessage(
            content="How many downloadable resources are there in this course?"
        ),
        AIMessage(
            content="There are 9 downloadable resources in the course."
        ),
    ],

    # ---- Reference topics the AI is expected to stick to. -----------------
    # Used by Topic Adherence. Each entry is one topic the AI should cover.
    "reference_topics": [
        """
        The AI should:
        1. Give results related to the selenium webdriver python course
        2. There are 23 articles and 9 downloadable resources in the course
        """
    ],

    # ---- The user's overall goal for the conversation. --------------------
    # Used by Agent Goal Accuracy. One short sentence is enough.
    "agent_goal": (
        "Tell the user that the Selenium WebDriver Python course has "
        "23 articles and 9 downloadable resources."
    ),

    # ---- Optional: pytest parametrize source ------------------------------
    # Set to a filename under testdata/ to run the test once per row in
    # that file (each row replaces the conversation in CONFIG). Set to
    # None to use the hard-coded conversation above.
    #   e.g. "Test4.json"  ->  reads testdata/Test4.json
    #         None         ->  uses the conversation above
    "parametrize_source": None,
}
# ============================================================================


# ============================================================================
# What this test does (in plain English):
#
# A RAG system is a "chatbot that looks things up before answering".
# This test runs three RAGAS metrics on a multi-turn conversation:
#   1. Topic Adherence     - did the AI stay on the expected topics?
#   2. Agent Goal Accuracy - did the AI achieve the user's overall goal?
#   3. Faithfulness        - were the AI's replies grounded in the chat?
#
# The test PASSES only when all three scores are above their thresholds
# (defined in CONFIG at the top of this file).
#
# How to run:
#   .\.venv\Scripts\python.exe -m pytest Test6.py -v -s
# ============================================================================


# ============================================================================
# Small helpers - everything below reads from CONFIG, so swapping values
# in CONFIG is enough to change behaviour.
# ============================================================================
def _thresholds() -> dict[str, float]:
    """Return the score thresholds from CONFIG, with a safe default."""
    return CONFIG.get("score_thresholds") or {
        "topic_adherence": 0.8,
        "agent_goal_accuracy": 0.8,
        "faithfulness": 0.8,
    }


def _build_sample() -> MultiTurnSample:
    """Build the RAGAS MultiTurnSample from CONFIG."""
    return MultiTurnSample(
        user_input=CONFIG["conversation"],
        reference_topics=CONFIG["reference_topics"],
        reference=CONFIG["agent_goal"],
    )


def _extract_score_and_reason(result) -> tuple[float, str]:
    """RAGAS metrics return either a MetricResult (with .value and .reason)
    or a raw scalar (numpy / float). This helper normalises both shapes."""
    if hasattr(result, "value"):
        score = float(result.value)
    else:
        score = float(result)
    reason = str(getattr(result, "reason", "") or "").strip()
    return score, reason


async def _score_topic_adherence(llm_wrapper, sample: MultiTurnSample) -> dict:
    """Run the Topic Adherence metric on the whole conversation.

    Returns a dict with:
        score  : float  - the metric value
        reason : str    - the judge LLM's explanation (empty if not provided)
        ok     : bool   - True if score > 0.8
    """
    metric = TopicAdherence(llm=llm_wrapper)
    result = await metric.ascore(
        user_input=sample.user_input,
        reference_topics=sample.reference_topics,
    )
    score, reason = _extract_score_and_reason(result)
    return {"score": score, "reason": reason, "ok": score > 0.8}


async def _score_agent_goal_accuracy(
    llm_wrapper, sample: MultiTurnSample
) -> dict:
    """Run the Agent Goal Accuracy metric against the configured goal.

    Returns the same {score, reason, ok} shape as the other helpers.
    """
    metric = AgentGoalAccuracy(llm=llm_wrapper)
    result = await metric.ascore(
        user_input=sample.user_input,
        reference=sample.reference,
    )
    score, reason = _extract_score_and_reason(result)
    return {"score": score, "reason": reason, "ok": score > 0.8}


async def _score_faithfulness(
    llm_wrapper, conversation: list
) -> dict:
    """Score each AI turn for faithfulness, then average.

    Returns a dict with:
        average  : float                                       - the averaged score
        per_turn : list of {index, role, content, score, reason} for each AI turn
        reason   : str                                          - a short summary of
                                                                   the per-turn reasons
        ok       : bool                                         - True if average > 0.8
    """
    metric = Faithfulness(llm=llm_wrapper)
    # Use the whole conversation as the "retrieved context" so the judge
    # LLM has something to ground the AI's claims against.
    full_conversation_text = " ".join(
        message.content for message in conversation
    )
    per_turn: list[dict] = []
    per_turn_scores: list[float] = []
    for turn_index, message in enumerate(conversation):
        if not isinstance(message, AIMessage):
            continue  # only score AI replies, not user questions
        preceding_user_message = next(
            (
                previous.content
                for previous in conversation[:turn_index]
                if isinstance(previous, HumanMessage)
            ),
            message.content,
        )
        result = await metric.ascore(
            user_input=preceding_user_message,
            response=message.content,
            retrieved_contexts=[full_conversation_text],
        )
        turn_score, turn_reason = _extract_score_and_reason(result)
        per_turn_scores.append(turn_score)
        per_turn.append({
            "index": turn_index,
            "role": "assistant",
            "content": message.content,
            "score": turn_score,
            "reason": turn_reason,
        })

    average = (
        sum(per_turn_scores) / len(per_turn_scores) if per_turn_scores else 0.0
    )
    # Build a compact summary reason out of the per-turn reasons.
    if per_turn:
        reason_lines = [
            f"Turn {t['index'] + 1}: {t['reason'] or '(no reason returned)'}"
            for t in per_turn
        ]
        reason = "\n".join(reason_lines)
    else:
        reason = ""
    return {"average": average, "per_turn": per_turn, "reason": reason, "ok": average > 0.8}


def _print_results(
    topic_score: float,
    agent_goal_score: float,
    faithfulness_score: float,
    thresholds: dict[str, float],
) -> str:
    """Print the three scores + the verdict, and return the verdict string."""
    print("Test started")
    print(f"topic adherence score is {topic_score}")
    print(f"agent goal accuracy score is {agent_goal_score}")
    print(f"faithfulness score is {faithfulness_score}")

    topic_ok = topic_score > thresholds["topic_adherence"]
    agent_ok = agent_goal_score > thresholds["agent_goal_accuracy"]
    faithful_ok = faithfulness_score > thresholds["faithfulness"]

    verdict = "PASS" if (topic_ok and agent_ok and faithful_ok) else "FAIL"
    print(f"test result: {verdict}")
    print("test ended")
    return verdict


# ============================================================================
# Pytest fixture  -  builds the RAGAS sample from CONFIG
# ============================================================================
@pytest.fixture
def getData():
    """Build the multi-turn sample from CONFIG. If CONFIG['parametrize_source']
    is set, pytest will call this fixture once per row in that JSON file.
    Otherwise the hard-coded conversation in CONFIG is used."""
    return _build_sample()


# Optional parametrize hook: if CONFIG['parametrize_source'] is set,
# re-decorate getData so pytest runs the test once per JSON row.
_PARAM_SOURCE = CONFIG.get("parametrize_source")
if _PARAM_SOURCE:
    _TEST_ROWS = load_test_data(_PARAM_SOURCE)
    getData = pytest.mark.parametrize(
        "getData", _TEST_ROWS, indirect=True
    )(getData)


# The line below is "commented out" - if you uncomment it, the test will
# automatically run once for every row in testdata/Test4.json (each row
# becomes its own test case). For this file we just use a hard-coded chat
# inside the getData fixture below, so this stays disabled.
#@pytest.mark.parametrize("getData", load_test_data("Test4.json"), indirect=True)
@pytest.mark.asyncio
async def test_topicAdherence(llm_wrapper, getData):
    thresholds = _thresholds()

    # 1) Topic adherence across the whole conversation.
    topic_result = await _score_topic_adherence(llm_wrapper, getData)
    topic_score = topic_result["score"]

    # 2) Agent goal accuracy (did the AI achieve the user's overall goal?).
    agent_result = await _score_agent_goal_accuracy(llm_wrapper, getData)
    agent_goal_score = agent_result["score"]

    # 3) Per-turn faithfulness, then averaged.
    faithfulness_result = await _score_faithfulness(llm_wrapper, getData.user_input)
    faithfulness_score = faithfulness_result["average"]

    # Print the final result and decide PASS / FAIL.
    verdict = _print_results(
        topic_score, agent_goal_score, faithfulness_score, thresholds
    )

    # Pytest assertions: the test only goes green if every score passes.
    assert topic_score > thresholds["topic_adherence"], (
        f"Topic adherence too low: {topic_score} "
        f"(threshold {thresholds['topic_adherence']})"
    )
    assert agent_goal_score > thresholds["agent_goal_accuracy"], (
        f"Agent goal accuracy too low: {agent_goal_score} "
        f"(threshold {thresholds['agent_goal_accuracy']})"
    )
    assert faithfulness_score > thresholds["faithfulness"], (
        f"Faithfulness too low: {faithfulness_score} "
        f"(threshold {thresholds['faithfulness']})"
    )
