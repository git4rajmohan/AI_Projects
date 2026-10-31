"""Card validator tests against the installed a2a-sdk 1.3.0 schema."""
import pytest

from remote_agents.card_validator import CardValidationError, summarize_card, validate_card

URL = "https://agent.example/.well-known/agent-card.json"


def good_card() -> dict:
    return {
        "name": "Research Agent",
        "description": "Performs research tasks",
        "version": "1.0.0",
        "supported_interfaces": [
            {"url": "https://agent.example/a2a", "protocol_binding": "JSONRPC", "protocol_version": "1.0"}
        ],
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "capabilities": {"streaming": True},
        "skills": [{"id": "web-research", "name": "Web Research", "description": "Researches a topic", "tags": ["r"]}],
    }


def test_valid_card_parses():
    vc = validate_card(good_card(), URL)
    assert vc.card.name == "Research Agent"
    assert vc.card.skills[0].id == "web-research"
    assert vc.source_url == URL
    assert vc.fetched_at is not None


def test_unknown_fields_retained_without_error():
    data = good_card()
    data["x_custom_extension"] = {"anything": 1}
    assert validate_card(data, URL).card.name == "Research Agent"


def test_non_card_json_rejected():
    with pytest.raises(CardValidationError, match="not a compatible A2A endpoint"):
        validate_card({"title": "My Blog", "posts": []}, URL)


def test_missing_endpoint_rejected():
    data = good_card()
    data["supported_interfaces"] = []
    with pytest.raises(CardValidationError):
        validate_card(data, URL)


def test_missing_skills_rejected_clearly():
    # skills is REQUIRED in the a2a-sdk 1.3.0 schema
    data = good_card()
    del data["skills"]
    with pytest.raises(CardValidationError, match="skills"):
        validate_card(data, URL)


def test_summary_shows_key_fields():
    text = summarize_card(validate_card(good_card(), URL))
    for expected in ("Research Agent", "https://agent.example/a2a", "web-research", URL):
        assert expected in text
