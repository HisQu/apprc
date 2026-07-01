"""Private dotenv parsing helpers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
from dotenv import dotenv_values


def parse_dotenv_file(path: Path | None) -> dict[str, str]:
    """Parse an optional dotenv file into string key/value pairs.

    :param path: Dotenv file path, or ``None`` for an inactive layer.
    :return: Parsed string values. Missing files return an empty mapping.
    """
    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    values = dotenv_values(env_path)
    return {
        key: value for key, value in values.items() if isinstance(value, str)
    }
