"""Dotenv syntax and interpolation against an explicitly captured environment."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

LOG = logging.getLogger(__name__)


def parse_dotenv_text(
    text: str, *, environment: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Expand assignments in file order, including repeated keys.

    :param text: Dotenv source text.
    :param environment: Interpolation inputs, or a copy of the process environment.
    :return: String assignments; bare keys are omitted and empty values retained.
    """
    captured = dict(os.environ if environment is None else environment)
    values: dict[str, str | None] = {}
    for binding in parse_stream(StringIO(text)):
        if binding.error:
            LOG.warning(
                "Invalid dotenv statement at line %s", binding.original.line
            )
        if binding.key is None:
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
    path: Path | None, *, environment: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Read an optional dotenv file using the shared syntax parser.

    :param path: Dotenv path, or ``None`` for an inactive layer.
    :param environment: Explicit interpolation inputs; an empty mapping is valid.
    :return: Parsed assignments, or an empty mapping for an absent file.
    """
    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    return parse_dotenv_text(
        env_path.read_text(encoding="utf-8"), environment=environment
    )
