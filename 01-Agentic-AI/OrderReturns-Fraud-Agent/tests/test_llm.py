"""Tests for app.llm — Phase 5 verification (parser, fallback, wiring).

Unit tests always run and mock the LLM entirely. The single integration test
marked ``@pytest.mark.integration`` hits the real Ollama Cloud endpoint and is
deselected by default (see pytest.ini); run it manually with:
    pytest tests/test_llm.py -m integration
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app import llm as llm_module
from app.llm import (
    CLASSIFICATION_SCHEMA,
    CONDITION_ENUM,
    _fallback_classify,
    build_chat_model,
    classify_reason,
    parse_condition,
)
from app.schemas import ItemCondition


# ---------------------------------------------------------------------------
# parse_condition — tolerant output mapping
# ---------------------------------------------------------------------------
class TestParseCondition:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("damaged_defective", ItemCondition.damaged_defective),
            ("buyer_remorse", ItemCondition.buyer_remorse),
            ('"damaged_defective"', ItemCondition.damaged_defective),
            ("  buyer_remorse  ", ItemCondition.buyer_remorse),
            ('{"condition": "damaged_defective"}', ItemCondition.damaged_defective),
            ('{"condition":"buyer_remorse"}', ItemCondition.buyer_remorse),
        ],
    )
    def test_valid_outputs(self, raw, expected):
        assert parse_condition(raw) is expected

    @pytest.mark.parametrize(
        "raw", ["", "   ", "maybe", "I would say broken but ok", '{"condition": "unknown"}']
    )
    def test_garbage_raises(self, raw):
        with pytest.raises(ValueError):
            parse_condition(raw)

    def test_none_raises(self):
        with pytest.raises(ValueError):
            parse_condition(None)


# ---------------------------------------------------------------------------
# _fallback_classify — keyword stub passthrough
# ---------------------------------------------------------------------------
class TestFallbackClassify:
    def test_damaged_keyword(self):
        assert _fallback_classify("it arrived broken") is ItemCondition.damaged_defective

    def test_remorse_default(self):
        assert _fallback_classify("changed my mind") is ItemCondition.buyer_remorse


# ---------------------------------------------------------------------------
# classify_reason — mocked LLM responses
# ---------------------------------------------------------------------------
def _mock_chat_model(content: object, side_effect: Exception | None = None):
    model = MagicMock()
    if side_effect is not None:
        model.invoke.side_effect = side_effect
    else:
        response = MagicMock()
        response.content = content
        model.invoke.return_value = response
    return model


class TestClassifyReasonMocked:
    def test_valid_enum_response_used(self):
        model = _mock_chat_model("damaged_defective")
        with patch.object(llm_module, "build_chat_model", return_value=model):
            assert classify_reason("screen cracked") is ItemCondition.damaged_defective

    def test_json_object_response_parsed(self):
        model = _mock_chat_model('{"condition": "buyer_remorse"}')
        with patch.object(llm_module, "build_chat_model", return_value=model):
            assert classify_reason("whatever") is ItemCondition.buyer_remorse

    def test_garbage_response_falls_back(self):
        """Unparseable LLM output must not fail the run — keyword fallback."""
        model = _mock_chat_model("total nonsense answer")
        with patch.object(llm_module, "build_chat_model", return_value=model):
            result = classify_reason("the device is not working")
        assert result is ItemCondition.damaged_defective  # keyword fallback caught it

    def test_garbage_response_falls_back_to_remorse(self):
        model = _mock_chat_model("total nonsense answer")
        with patch.object(llm_module, "build_chat_model", return_value=model):
            result = classify_reason("I simply do not want it")
        assert result is ItemCondition.buyer_remorse

    def test_llm_exception_falls_back(self):
        model = _mock_chat_model(None, side_effect=RuntimeError("cloud down"))
        with patch.object(llm_module, "build_chat_model", return_value=model):
            result = classify_reason("arrived broken")
        assert result is ItemCondition.damaged_defective

    def test_missing_api_key_skips_llm(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "OLLAMA_API_KEY", "")
        with patch.object(llm_module, "build_chat_model") as builder:
            result = classify_reason("arrived broken")
        builder.assert_not_called()
        assert result is ItemCondition.damaged_defective

    def test_prompt_contains_reason_text(self):
        model = _mock_chat_model("buyer_remorse")
        with patch.object(llm_module, "build_chat_model", return_value=model):
            classify_reason("wrong size")
        messages = model.invoke.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "damaged_defective" in messages[0]["content"]  # enum in system prompt
        assert "wrong size" in messages[1]["content"]


# ---------------------------------------------------------------------------
# build_chat_model — wiring sanity (no network)
# ---------------------------------------------------------------------------
class TestBuildChatModel:
    def test_returns_chatollama_with_auth_and_schema(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "OLLAMA_API_KEY", "test-key-123")
        monkeypatch.setattr(llm_module.settings, "OLLAMA_MODEL", "test-model")
        monkeypatch.setattr(llm_module.settings, "OLLAMA_BASE_URL", "https://example.com")

        model = build_chat_model()

        assert model.model == "test-model"
        assert model.base_url == "https://example.com"
        headers = model.client_kwargs["headers"]["Authorization"]
        assert headers == "Bearer test-key-123"
        assert model.format == CLASSIFICATION_SCHEMA

    def test_schema_constrains_to_enum(self):
        assert CLASSIFICATION_SCHEMA["properties"]["condition"]["enum"] == list(CONDITION_ENUM)
        assert CONDITION_ENUM == ["damaged_defective", "buyer_remorse"]


# ---------------------------------------------------------------------------
# Integration (live Ollama Cloud) — deselected by default
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestLiveOllamaCloud:
    """Hits the real Ollama Cloud endpoint; requires OLLAMA_API_KEY in .env."""

    def test_live_classification_damaged(self):
        result = classify_reason("The screen arrived shattered and it will not power on")
        assert result is ItemCondition.damaged_defective

    def test_live_classification_remorse(self):
        result = classify_reason("I changed my mind, the color does not match my desk")
        assert result is ItemCondition.buyer_remorse