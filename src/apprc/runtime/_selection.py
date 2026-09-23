"""Precedence of explicit inputs used for structural source selection."""

from collections.abc import Mapping


def selection_env(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Return env values used before dotenv layers mutate ``os.environ``."""
    if env_file_overrides_os_environ:
        return {**original_env, **explicit_values}
    return {**explicit_values, **original_env}
