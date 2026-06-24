"""Shared sentinel objects for AppRC config resolution."""

from __future__ import annotations

from typing import Final

CONFIG_MISSING: Final = object()
ENV_FIELD_METADATA_KEY: Final = "apprc.env_field"


class _EnvFieldMissingSentinel:
    """Placeholder used until Python args, env, or owner defaults resolve."""

    def __repr__(self) -> str:
        return "env_field()"


ENV_FIELD_MISSING: Final = _EnvFieldMissingSentinel()
