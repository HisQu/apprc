"""Common CLI option metadata."""

from __future__ import annotations

COMMON_ROOT_FLAG_OPTIONS = frozenset(
    {
        "--env-file-overrides-shell",
        "--skip-dotenv-layers",
        "-s",
    }
)
COMMON_ROOT_VALUE_OPTIONS = frozenset(
    {
        "--env-file",
        "--log-level",
        "--storage",
    }
)
