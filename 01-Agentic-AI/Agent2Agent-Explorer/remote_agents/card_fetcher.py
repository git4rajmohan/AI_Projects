"""Safely fetch an Agent Card JSON document from a user-supplied URL.

Every fetch passes SSRF validation first; redirects are refused; the body
is streamed with a hard size cap.
"""
import json
from typing import Any

import httpx

from remote_agents.config import settings
from remote_agents.url_safety import validate_url


class CardFetchError(Exception):
    """Card could not be fetched; message says why."""


def fetch_card_json(
    url: str,
    *,
    timeout: float | None = None,
    max_bytes: int | None = None,
    transport: httpx.BaseTransport | None = None,
    allow_local: bool | None = None,
) -> dict[str, Any]:
    """Fetch `url` and return the parsed JSON object. Raises CardFetchError / UnsafeUrlError."""
    validate_url(url, allow_local=allow_local)
    timeout = settings.default_timeout if timeout is None else timeout
    max_bytes = settings.max_card_bytes if max_bytes is None else max_bytes

    try:
        # ponytail: follow_redirects=False == A2A_MAX_REDIRECTS=0; revalidate per hop if that ever changes
        with httpx.Client(follow_redirects=False, timeout=timeout, transport=transport) as client:
            with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    raise CardFetchError(f"redirect to {resp.headers.get('location')!r} refused (A2A_MAX_REDIRECTS=0)")
                if resp.status_code != 200:
                    raise CardFetchError(f"HTTP {resp.status_code} from {url}")
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise CardFetchError(f"response exceeds {max_bytes} byte limit")
    except httpx.HTTPError as exc:
        raise CardFetchError(f"request failed: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CardFetchError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CardFetchError("response JSON is not an object")
    return data
