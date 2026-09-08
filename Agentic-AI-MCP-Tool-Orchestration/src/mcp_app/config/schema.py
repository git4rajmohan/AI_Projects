"""Pydantic v2 schemas for all config files."""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ── App Settings ─────────────────────────────────────────────────────────────

class OllamaSettings(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    temperature: float = 0.2
    num_ctx: int = 8192
    api_key: str = ""  # Bearer token for Ollama Cloud (https://ollama.com); blank for local


class OpenAICompatSettings(BaseModel):
    """Settings for any OpenAI-compatible API (OpenAI, Azure OpenAI, Groq, etc.)."""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.2


class ToolCallingSettings(BaseModel):
    mode: Literal["require_approval", "auto"] = "require_approval"


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    dir: str = "./.mcp_app_logs"


class LimitsSettings(BaseModel):
    max_tool_output_chars: int = 20000
    max_tool_rounds: int = 20   # agentic tool-call rounds per turn
    excel_max_rows: int = 2000  # servers/excel MAX_ROWS_HARD
    sql_max_rows: int = 500     # servers/sql MAX_ROWS_HARD


class TimeoutsSettings(BaseModel):
    llm_seconds: int = 60
    tool_seconds: int = 60


class BrowserSettings(BaseModel):
    headless: bool = True
    screenshots_dir: str = "./.mcp_app_logs/screenshots"


class UISettings(BaseModel):
    font_size: int = 15
    font_family: str = "sans-serif"
    zoom: float = 1.0
    theme: Literal["dark", "light"] = "dark"
    accent_color: str = "#ff6b35"
    chat_max_width: int = 800
    compact_mode: bool = False
    show_timestamps: bool = False
    tool_calls_expanded: bool = False


class VisionSettings(BaseModel):
    """Optional dedicated vision model for image analysis turns."""
    enabled: bool = False
    provider: str = "openai_compat"  # "ollama" | "openai_compat"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2


class AppSettings(BaseModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    openai_compat: OpenAICompatSettings = Field(default_factory=OpenAICompatSettings)
    llm_provider: str = "ollama"  # "ollama" | "openai_compat"
    vision: VisionSettings = Field(default_factory=VisionSettings)
    tool_calling: ToolCallingSettings = Field(default_factory=ToolCallingSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    timeouts: TimeoutsSettings = Field(default_factory=TimeoutsSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    ui: UISettings = Field(default_factory=UISettings)

    @property
    def active_model(self) -> str:
        """Return the model name for the currently configured provider."""
        if self.llm_provider == "openai_compat":
            return self.openai_compat.model
        return self.ollama.model


# ── MCP Servers ───────────────────────────────────────────────────────────────

class StdioConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)
    env_file: Optional[str] = None


class ServerTimeouts(BaseModel):
    connect_seconds: int = 10
    call_seconds: int = 30


class ServerPolicy(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)

    @field_validator("allowed_tools", "denied_tools", mode="before")
    @classmethod
    def must_be_list(cls, v: Any, info: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError(
                f"policy.{info.field_name} must be a list, got {type(v).__name__}"
            )
        return v


class ServerConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True
    transport: Literal["stdio", "http", "ws"] = "stdio"
    stdio: Optional[StdioConfig] = None
    timeouts: ServerTimeouts = Field(default_factory=ServerTimeouts)
    policy: ServerPolicy = Field(default_factory=ServerPolicy)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_transport_config(self) -> "ServerConfig":
        if self.transport == "stdio":
            if self.stdio is None:
                raise ValueError(
                    f"Server '{self.id}': transport=stdio requires a [stdio] section "
                    "with at least 'command'."
                )
        elif self.transport in ("http", "ws"):
            # stubs – not implemented yet
            pass
        else:
            raise ValueError(
                f"Server '{self.id}': unknown transport '{self.transport}'. "
                "Supported: stdio."
            )
        return self


class MCPServersConfig(BaseModel):
    servers: list[ServerConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "MCPServersConfig":
        seen: set[str] = set()
        for srv in self.servers:
            if srv.id in seen:
                raise ValueError(
                    f"Duplicate server id '{srv.id}' in mcp_servers.yaml. "
                    "All server ids must be unique."
                )
            seen.add(srv.id)
        return self


# ── Policies ─────────────────────────────────────────────────────────────────

class PoliciesConfig(BaseModel):
    global_denied_tools: list[str] = Field(default_factory=list)
    global_allowed_tools: list[str] = Field(default_factory=list)
    dangerous_tools_require_approval: bool = True
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "token", "password", "secret", "api_key", "apikey",
            "access_key", "private_key", "auth", "authorization",
            "bearer", "credential", "passphrase",
        ]
    )

    @field_validator(
        "global_denied_tools", "global_allowed_tools", "redact_keys", mode="before"
    )
    @classmethod
    def must_be_list(cls, v: Any, info: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError(
                f"policies.{info.field_name} must be a list, got {type(v).__name__}"
            )
        return v
