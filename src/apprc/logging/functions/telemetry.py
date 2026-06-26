"""Async telemetry helpers for AppRC's stdlib semantic logger.

Telemetry is a lightweight progress heartbeat for async workflows. The context
manager temporarily wraps the running event loop's ``create_task`` method so it
can count tasks spawned inside the scope, starts a reporter task, and emits
periodic ``TELEMETRY`` log messages through the normal AppRC logger pipeline.

No separate metrics backend is involved. Extra counters are pulled from an
optional callback and included in the human message so they appear in console
logs alongside task/thread counts.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from apprc.logging.core import AppLogger, get_logger


def _frame_name(depth: int = 0) -> str:
    """Return the function name at the requested stack depth.

    :param depth: Additional frames to skip above this helper.
    :return: Function name or ``unknown``.
    """

    frame = inspect.currentframe()
    try:
        for _ in range(depth + 1):
            if frame is None:
                return "unknown"
            frame = frame.f_back
        return frame.f_code.co_name if frame else "unknown"
    finally:
        del frame


class AsyncTelemetryContext:
    """Context manager for periodic async telemetry logging.

    Entering the context captures the current event loop, patches
    ``loop.create_task`` to remember tasks created in the scope, and starts a
    reporter task. Exiting restores the original task factory and signals the
    reporter to stop. The async exit path awaits the reporter so the final
    cleanup is deterministic.

    :param interval: Seconds between telemetry messages.
    :param label: Human-readable telemetry scope label.
    :param logger: Logger used for telemetry messages.
    :param include_threads: Whether active OS thread count is reported.
    :param extras: Optional callback returning extra metrics.
    """

    def __init__(
        self,
        *,
        interval: float = 30.0,
        label: str = "",
        logger: AppLogger | None = None,
        include_threads: bool = True,
        extras: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.interval = float(interval)
        self.label = label or _frame_name(depth=1)
        self.logger = logger or get_logger(__name__)
        self.include_threads = include_threads
        self.extras = extras
        self._loop: asyncio.AbstractEventLoop | None = None
        self._orig_create_task: Callable[..., asyncio.Task[Any]] | None = None
        self._scope_tasks: set[asyncio.Task[Any]] = set()
        self._stop_evt: asyncio.Event | None = None
        self._reporter: asyncio.Task[None] | None = None

    def __enter__(self) -> "AsyncTelemetryContext":
        """Start telemetry inside an already-running event loop.

        :return: This context manager.
        """

        self._start()
        return self

    async def __aenter__(self) -> "AsyncTelemetryContext":
        """Start telemetry for ``async with`` usage.

        :return: This context manager.
        """

        self._start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Signal telemetry shutdown from synchronous context-manager exit.

        :param exc_type: Exception type supplied by the context protocol.
        :param exc: Exception instance supplied by the context protocol.
        :param tb: Traceback supplied by the context protocol.
        :return: ``None``.
        """

        self._stop_sync()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Restore loop state and await reporter shutdown.

        :param exc_type: Exception type supplied by the context protocol.
        :param exc: Exception instance supplied by the context protocol.
        :param tb: Traceback supplied by the context protocol.
        :return: ``None``.
        """

        await self._stop_async()

    def snapshot(self) -> dict[str, Any]:
        """Return the current telemetry counters.

        The snapshot is useful for tests and for callers that want the same
        counters without waiting for the next log interval.

        :return: Snapshot data for active tasks, total tasks, and extras.
        """

        active_scope = sum(1 for t in list(self._scope_tasks) if not t.done())
        tasks_total = sum(1 for _ in asyncio.all_tasks())
        data: dict[str, Any] = {
            "label": self.label,
            "active_tasks_in_scope": active_scope,
            "tasks_total": tasks_total,
        }
        if self.include_threads:
            data["threads"] = threading.active_count()
        if self.extras:
            data.update(self.extras())
        return data

    def _start(self) -> None:
        """Patch task creation and start the reporter task.

        :return: ``None``.
        """

        self._loop = asyncio.get_running_loop()
        self._stop_evt = asyncio.Event()
        orig_create_task: Callable[..., asyncio.Task[Any]] = (
            self._loop.create_task
        )
        self._orig_create_task = orig_create_task

        def _patched_create_task(
            coro: Any,
            *args: Any,
            **kwargs: Any,
        ) -> asyncio.Task[Any]:
            task = orig_create_task(coro, *args, **kwargs)
            self._scope_tasks.add(task)
            return task

        self._loop.create_task = _patched_create_task
        self._reporter = orig_create_task(
            self._reporter_loop(),
            name=f"{self.label}:telemetry",
        )

    async def _stop_async(self) -> None:
        """Restore the event loop and await the reporter task.

        :return: ``None``.
        """

        if self._loop is None:
            return
        if self._orig_create_task is not None:
            self._loop.create_task = self._orig_create_task
            self._orig_create_task = None
        if self._stop_evt is not None:
            self._stop_evt.set()
        if self._reporter is not None:
            try:
                await self._reporter
            finally:
                self._reporter = None

    def _stop_sync(self) -> None:
        """Restore the event loop and signal the reporter task.

        :return: ``None``.
        """

        if self._loop is None:
            return
        if self._orig_create_task is not None:
            self._loop.create_task = self._orig_create_task
            self._orig_create_task = None
        if self._stop_evt is not None:
            self._stop_evt.set()

    async def _reporter_loop(self) -> None:
        """Emit telemetry until the stop event is set.

        :return: ``None``.
        """

        self.logger.debug(f"Entered reporter loop [{self.label}]")
        await self._emit()
        assert self._stop_evt is not None
        while not self._stop_evt.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_evt.wait(), timeout=self.interval
                )
            except TimeoutError:
                await self._emit()
            else:
                break
        self.logger.debug(f"Exited reporter loop [{self.label}]")

    async def _emit(self, depth: int = 1) -> None:
        """Emit one telemetry message through the configured logger.

        :param depth: Additional stack frames to skip for callsite attribution.
        :return: ``None``.
        """

        self._scope_tasks = {t for t in self._scope_tasks if not t.done()}
        all_tasks: Iterable[asyncio.Task[Any]] = asyncio.all_tasks()
        tasks_total = sum(1 for _ in all_tasks)
        parts = [
            f"[Active / Total Tasks: {len(self._scope_tasks)}/{tasks_total}]",
        ]
        if self.include_threads:
            parts.append(f"[OS Threads: {threading.active_count()}]")
        if self.extras:
            for key, value in self.extras().items():
                parts.append(f"[{key}={value}]")
        self.logger.telemetry(" ".join(parts), depth=depth)


def async_telemetry(
    label: str = "",
    *,
    interval: float = 30.0,
    logger: AppLogger | None = None,
    include_threads: bool = True,
    extras: Callable[[], dict[str, Any]] | None = None,
) -> AsyncTelemetryContext:
    """Create an async telemetry context manager.

    This is the public helper used by ``AppLogger.telemetry_async`` and by
    callers that want to wrap a block directly.

    :param label: Human-readable telemetry scope label.
    :param interval: Seconds between telemetry messages.
    :param logger: Logger used for telemetry messages.
    :param include_threads: Whether active OS thread count is reported.
    :param extras: Optional callback returning extra metrics.
    :return: Async telemetry context manager.
    """

    return AsyncTelemetryContext(
        interval=interval,
        label=label or _frame_name(depth=2),
        logger=logger,
        include_threads=include_threads,
        extras=extras,
    )


P = ParamSpec("P")
R = TypeVar("R")


def with_async_telemetry(
    label: str = "",
    *,
    interval: float = 30.0,
    logger: AppLogger | None = None,
    include_threads: bool = True,
    extras: Callable[[], dict[str, Any]] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async function to run inside telemetry logging.

    The decorated function runs unchanged except that its body is wrapped in an
    ``async_telemetry`` context. Non-async functions are rejected at decoration
    time because the context needs a running event loop.

    :param label: Human-readable telemetry scope label.
    :param interval: Seconds between telemetry messages.
    :param logger: Logger used for telemetry messages.
    :param include_threads: Whether active OS thread count is reported.
    :param extras: Optional callback returning extra metrics.
    :return: Async function decorator.
    """

    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(
                "with_async_telemetry can only decorate async functions"
            )

        @wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            telemetry_label = label or getattr(fn, "__qualname__", fn.__name__)
            async with async_telemetry(
                interval=interval,
                label=telemetry_label,
                logger=logger,
                include_threads=include_threads,
                extras=extras,
            ):
                return await fn(*args, **kwargs)

        return wrapped

    return decorate


__all__ = [
    "AsyncTelemetryContext",
    "async_telemetry",
    "with_async_telemetry",
]
