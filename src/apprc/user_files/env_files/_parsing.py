"""Dotenv syntax and interpolation against an explicitly captured environment."""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Mapping
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

LOG = logging.getLogger(__name__)


def parse_dotenv_text(
    text: str,
    *,
    environment: Mapping[str, str] | None = None,
    excluded_env_keys: Collection[str] = (),
    excluded_env_prefixes: Collection[str] = (),
) -> dict[str, str]:
    """Expand assignments in file order, including repeated keys.

    :param text: Dotenv source text.
    :param environment: Interpolation inputs, or a copy of the process environment.
    :param excluded_env_keys: Exact keys omitted from values and interpolation.
    :param excluded_env_prefixes: Prefixes omitted from values and interpolation.
    :return: String assignments; bare keys are omitted and empty values retained.
    """
    excluded_keys = frozenset(excluded_env_keys)
    excluded_prefixes = tuple(excluded_env_prefixes)

    def is_excluded(key: str) -> bool:
        """Return whether one key belongs to an excluded input boundary."""
        return key in excluded_keys or any(
            key.startswith(prefix) for prefix in excluded_prefixes
        )

    captured = {
        key: value
        for key, value in (
            os.environ if environment is None else environment
        ).items()
        if not is_excluded(key)
    }
    values: dict[str, str | None] = {}
    for binding in parse_stream(StringIO(text)):
        if binding.error:
            LOG.warning(
                "Invalid dotenv statement at line %s", binding.original.line
            )
        if binding.key is None:
            continue
        if is_excluded(binding.key):
            continue
        if binding.value is None:
            values[binding.key] = None
            continue
        context = {**captured, **values}
        values[binding.key] = "".join(
            atom.resolve(context) for atom in parse_variables(binding.value)
        )
    return {key: value for key, value in values.items() if value is not None}


def parse_dotenv_file(
    path: Path | None,
    *,
    environment: Mapping[str, str] | None = None,
    excluded_env_keys: Collection[str] = (),
    excluded_env_prefixes: Collection[str] = (),
) -> dict[str, str]:
    """Read an optional dotenv file using the shared syntax parser.

    :param path: Dotenv path, or ``None`` for an inactive layer.
    :param environment: Explicit interpolation inputs; an empty mapping is valid.
    :param excluded_env_keys: Exact keys omitted from values and interpolation.
    :param excluded_env_prefixes: Prefixes omitted from values and interpolation.
    :return: Parsed assignments, or an empty mapping for an absent file.
    """
    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    return parse_dotenv_text(
        env_path.read_text(encoding="utf-8"),
        environment=environment,
        excluded_env_keys=excluded_env_keys,
        excluded_env_prefixes=excluded_env_prefixes,
    )
