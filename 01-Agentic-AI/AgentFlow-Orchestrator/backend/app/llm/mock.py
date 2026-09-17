"""Mock LLM for automated tests.

Provides a simple mock that returns predefined responses
without calling any external LLM API.
"""

from typing import Any


class MockLLM:
    """Mock LLM that returns canned responses for testing.

    Usage:
        mock = MockLLM()
        mock.set_response("Hello", "Hi there!")
        response = await mock.chat("Hello")
    """

    def __init__(self) -> None:
        self._responses: dict[str, str] = {}
        self._default_response: str = "Mock LLM response"
        self._call_count: int = 0

    def set_response(self, prompt_contains: str, response: str) -> None:
        """Set a response for prompts containing a specific string."""
        self._responses[prompt_contains.lower()] = response

    def set_default_response(self, response: str) -> None:
        """Set the default response when no specific match is found."""
        self._default_response = response

    async def chat(self, prompt: str, **kwargs: Any) -> str:
        """Return a mock response based on the prompt."""
        self._call_count += 1
        prompt_lower = prompt.lower()
        for key, response in self._responses.items():
            if key in prompt_lower:
                return response
        return self._default_response

    async def chat_structured(self, prompt: str, schema: type, **kwargs: Any) -> Any:
        """Return a mock structured response.

        For tests, this returns a minimal instance of the schema.
        Override per-test as needed.
        """
        self._call_count += 1
        # Try to create a minimal instance from the schema
        try:
            return schema.model_construct()
        except Exception:
            return None

    @property
    def call_count(self) -> int:
        """Number of times the mock was called."""
        return self._call_count

    def reset(self) -> None:
        """Reset the mock state."""
        self._responses.clear()
        self._call_count = 0
        self._default_response = "Mock LLM response"