"""Shared state for one AppRC declaration's process bootstrap."""

from __future__ import annotations

# == Standard Library ========================
from threading import RLock

# == Internal ================================
from apprc.runtime.result import EnvBootstrapResult


class BootstrapState:
    """Record the latest successful bootstrap and serialize initial setup.

    ``AppRC`` may rebuild its lower-level kit as config classes register. This
    object survives those rebuilds so Python calls and mounted CLI callbacks
    observe the same bootstrap result.
    """

    __slots__ = ("lock", "result")

    def __init__(self) -> None:
        """Create empty state for one application declaration."""
        self.lock = RLock()
        self.result: EnvBootstrapResult | None = None


__all__ = ["BootstrapState"]
