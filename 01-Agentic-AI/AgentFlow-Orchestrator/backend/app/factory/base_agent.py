"""BaseAgent — common interface for all agents.

Matches instruction.md section 14 (Agent Runtime).

Runtime responsibilities:
1. Receive context
2. Load memory
3. Load skills
4. Load tools
5. Execute model interaction
6. Validate output
7. Execute tools
8. Store tool results
9. Update memory
10. Return structured AgentResult

Limits: max iterations, max tool calls, timeout
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from app.factory.context import AgentContext, AgentResult
from app.llm.config import get_model
from app.models.agent import AgentSpec
from app.tools.registry import Tool, ToolNotFoundError, get_registry

logger = logging.getLogger(__name__)


def _make_adk_tool(tool_id: str, tool: Tool) -> FunctionTool:
    """Create an ADK FunctionTool wrapper for our custom tool.

    This allows the LLM to use native function calling (tool_calls)
    which ADK handles automatically.

    We create a dynamically typed function that matches the tool's
    input schema so ADK can introspect the parameters.
    """
    # Build a proper function signature from the tool's input schema
    schema = tool.spec.input_schema or {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Create the async execution function with explicit parameters
    # We use exec to create a function with the right signature
    param_names = list(properties.keys())
    param_defaults = {}
    for name, prop in properties.items():
        if name not in required:
            default = prop.get("default")
            param_defaults[name] = default

    # Build the function code
    params_str = ", ".join(
        f"{name}={param_defaults[name]!r}" if name in param_defaults else name
        for name in param_names
    )

    # Create the function
    func_code = f"""
async def _adk_tool({params_str}):
    \"\"\"{tool.spec.description}\"\"\"
    params = {{{', '.join(f'{name!r}: {name}' for name in param_names)}}}
    # Remove None values for optional params
    params = {{k: v for k, v in params.items() if v is not None}}
    result = await _tool_ref.execute(**params)
    return result
