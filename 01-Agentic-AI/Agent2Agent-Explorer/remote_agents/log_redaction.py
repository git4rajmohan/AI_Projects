"""Redact bearer tokens / authorization headers from all log records.

The a2a-sdk logs raw request headers at DEBUG; this guarantees credentials
never reach any log output, whichever logger emits them.
"""
import logging
import re

_BEARER = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+")
_AUTH_VALUE = re.compile(r"(?i)(['\"]authorization['\"]:\s*['\"])[^'\"]*(['\"])")


def redact(text: str) -> str:
    text = _BEARER.sub(r"\1[REDACTED]", text)
    return _AUTH_VALUE.sub(r"\1[REDACTED]\2", text)


def install() -> None:
    """Install once per process; idempotent."""
    factory = logging.getLogRecordFactory()
    if getattr(factory, "_redacts_auth", False):
        return

    def redacting_factory(*args, **kwargs):
        record = factory(*args, **kwargs)
        probe = f"{record.msg}{record.args}"
        if "earer" in probe or "uthorization" in probe:  # cheap case-insensitive-ish probe
            record.msg = redact(record.getMessage())
            record.args = None
        return record

    redacting_factory._redacts_auth = True
    logging.setLogRecordFactory(redacting_factory)
