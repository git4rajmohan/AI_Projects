"""Security utilities — secret protection and input sanitization."""

import re
from pathlib import Path

# Patterns that should never appear in user-facing output
SENSITIVE_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",  # OpenAI-style keys
    r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*",  # Bearer tokens
    r"password\s*[:=]\s*\S+",  # Password assignments
]


def redact_secrets(text: str) -> str:
    """Redact known secret patterns from text."""
    for pattern in SENSITIVE_PATTERNS:
        text = re.sub(pattern, "***REDACTED***", text, flags=re.IGNORECASE)
    return text


def sanitize_path(path_str: str, base_dir: str | None = None) -> Path:
    """Sanitize a file path to prevent directory traversal.

    If base_dir is provided, ensures the resolved path stays within base_dir.
    """
    resolved = Path(path_str).resolve()
    if base_dir is not None:
        base = Path(base_dir).resolve()
        if not str(resolved).startswith(str(base)):
            raise ValueError(f"Path '{path_str}' escapes base directory '{base_dir}'")
    return resolved


def is_safe_filename(filename: str) -> bool:
    """Check if a filename is safe (no path traversal, no special chars)."""
    if not filename or len(filename) > 255:
        return False
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    # Allow alphanumeric, dash, underscore, dot, space
    return bool(re.match(r"^[\w\.\- ]+$", filename))