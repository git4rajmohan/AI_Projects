"""Async timeout helpers."""
from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Coroutine, Optional, TypeVar

from mcp_app.core.errors import ProcessTimeoutError

T = TypeVar("T")


async def with_timeout(
    coro: Coroutine[Any, Any, T],
    timeout: float,
    error_msg: str = "Operation timed out",
) -> T:
    """
    Await *coro* with a timeout.

    Raises:
        ProcessTimeoutError if the coroutine does not complete in time.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ProcessTimeoutError(error_msg) from exc


def timeout_decorator(seconds: float, error_msg: Optional[str] = None):
    """
    Decorator that applies a timeout to an async function.

    Usage::

        @timeout_decorator(30.0)
        async def my_fn(): ...
    """
    def decorator(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            msg = error_msg or f"{fn.__name__} timed out after {seconds}s"
            return await with_timeout(fn(*args, **kwargs), seconds, msg)
        return wrapper
    return decorator
