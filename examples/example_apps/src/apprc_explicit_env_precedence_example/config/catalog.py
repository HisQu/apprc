"""Config section catalog for the explicit env precedence example."""

import importlib

from apprc_explicit_env_precedence_example.config.app import MyRC

importlib.import_module("apprc_explicit_env_precedence_example.config.bundle")

KIT = MyRC.kit
CONFIG_SPEC = KIT.spec
CONFIG_SECTIONS = CONFIG_SPEC.owners
SECTION_BY_KEY = {section.key: section for section in CONFIG_SECTIONS}

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "SECTION_BY_KEY",
]
