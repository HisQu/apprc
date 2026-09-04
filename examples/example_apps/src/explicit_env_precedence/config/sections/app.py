"""Explicit env precedence example AppRC section."""

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc as rc
from explicit_env_precedence.config.app import MyRC


@MyRC.config(
    "precedence",
    prefix="APPRC_EXAMPLE_PRECEDENCE_",
    title="Precedence",
)
class ExplicitEnvPrecedenceConfig(rc.Config):
    """Storage fields used to demonstrate explicit env-file precedence."""

    storage_root: Path = rc.field(
        "APPRC_EXAMPLE_PRECEDENCE_STORAGE",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Storage selector used in precedence examples.",
    )
    label: str = rc.field(
        "APPRC_EXAMPLE_PRECEDENCE_LABEL",
        default="default",
        title="Label",
        explanation_short="Value overridden by shell and explicit env files.",
    )
