"""Structured logging configuration with correlation IDs."""

import logging
import sys
import uuid
from contextvars import ContextVar

# Context variables for correlation IDs
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)
execution_id_var: ContextVar[str | None] = ContextVar("execution_id", default=None)
agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)


class CorrelationFilter(logging.Filter):
    """Inject correlation IDs into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.task_id = task_id_var.get() or "-"
        record.execution_id = execution_id_var.get() or "-"
        record.agent_id = agent_id_var.get() or "-"
        return True


class SecretRedactionFilter(logging.Filter):
    """Redact secrets from log messages."""

    SENSITIVE_KEYS = {
        "api_key",
        "apikey",
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "openai_api_key",
        "ollama_api_key",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for key in self.SENSITIVE_KEYS:
            # Redact patterns like key=value or key: value
            import re

            msg = re.sub(
                rf"{key}=[^\s]+",
                f"{key}=***REDACTED***",
                msg,
                flags=re.IGNORECASE,
            )
            msg = re.sub(
                rf"{key}:\s*[^\s]+",
                f"{key}: ***REDACTED***",
                msg,
                flags=re.IGNORECASE,
            )
        record.msg = msg
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging with correlation IDs and secret redaction."""

    fmt = (
        "%(asctime)s | %(levelname)-8s | "
        "task=%(task_id)s exec=%(execution_id)s agent=%(agent_id)s | "
        "%(name)s | %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(CorrelationFilter())
    handler.addFilter(SecretRedactionFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def set_correlation(
    task_id: str | None = None,
    execution_id: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Set correlation IDs for the current async context."""
    if task_id is not None:
        task_id_var.set(task_id)
    if execution_id is not None:
        execution_id_var.set(execution_id)
    if agent_id is not None:
        agent_id_var.set(agent_id)


def generate_id() -> str:
    """Generate a unique ID for tasks, executions, etc."""
    return str(uuid.uuid4())