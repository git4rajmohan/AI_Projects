"""Tests for the Tool Registry and built-in tools."""

import os
import tempfile

import pytest

from app.tools.registry import Tool, ToolNotFoundError, ToolRegistry, get_registry
from app.models.tool_schema import ToolSpec


class TestToolRegistry:
    """Test the ToolRegistry class."""

    def test_register_and_get(self):
        """Register a tool and retrieve it."""
        registry = ToolRegistry()

        class DummyTool(Tool):
            def __init__(self):
                super().__init__(ToolSpec(id="dummy", name="Dummy", description="A dummy tool"))

            async def execute(self, **params):
                return {"success": True, "output": {"echo": params}, "error": None}

        tool = DummyTool()
        registry.register(tool)

        assert registry.has("dummy")
        retrieved = registry.get("dummy")
        assert retrieved.id == "dummy"
        assert retrieved.name == "Dummy"

    def test_get_not_found(self):
        """Getting a non-existent tool raises ToolNotFoundError."""
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            registry.get("nonexistent")

    def test_list(self):
        """List returns all registered tool specs."""
        registry = ToolRegistry()

        class Tool1(Tool):
            def __init__(self):
                super().__init__(ToolSpec(id="t1", name="Tool 1", description="Tool 1"))

            async def execute(self, **params):
                pass

        class Tool2(Tool):
            def __init__(self):
                super().__init__(ToolSpec(id="t2", name="Tool 2", description="Tool 2"))

            async def execute(self, **params):
                pass

        registry.register(Tool1())
        registry.register(Tool2())

        specs = registry.list()
        assert len(specs) == 2
        ids = [s.id for s in specs]
        assert "t1" in ids
        assert "t2" in ids

    def test_remove(self):
        """Remove a tool from the registry."""
        registry = ToolRegistry()

        class DummyTool(Tool):
            def __init__(self):
                super().__init__(ToolSpec(id="removable", name="Removable", description="Removable tool"))

            async def execute(self, **params):
                pass

        registry.register(DummyTool())
        assert registry.has("removable")

        registry.remove("removable")
        assert not registry.has("removable")

    def test_clear(self):
        """Clear removes all tools."""
        registry = ToolRegistry()

        class T(Tool):
            def __init__(self):
                super().__init__(ToolSpec(id="t", name="T", description="T"))

            async def execute(self, **params):
                pass

        registry.register(T())
        registry.clear()
        assert len(registry.list()) == 0


class TestBuiltinTools:
    """Test that built-in tools are registered and work."""

    def test_registry_has_all_builtins(self):
        """The singleton registry has all 6 built-in tools."""
        registry = get_registry()
        tool_ids = [t.id for t in registry.list()]

        expected = ["file_reader", "file_writer", "python_executor", "calculator", "http_request", "web_search"]
        for tid in expected:
            assert tid in tool_ids, f"Missing built-in tool: {tid}"

    @pytest.mark.asyncio
    async def test_file_reader(self):
        """FileReader reads a file correctly."""
        registry = get_registry()
        tool = registry.get("file_reader")

        # Create a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello, AgentOS!")
            temp_path = f.name

        try:
            result = await tool.execute(path=temp_path)
            assert result["success"]
            assert result["output"]["content"] == "Hello, AgentOS!"
            assert result["output"]["truncated"] is False
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_file_reader_not_found(self):
        """FileReader returns error for non-existent file."""
        registry = get_registry()
        tool = registry.get("file_reader")

        result = await tool.execute(path="/nonexistent/path/file.txt")
        assert not result["success"]
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_file_writer(self):
        """FileWriter writes content to a file."""
        registry = get_registry()
        tool = registry.get("file_writer")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.txt")
            result = await tool.execute(path=path, content="Written by AgentOS!")

            assert result["success"]
            assert os.path.exists(path)
            with open(path, "r", encoding="utf-8") as f:
                assert f.read() == "Written by AgentOS!"

    @pytest.mark.asyncio
    async def test_calculator(self):
        """Calculator evaluates math expressions."""
        registry = get_registry()
        tool = registry.get("calculator")

        result = await tool.execute(expression="2 + 3 * 4")
        assert result["success"]
        assert result["output"]["result"] == 14

    @pytest.mark.asyncio
    async def test_calculator_with_parens(self):
        """Calculator respects parentheses."""
        registry = get_registry()
        tool = registry.get("calculator")

        result = await tool.execute(expression="(2 + 3) * 4")
        assert result["success"]
        assert result["output"]["result"] == 20

    @pytest.mark.asyncio
    async def test_calculator_power(self):
        """Calculator supports exponentiation."""
        registry = get_registry()
        tool = registry.get("calculator")

        result = await tool.execute(expression="2 ** 10")
        assert result["success"]
        assert result["output"]["result"] == 1024

    @pytest.mark.asyncio
    async def test_calculator_invalid(self):
        """Calculator rejects invalid expressions."""
        registry = get_registry()
        tool = registry.get("calculator")

        result = await tool.execute(expression="import os; os.system('rm -rf /')")
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_python_executor(self):
        """PythonExecutor runs code and returns output."""
        registry = get_registry()
        tool = registry.get("python_executor")

        result = await tool.execute(code="print('Hello from Python!')")
        assert result["success"]
        assert "Hello from Python!" in result["output"]["stdout"]
        assert result["output"]["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_python_executor_error(self):
        """PythonExecutor captures stderr."""
        registry = get_registry()
        tool = registry.get("python_executor")

        result = await tool.execute(code="import sys; sys.stderr.write('error msg\\n'); sys.exit(1)")
        assert not result["success"]
        assert result["output"]["exit_code"] == 1
        assert "error msg" in result["output"]["stderr"]

    @pytest.mark.asyncio
    async def test_python_executor_blocks_network_imports(self):
        """PythonExecutor rejects code that imports networking modules (must use web_search/http_request instead)."""
        registry = get_registry()
        tool = registry.get("python_executor")

        for code in [
            "import requests\nrequests.get('http://example.com')",
            "import urllib.request\nurllib.request.urlopen('http://example.com')",
            "from httpx import Client",
            "import socket\nsocket.socket()",
        ]:
            result = await tool.execute(code=code)
            assert not result["success"]
            assert "web_search" in result["error"] or "http_request" in result["error"]

    @pytest.mark.asyncio
    async def test_python_executor_allows_normal_code(self):
        """PythonExecutor still runs ordinary non-networking code fine."""
        registry = get_registry()
        tool = registry.get("python_executor")

        result = await tool.execute(code="import math\nprint(math.sqrt(16))")
        assert result["success"]
        assert "4.0" in result["output"]["stdout"]

    @pytest.mark.asyncio
    async def test_web_search_no_key(self, monkeypatch):
        """WebSearch returns placeholder when no API key is set."""
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        registry = get_registry()
        tool = registry.get("web_search")

        result = await tool.execute(query="AI testing tools")
        assert result["success"]
        assert "note" in result["output"]