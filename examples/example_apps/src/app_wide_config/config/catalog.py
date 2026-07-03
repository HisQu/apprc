"""Config section catalog for the app-wide config example."""

import importlib

from app_wide_config.config.app import MyRC

importlib.import_module("app_wide_config.config.bundle")

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
