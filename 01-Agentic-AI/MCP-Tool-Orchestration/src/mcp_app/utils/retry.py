"""Simple exponential-backoff retry helper."""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Coroutine, Tuple, Type, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


async def retry_async(
    fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """
    Call an async function with exponential-backoff retry.

    Args:
        fn:         Async callable to retry.
        retries:    Maximum number of *extra* attempts (total = retries + 1).
        base_delay: Initial sleep between attempts (seconds).
        max_delay:  Cap on sleep duration.
        exceptions: Tuple of exception types to retry on.

    Returns:
        Result of the first successful call.

    Raises:
        The last exception if all attempts fail.
    """
    last_exc: BaseException = RuntimeError("No attempts made")
    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < retries:
                log.debug(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1, retries, fn.__name__, delay, exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
            else:
                log.debug("All %d retries exhausted for %s.", retries, fn.__name__)
    raise last_exc


def retry_decorator(
    retries: int = 3,
    base_delay: float = 0.5,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
):
    """Decorator version of retry_async."""
    def decorator(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(
                fn, *args, retries=retries, base_delay=base_delay,
                exceptions=exceptions, **kwargs
            )
        return wrapper
    return decorator
