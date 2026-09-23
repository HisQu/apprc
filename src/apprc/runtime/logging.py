"""Minimal application logging contract for runtime adapters."""

from typing import Any, Protocol


class ResolutionLogger(Protocol):
    """Logger interface needed for resolution status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""
