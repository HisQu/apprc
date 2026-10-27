"""Result and error records for explicit AppRC configuration setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConfigSetupError(ValueError):
    """Readable setup failure with optional CLI context.

    :param message: Human-readable setup failure.
    :param param_hint: Optional Typer parameter hint for the cause.
    :param exit_code: Optional command exit code.
    """

    def __init__(
        self,
        message: str,
        *,
        param_hint: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Store setup failure details."""
        super().__init__(message)
        self.param_hint = param_hint
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ConfigSetupResult:
    """Configuration locations initialized by one explicit setup run.

    :param config_dir: Captured configuration component root.
    :param user_dotenv: Initialized preference file, when declared.
    """

    config_dir: Path
    user_dotenv: Path | None
