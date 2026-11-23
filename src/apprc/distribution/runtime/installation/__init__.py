"""Public imports for transactional managed installation and editable registration."""

# ruff: noqa: F401

from ._commands import recorded_command_directory
from ._editable import register_editable_application
from ._managed import install_application
from ._post_install import (
    confirm_desktop_shortcut,
    offer_configuration_setup,
    publish_optional_shortcuts,
)
from ._transaction import installation_maintenance_group, require_update_record
