"""Config section catalog for the app-wide config example."""

import importlib

from apprc_app_wide_config_example.config.app import MyRC

importlib.import_module("apprc_app_wide_config_example.config.bundle")

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
