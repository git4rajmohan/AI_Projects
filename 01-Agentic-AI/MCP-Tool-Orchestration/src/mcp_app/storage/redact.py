"""Deterministic secret redaction for logs and traces."""
from __future__ import annotations

import re
from typing import Any

_REDACTED = "***REDACTED***"

# Default sensitive key names (lower-cased for comparison)
_DEFAULT_REDACT_KEYS: frozenset[str] = frozenset(
    [
        "token", "password", "secret", "api_key", "apikey",
        "access_key", "private_key", "auth", "authorization",
        "bearer", "credential", "passphrase",
    ]
)

# Regex patterns for values that look like tokens / keys
_SECRET_VALUE_PATTERNS = [
    re.compile(r"^sk-[A-Za-z0-9]{20,}$"),   # OpenAI-style
    re.compile(r"^Bearer\s+\S+"),            # Authorization header value
]


def _is_sensitive_key(key: str, redact_keys: frozenset[str]) -> bool:
    """Return True if *key* (case-insensitive) is in the redact set."""
    return key.lower() in redact_keys


def _looks_like_secret(value: str) -> bool:
    """Heuristic: value looks like a bearer token or API key."""
    for pat in _SECRET_VALUE_PATTERNS:
        if pat.match(value):
            return True
    return False


def redact_dict(
    obj: Any,
    redact_keys: frozenset[str] | None = None,
) -> Any:
    """
    Recursively redact sensitive fields from dicts/lists.

    Args:
        obj:         The object to redact (dict, list, or scalar).
        redact_keys: Set of lower-cased key names to redact.
                     Defaults to the built-in set.

    Returns:
        A new object with sensitive values replaced by ***REDACTED***.
    """
    if redact_keys is None:
        redact_keys = _DEFAULT_REDACT_KEYS

    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if _is_sensitive_key(str(k), redact_keys):
                result[k] = _REDACTED
            else:
                result[k] = redact_dict(v, redact_keys)
        return result

    if isinstance(obj, list):
        return [redact_dict(item, redact_keys) for item in obj]

    if isinstance(obj, str) and _looks_like_secret(obj):
        return _REDACTED

    return obj


def make_redactor(redact_keys: list[str]):
    """
    Factory: returns a redact_dict partial bound to the supplied key list.

    Useful so callers can pass a single-argument callable.
    """
    key_set = frozenset(k.lower() for k in redact_keys)

    def _redact(obj: Any) -> Any:
        return redact_dict(obj, redact_keys=key_set)

    return _redact
