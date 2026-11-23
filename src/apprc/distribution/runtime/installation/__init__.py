"""Public imports for transactional managed installation and editable registration."""

# ruff: noqa: F401

from .commands import recorded_command_directory
from .editable import register_editable_application
from .managed import install_application
from .post_install import (
    confirm_desktop_shortcut,
    offer_configuration_setup,
    publish_optional_shortcuts,
)
from .transaction import installation_maintenance_group, require_update_record
