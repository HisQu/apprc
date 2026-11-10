"""Result and error records for explicit AppRC configuration setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigSetupResult:
    """Configuration locations initialized by one explicit setup run.

    :param config_dir: Captured configuration component root.
    :param user_dotenv: Initialized preference file, when declared.
    """

    config_dir: Path
    user_dotenv: Path | None