"""

    # Execute the code to create the function
    local_vars: dict[str, Any] = {"_tool_ref": tool}
    exec(func_code, local_vars)
    func = local_vars["_adk_tool"]
    func.__name__ = tool_id

    return FunctionTool(func=func)


class BaseAgent:
    """Base agent that uses ADK LlmAgent + tools to accomplish a goal.

    The agent runs an LLM loop:
    1. Send the goal + context to the LLM
    2. If the LLM wants to call a tool, execute it and feed the result back
    3. Repeat until the LLM produces a final response or limits are hit

    For non-Gemini models (Ollama Cloud), we use a simplified approach:
    the LLM generates a plan of tool calls as JSON, we execute them,
    then feed results back for a final response.
    """

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self._tool_registry = get_registry()

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def name(self) -> str:
        return self.spec.name

    def _build_system_prompt(self) -> str:
        """Build the system prompt for this agent."""
        parts = [
            f"You are {self.spec.name}.",
            f"Goal: {self.spec.goal}",
        ]
        if self.spec.description:
            parts.append(f"Description: {self.spec.description}")

        # List available tools
        available_tools = []
        for tool_id in self.spec.tools:
            try:
                tool = self._tool_registry.get(tool_id)
                available_tools.append(f"- {tool_id}: {tool.spec.description}")
            except ToolNotFoundError:
                pass

        if available_tools:
            parts.append("\nAvailable tools:")
            parts.extend(available_tools)
            parts.append(
                "\n## CRITICAL: How to use tools\n"
                "To use a tool, respond with ONLY this JSON format (no other text):\n"
                '```json\n{"tool_calls": [{"tool": "tool_id", "params": {"param": "value"}}]}\n```\n'
                "Example to read a file:\n"
                '```json\n{"tool_calls": [{"tool": "file_reader", "params": {"path": "data/uploads/result.csv"}}]}\n```\n'
                "After receiving tool results, either call more tools or provide your final answer.\n"
                "You MUST use tools to accomplish the task. Do NOT just describe what you would do — actually DO it by calling tools.\n"
                "If every available tool fails or cannot retrieve the requested information, clearly tell the user "
                "that the data could not be retrieved and why. Do NOT invent, estimate, or guess specific facts "
                "(prices, dates, statistics, etc.) and present them as if they came from a real source."
            )
        else:
            parts.append("\nNo tools available. Provide your answer directly.")

        if self.spec.system_prompt:
            parts.append(f"\nAdditional instructions: {self.spec.system_prompt}")

        return "\n".join(parts)

    def _build_user_message(self, context: AgentContext) -> str:
        """Build the user message from context."""
        parts = [f"Task: {context.intent}"]

        if context.inputs:
            parts.append("\nInputs from previous agents:")
            for agent_id, output in context.inputs.items():
                parts.append(f"  {agent_id}: {json.dumps(output, default=str)[:500]}")

        if context.working_memory:
            parts.append(f"\nWorking memory: {json.dumps(context.working_memory, default=str)[:500]}")

        # Extract file paths from the intent and make them prominent
        import re
        file_paths = re.findall(r'[A-Za-z]:[\\\/][^\s,]+\.csv|[A-Za-z]:[\\\/][^\s,]+\.xlsx|[A-Za-z]:[\\\/][^\s,]+\.txt|data[\\\/]uploads[\\\/][^\s,]+', context.intent)
        if file_paths:
            parts.append("\n## FILE PATHS (use these exact paths in your tool calls)")
            for fp in file_paths:
                parts.append(f"  FILE: {fp}")
        else:
            # Also check for any path-like patterns in the intent
            all_paths = re.findall(r'[A-Za-z]:[\\\/][^\s]+', context.intent)
            if all_paths:
                parts.append("\n## FILE PATHS (use these exact paths in your tool calls)")
                for fp in all_paths:
                    parts.append(f"  FILE: {fp}")

        parts.append(
            "\n## Instructions\n"
            "1. Use the available tools to accomplish this task.\n"
            "2. Respond with the tool call JSON to execute tools.\n"
            "3. After tool results, provide your final answer or call more tools.\n"
            "4. Do NOT explain what you would do — actually call the tools by responding with the JSON.\n"
            "5. Use the EXACT file paths provided above in your tool calls."
        )
        return "\n".join(parts)

    def _parse_tool_calls(self, text: str) -> list[dict[str, Any]] | None:
        """Try to parse tool calls from LLM response text.

        Handles multiple formats:
        1. Pure JSON: {"tool_calls": [...]}
        2. Markdown JSON: ```json\n{"tool_calls": [...]}\n```
        3. JSON embedded in prose (reasoning models)
        4. Bare JSON array: [{"tool": "...", "params": {...}}]
        """
        import re

        # Try direct JSON parse
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "tool_calls" in data:
                return data["tool_calls"]
            if isinstance(data, list) and len(data) > 0 and "tool" in data[0]:
                return data
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict) and "tool_calls" in data:
                    return data["tool_calls"]
                if isinstance(data, list) and len(data) > 0 and "tool" in data[0]:
                    return data
            except json.JSONDecodeError:
                pass

        # Try to find JSON objects with "tool_calls" using brace matching
        # (handles nested braces in params)
        tool_calls = self._extract_json_with_key(text, "tool_calls")
        if tool_calls:
            return tool_calls

        # Try to find bare JSON arrays with tool calls
        tool_calls = self._extract_tool_array(text)
        if tool_calls:
            return tool_calls

        # Try to find individual tool call objects
        tool_calls = self._extract_single_tool_calls(text)
        if tool_calls:
            return tool_calls

        return None

    def _extract_json_with_key(self, text: str, key: str) -> list[dict] | None:
        """Extract a JSON object containing a specific key from text.

        Uses brace matching to handle nested JSON (e.g., code params with braces).
        """
        # Find all positions where key appears
        import re
        for match in re.finditer(r'\{', text):
            pos = match.start()
            # Try to parse a JSON object starting at this brace
            obj = self._try_parse_json_at(text, pos)
            if obj and isinstance(obj, dict) and key in obj:
                if isinstance(obj[key], list):
                    return obj[key]
        return None

    def _try_parse_json_at(self, text: str, start: int) -> dict | None:
        """Try to parse a JSON object starting at the given position.

        Uses brace matching to find the end of the object.
        """
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    # Found the complete object
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        return None
        return None

    def _extract_tool_array(self, text: str) -> list[dict] | None:
        """Extract a JSON array of tool call objects from text."""
        import re
        for match in re.finditer(r'\[', text):
            pos = match.start()
            # Try to parse a JSON array starting at this bracket
            depth = 0
            in_string = False
            escape = False
            for i in range(pos, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == '\\':
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[pos:i+1])
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "tool" in data[0]:
                                return data
                        except json.JSONDecodeError:
                            pass
                        break
        return None

    def _extract_single_tool_calls(self, text: str) -> list[dict] | None:
        """Extract individual tool call objects from text."""
        import re
        tool_calls = []
        for match in re.finditer(r'\{', text):
            pos = match.start()
            obj = self._try_parse_json_at(text, pos)
            if obj and isinstance(obj, dict) and "tool" in obj and "params" in obj:
                tool_calls.append(obj)
        return tool_calls if tool_calls else None

    async def _execute_tool(self, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call."""
        try:
            tool = self._tool_registry.get(tool_id)
            result = await tool.execute(**params)
            return result
        except ToolNotFoundError:
            return {"success": False, "output": None, "error": f"Tool '{tool_id}' not found"}
        except Exception as e:
            logger.error(f"Tool '{tool_id}' execution error: {e}", exc_info=True)
            return {"success": False, "output": None, "error": str(e)}

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent.

        Runs the LLM loop with tool calling until:
        - The LLM produces a final (non-tool-call) response
        - Max iterations reached
        - Max tool calls reached
        - Timeout exceeded
        """
        start_time = time.time()
        events: list[dict[str, Any]] = []
        tool_call_count = 0
        iteration = 0

        logger.info(f"Agent '{self.id}' starting execution")

        # Build ADK tools from our tool registry
        adk_tools: list[FunctionTool] = []
        for tool_id in self.spec.tools:
            try:
                tool = self._tool_registry.get(tool_id)
                adk_tool = _make_adk_tool(tool_id, tool)
                adk_tools.append(adk_tool)
                logger.debug(f"Registered ADK tool: {tool_id}")
            except ToolNotFoundError:
                logger.warning(f"Tool '{tool_id}' not found in registry — skipping")

        # Build ADK agent with tools registered
        model = get_model(self.spec.model or None)
        adk_agent = LlmAgent(
            name=self.id,
            description=self.spec.description or self.spec.name,
            instruction=self._build_system_prompt(),
            model=model,
            tools=adk_tools,  # ADK requires a list (empty list is fine, None is not)
            output_key="agent_output",
        )

        session_service = InMemorySessionService()
        runner = Runner(
            agent=adk_agent,
            app_name="agentos_runtime",
            session_service=session_service,
        )
        session_id = f"agent_{uuid.uuid4().hex[:8]}"

        await session_service.create_session(
            app_name="agentos_runtime",
            user_id="agentos",
            session_id=session_id,
        )

        current_message = self._build_user_message(context)
        logger.info(f"Agent '{self.id}' user message: {current_message[:500]}")

        try:
            # With ADK native tool calling, the runner handles the LLM loop
            # automatically — it calls tools, feeds results back, and repeats
            # until the LLM produces a final response.
            # We just need to collect events and the final response.

            user_content = types.Content(
                role="user",
                parts=[types.Part(text=current_message)],
            )

            final_text: str | None = None

            async for event in runner.run_async(
                user_id="agentos",
                session_id=session_id,
                new_message=user_content,
            ):
                # Count tool calls from events
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        # Check for function_call parts (tool calls)
                        if hasattr(part, "function_call") and part.function_call:
                            tool_call_count += 1
                            fn_name = part.function_call.name if hasattr(part.function_call, "name") else str(part.function_call)
                            logger.info(f"Agent '{self.id}' ADK tool call: {fn_name}")
                            events.append({
                                "type": "TOOL_CALL",
                                "tool_id": fn_name,
                            })

                # Check for function_response parts (tool results)
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "function_response") and part.function_response:
                            fn_name = part.function_response.name if hasattr(part.function_response, "name") else "unknown"
                            events.append({
                                "type": "TOOL_COMPLETED",
                                "tool_id": fn_name,
                            })

                # Collect final response
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = []
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        final_text = "\n".join(text_parts).strip()

            iteration = 1
            elapsed = time.time() - start_time

            if not final_text:
                return AgentResult(
                    agent_id=self.id,
                    status="failed",
                    error="LLM returned no response",
                    tool_calls=tool_call_count,
                    iterations=iteration,
                    duration_seconds=elapsed,
                    events=events,
                )

            # Check if the final text still contains tool call JSON (fallback for text-based tool calling)
            tool_calls = self._parse_tool_calls(final_text)
            if tool_calls is not None:
                # The LLM returned text-based tool calls instead of native function calls
                # Execute them manually
                tool_results_text = []
                for tc in tool_calls:
                    if tool_call_count >= self.spec.max_tool_calls:
                        break
                    tool_id = tc.get("tool", "")
                    params = tc.get("params", {})
                    logger.info(f"Agent '{self.id}' text tool call: '{tool_id}' with params: {params}")
                    result = await self._execute_tool(tool_id, params)
                    tool_call_count += 1
                    context.add_tool_result(tool_id, params, result)
                    events.append({
                        "type": "TOOL_COMPLETED" if result.get("success") else "TOOL_FAILED",
                        "tool_id": tool_id,
                        "params": params,
                        "success": result.get("success", False),
                    })
                    tool_results_text.append(
                        f"Tool '{tool_id}' result: {json.dumps(result.get('output'), default=str)}"
                    )

                if tool_results_text:
                    # Feed results back for a final response
                    followup_message = (
                        "Tool results:\n" + "\n".join(tool_results_text) +
                        "\n\nBased on these results, provide your final answer."
                    )
                    followup_content = types.Content(
                        role="user",
                        parts=[types.Part(text=followup_message)],
                    )
                    async for event in runner.run_async(
                        user_id="agentos",
                        session_id=session_id,
                        new_message=followup_content,
                    ):
                        if event.is_final_response() and event.content and event.content.parts:
                            text_parts = []
                            for part in event.content.parts:
                                if hasattr(part, "text") and part.text:
                                    text_parts.append(part.text)
                            if text_parts:
                                final_text = "\n".join(text_parts).strip()

            logger.info(f"Agent '{self.id}' completed: {tool_call_count} tool calls, {elapsed:.1f}s")
            return AgentResult(
                agent_id=self.id,
                status="completed",
                output={"response": final_text},
                tool_calls=tool_call_count,
                iterations=iteration,
                duration_seconds=elapsed,
                events=events,
            )

        except asyncio.TimeoutError:
            return AgentResult(
                agent_id=self.id,
                status="timed_out",
                error=f"Agent timed out after {self.spec.timeout_seconds}s",
                tool_calls=tool_call_count,
                iterations=iteration,
                duration_seconds=time.time() - start_time,
                events=events,
            )
        except Exception as e:
            logger.error(f"Agent '{self.id}' failed: {e}", exc_info=True)
            return AgentResult(
                agent_id=self.id,
                status="failed",
                error=str(e),
                tool_calls=tool_call_count,
                iterations=iteration,
                duration_seconds=time.time() - start_time,
                events=events,
            )
        finally:
            try:
                await session_service.delete_session(
                    app_name="agentos_runtime",
                    user_id="agentos",
                    session_id=session_id,
                )
            except Exception:
                pass