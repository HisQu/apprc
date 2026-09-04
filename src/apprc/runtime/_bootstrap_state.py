"""Shared state for one AppRC declaration's process bootstrap."""

from __future__ import annotations

# == Standard Library ========================
import os
from threading import RLock

# == Internal ================================
from apprc.runtime.result import EnvBootstrapResult


class BootstrapState:
    """Record the latest successful bootstrap and serialize initial setup.

    ``AppRC`` may rebuild its lower-level kit as config classes register. This
    object survives those rebuilds so Python calls and mounted CLI callbacks
    observe the same bootstrap result.
    """

    __slots__ = ("baseline_env", "lock", "result", "written_env")

    def __init__(self) -> None:
        """Create empty state for one application declaration."""
        self.lock = RLock()
        self.result: EnvBootstrapResult | None = None
        self.baseline_env: dict[str, str] | None = None
        self.written_env: dict[str, str] = {}

    def begin_reload(self) -> tuple[dict[str, str], dict[str, str]]:
        """Restore unchanged prior writes before resolving new inputs.

        A caller mutation after bootstrap becomes part of the next baseline.
        Only values that still equal AppRC's exact prior write are restored.

        :return: Pre-reload snapshot and clean baseline environment.
        """
        before_reload = dict(os.environ)
        if self.baseline_env is None:
            clean_env = before_reload
        else:
            clean_env = dict(before_reload)
            for key, written_value in self.written_env.items():
                if before_reload.get(key) != written_value:
                    continue
                if key in self.baseline_env:
                    clean_env[key] = self.baseline_env[key]
                else:
                    clean_env.pop(key, None)
        _replace_process_environment(clean_env)
        return before_reload, clean_env

    def commit_reload(self, *, baseline_env: dict[str, str]) -> None:
        """Record exact writes made by the latest successful bootstrap.

        :param baseline_env: Environment used to resolve this bootstrap.
        :return: None.
        """
        current = dict(os.environ)
        self.baseline_env = baseline_env
        self.written_env = {
            key: value
            for key, value in current.items()
            if baseline_env.get(key) != value
        }

    def rollback_reload(self, before_reload: dict[str, str]) -> None:
        """Restore process state after a failed bootstrap attempt.

        :param before_reload: Environment captured before cleanup and retry.
        :return: None.
        """
        _replace_process_environment(before_reload)


def _replace_process_environment(values: dict[str, str]) -> None:
    """Make ``os.environ`` equal ``values`` without replacing its object.

    :param values: Complete target process environment.
    :return: None.
    """
    for key in set(os.environ) - set(values):
        del os.environ[key]
    os.environ.update(values)


__all__ = ["BootstrapState"]
