"""Config section catalog for the config-with-storage example."""

import importlib

from config_with_storage.config.app import MyRC

importlib.import_module("config_with_storage.config.bundle")

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
