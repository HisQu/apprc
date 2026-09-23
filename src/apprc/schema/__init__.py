"""Advanced AppRC config schema metadata namespace."""

# ruff: noqa: F401

# > Explicit aliases mark public imports for downstream type checkers.
from apprc.definition.env_config.lookup import (
    find_field_by_config_path as find_field_by_config_path,
    find_field_by_env_key as find_field_by_env_key,
    iter_config_fields as iter_config_fields,
    resolve_config_field_reference as resolve_config_field_reference,
)
from apprc.definition.env_config.schema import (
    ConfigField as ConfigField,
    ConfigOwner as ConfigOwner,
    owner_for as owner_for,
)
from apprc.definition.env_config.sentinels import (
    CONFIG_MISSING as CONFIG_MISSING,
    ENV_FIELD_MISSING as ENV_FIELD_MISSING,
)

from ._exports import PUBLIC_NAMES as __all__
