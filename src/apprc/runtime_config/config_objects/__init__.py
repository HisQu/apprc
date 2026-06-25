"""Runtime config object classes and declaration helpers.

Conceptual map:
- Public config objects: ``BaseConfig`` and ``EnvConfig`` are the classes app
  and library code should inherit from.
- App / env mode: ``env_field`` and ``env_owner`` declare env-backed config
  sections that resolve defaults, Python constructor values, and ``os.environ``.
- Library mode: ``BaseConfig.create_or_update`` persists per-instance values,
  while ``BaseConfig.scoped`` and ``scoped_from`` create request-local clones.
- State changes: assignment and persistent library-mode updates are tracked as
  Python-owned state changes.
- State transfer: internal copy/deepcopy helpers clone already-resolved config
  objects without rerunning constructors or env binding.
- State tracking: provenance records why each effective value won.
"""

# ruff: noqa: F401

from apprc.runtime_config.config_objects.base_config import BaseConfig
from apprc.runtime_config.config_objects.env_field import (
    EnvFieldSpec,
    config_owner_for,
    env_field,
    env_owner,
)
from apprc.runtime_config.config_objects.env_config import EnvConfig
