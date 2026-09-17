"""Tests for the intent parser."""

from app.planner.intent import parse_intent


class TestParseIntent:
    """Test intent parsing."""

    def test_research_intent(self):
        """Research-type intent is detected."""
        intent = parse_intent("Research five AI testing tools and compare them.")
        assert intent.task_type == "research"
        assert "research" in intent.objective.lower() or "ai testing" in intent.objective.lower()

    def test_data_analysis_intent(self):
        """Data analysis intent is detected."""
        intent = parse_intent("Analyze these Excel files and explain why revenue declined.")
        assert intent.task_type == "data_analysis"

    def test_coding_intent(self):
        """Coding intent is detected."""
        intent = parse_intent("Create a REST API for employee management.")
        assert intent.task_type == "coding"

    def test_qa_intent(self):
        """QA intent is detected."""
        intent = parse_intent("Create automated test cases for this application.")
        assert intent.task_type == "qa"

    def test_document_intent(self):
        """Document intent is detected."""
        intent = parse_intent("Summarize this PDF document and extract key points.")
        assert intent.task_type == "document"

    def test_simple_intent(self):
        """Simple intent is parsed correctly."""
        intent = parse_intent("Convert this CSV into an Excel file.")
        assert intent.raw_text == "Convert this CSV into an Excel file."
        assert intent.objective  # non-empty

    def test_empty_intent(self):
        """Empty intent is handled gracefully."""
        intent = parse_intent("")
        assert intent.task_type == "other"