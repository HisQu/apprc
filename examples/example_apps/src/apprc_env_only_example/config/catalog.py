"""Config section catalog for the env-only example."""

import importlib

from apprc_env_only_example.config.app import MyRC

importlib.import_module("apprc_env_only_example.config.bundle")

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
