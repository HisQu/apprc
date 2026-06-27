"""Read persistent storage selector fallback layers."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass

# == Internal ================================
from apprc.runtime_config.app_spec import AppConfigSpec
from apprc.runtime_config.bootstrap.dotenv_layers import (
    read_dotenv_file,
    read_shared_env_values,
)


@dataclass(frozen=True, slots=True)
class StorageSelectorFallbackValues:
    """Dotenv values used after process env storage selectors.

    :param global_values: Values from the app-global dotenv file.
    :param shared_values: Values from the packaged shared dotenv file.
    :param issues: Non-fatal read problems suitable for diagnostics.
    """

    global_values: dict[str, str]
    shared_values: dict[str, str]
    issues: list[str]


def read_storage_selector_fallback_values(
    spec: AppConfigSpec,
) -> StorageSelectorFallbackValues:
    """Read dotenv fallback values used for storage selection.

    Bootstrap, config commands, and doctor must resolve persistent storage
    selectors the same way. This helper keeps the file-reading side of that
    rule in one place while leaving selector precedence in
    :mod:`apprc.runtime_config.storage.selector`.

    :param spec: Application-specific config contract.
    :return: Parsed fallback values and any diagnostic issues.
    """
    global_values = {}
    if spec.global_env_path().is_file():
        global_values = read_dotenv_file(spec.global_env_path())
    try:
        _, shared_values = read_shared_env_values(spec)
    except (ImportError, OSError, TypeError) as exc:
        shared_values = {}
        issues = [
            "Packaged shared env could not be read for "
            f"{spec.config_package!r}: {exc}"
        ]
    else:
        issues = []
    return StorageSelectorFallbackValues(
        global_values=global_values,
        shared_values=shared_values,
        issues=issues,
    )
