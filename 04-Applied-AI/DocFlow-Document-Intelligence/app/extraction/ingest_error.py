"""Signals an unreadable document, so callers (API 422, eval skip) can react."""


class IngestError(Exception):
    pass