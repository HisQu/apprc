"""Class-level lifecycle logging decorators.

These helpers add small initialization breadcrumbs without changing call sites.
The decorator wraps a class ``__init__`` method, logs before and optionally
after construction, and uses ``AppLogger.depth`` so the reported callsite
points at the decorated class rather than the wrapper internals.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from apprc.logging.core import get_logger

_ClassT = TypeVar("_ClassT", bound=type[Any])


def log_init_lifecycle(
    label: str = "Runtime Config",
    log_start: bool = True,
    log_done: bool = False,
) -> Callable[[_ClassT], _ClassT]:
    """Return a class decorator that logs object initialization.

    The wrapper is idempotent: if the class has already been wrapped, the
    decorator returns it unchanged. The original ``__init__`` signature is not
    redefined, so arbitrary constructor arguments continue to pass through.

    :param label: Human-readable subsystem label.
    :param log_start: Whether to emit a pre-initialization message.
    :param log_done: Whether to emit a post-initialization message.
    :return: Class decorator.
    """

    def decorator(cls: _ClassT) -> _ClassT:
        original_init = cast(Callable[..., None], cls.__init__)
        if getattr(original_init, "__init_lifecycle_wrapped__", False):
            return cls

        @wraps(original_init)
        def wrapped_init(self: Any, *args: Any, **kwargs: Any) -> None:
            log = get_logger(cls.__module__)
            name = self.__class__.__name__
            with log.depth(1):
                if log_start:
                    log.info(f"⚙️🔜 INITIALIZING: {label} '{name}' ...")
                original_init(self, *args, **kwargs)
                if log_done:
                    log.info(f"⚙️✔️  {label} '{name}' initialized!")

        setattr(wrapped_init, "__init_lifecycle_wrapped__", True)
        setattr(cls, "__init__", wrapped_init)
        return cls

    return decorator


__all__ = ["log_init_lifecycle"]
