"""Background-thread asyncio event loop bridge for Streamlit.

Streamlit's execution model reruns the entire script on each user interaction,
but asyncio event loops and long-lived resources (like MCP server subprocesses)
must persist across reruns.  This module provides an ``AsyncBridge`` that runs
a dedicated event loop in a daemon thread so coroutines can be submitted from
Streamlit's synchronous context and awaited synchronously via ``bridge.run()``.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncBridge:
    """
    Runs a persistent asyncio event loop in a background daemon thread.

    All coroutines submitted via :meth:`run` execute on that loop, so
    long-lived async resources (server processes, connections) survive
    across Streamlit reruns.

    Typical usage with ``@st.cache_resource``::

        @st.cache_resource
        def get_bridge() -> AsyncBridge:
            return AsyncBridge()

        result = get_bridge().run(some_coroutine())
    """

    def __init__(self) -> None:
        # On Windows, subprocess creation requires ProactorEventLoop.
        # asyncio.new_event_loop() on a non-main thread defaults to
        # SelectorEventLoop, which cannot spawn processes.  Explicitly
        # create a ProactorEventLoop on Windows; on other platforms use
        # the default (already suitable) loop.
        import sys
        if sys.platform == "win32":
            self._loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="mcp-async-bridge",
            daemon=True,
        )
        self._thread.start()
        self._current_future: Any = None

    def run(self, coro: Coroutine[Any, Any, T], timeout: float = 300.0) -> T:
        """
        Submit *coro* to the background loop and block until it completes.

        Args:
            coro:    The coroutine to execute.
            timeout: Maximum seconds to wait (default 300 s / 5 min).

        Returns:
            Whatever the coroutine returns.

        Raises:
            Any exception raised by the coroutine, or
            ``concurrent.futures.TimeoutError`` if *timeout* elapses.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        self._current_future = future
        return future.result(timeout=timeout)

    def submit(self, coro: Coroutine[Any, Any, T]) -> "concurrent.futures.Future[T]":
        """Submit *coro* non-blocking and return a Future.

        The caller can poll ``future.done()`` and call ``future.result()``
        when ready.  Use :meth:`cancel_current` to abort.
        """
        future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(
            coro, self._loop
        )
        self._current_future = future
        return future

    def cancel_current(self) -> None:
        """Request cancellation of the most recently submitted coroutine."""
        f = self._current_future
        if f is not None and not f.done():
            # Schedule asyncio-side cancellation on the loop thread
            self._loop.call_soon_threadsafe(f.cancel)

    def stop(self) -> None:
        """Stop the background event loop (call on app shutdown if needed)."""
        self._loop.call_soon_threadsafe(self._loop.stop)
