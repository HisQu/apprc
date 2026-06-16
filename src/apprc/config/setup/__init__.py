"""Setup workflow and user-facing copy helpers."""

# ruff: noqa: F401

from apprc.config.setup.flow import (
    ConfigSetupError,
    ConfigSetupResult,
    ExistingSetupAction,
    ensure_registered_storage,
    find_existing_apprc_toml_path,
    load_setup_registry,
    move_existing_apprc_toml,
    prepare_setup_registry,
    remove_apprc_toml_config_state,
    require_apprc_toml_path_available,
    same_path,
    setup_apprc_toml_dir,
    setup_apprc_toml_path_from_dir,
    setup_storage_root_from_env,
    validate_storage_root_for_setup,
)
from apprc.config.setup.text import (
    apprc_dir_label,
    apprc_dir_step_text,
    dotenv_apprc_toml_assignment,
    dotenv_assignment_commands,
    dotenv_storage_selector_assignment,
    existing_registry_text,
    export_apprc_toml_command,
    export_storage_selector_command,
    reset_warning_text,
    setup_finish_text,
    setup_overview_text,
    shell_export_commands,
    storage_root_reuse_text,
    storage_root_step_text,
    verification_commands,
)
