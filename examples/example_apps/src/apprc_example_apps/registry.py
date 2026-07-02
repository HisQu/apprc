"""Public registry for repository-local AppRC example apps."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping
from dataclasses import dataclass

# == Internal ================================
import apprc
from apprc_app_wide_config_example.config import KIT as APP_WIDE_CONFIG_KIT
from apprc_app_wide_storage_example.config import KIT as APP_WIDE_STORAGE_KIT
from apprc_cli_runtime_example.config import KIT as CLI_RUNTIME_KIT
from apprc_env_only_example.config import KIT as ENV_ONLY_KIT
from apprc_explicit_env_precedence_example.config import (
    KIT as EXPLICIT_ENV_PRECEDENCE_KIT,
)
from apprc_storage_only_example.config import KIT as STORAGE_ONLY_KIT


@dataclass(frozen=True, slots=True)
class ExampleAppSpec:
    """Files and values needed to bootstrap one example app.

    :param name: Human-readable mode name used in summaries.
    :param root_name: Repository-local sandbox directory name.
    :param kit: AppRC contract for the example CLI.
    :param explicit_values: Values written to the arbitrary sourceable
        ``.env`` file.
    :param app_wide_values: Values written to the app-wide dotenv file.
    :param storage_values: Values written to the selected storage dotenv file.
    :param storage_name: Named-storage selector registered in the TOML index.
    """

    name: str
    root_name: str
    kit: apprc.AppConfigKit
    explicit_values: Mapping[str, str]
    app_wide_values: Mapping[str, str]
    storage_values: Mapping[str, str] | None = None
    storage_name: str = "alpha"

    @property
    def uses_storage(self) -> bool:
        """Return whether this example has a selected storage root."""
        return self.kit.spec.storage_required()


EXAMPLE_APPS = (
    ExampleAppSpec(
        name="env_only",
        root_name=".apprc-example-env-only",
        kit=ENV_ONLY_KIT,
        explicit_values={
            "APPRC_EXAMPLE_ENV_ONLY_PROFILE": "explicit-env-profile",
            "APPRC_EXAMPLE_ENV_ONLY_DEBUG": "true",
        },
        app_wide_values={
            "APPRC_EXAMPLE_ENV_ONLY_PROFILE": "app-wide-profile",
        },
    ),
    ExampleAppSpec(
        name="storage_only",
        root_name=".apprc-example-storage-only",
        kit=STORAGE_ONLY_KIT,
        explicit_values={
            "APPRC_EXAMPLE_STORAGE_ENABLED": "false",
            "APPRC_EXAMPLE_STORAGE_RETRY_COUNT": "7",
        },
        app_wide_values={
            "APPRC_EXAMPLE_STORAGE_PROFILE": "app-wide-profile",
        },
        storage_values={
            "APPRC_EXAMPLE_STORAGE_PROFILE": "storage-profile",
            "APPRC_EXAMPLE_STORAGE_MODE": "MANUAL",
            "APPRC_EXAMPLE_STORAGE_API_TOKEN": "storage-secret-token",
        },
    ),
    ExampleAppSpec(
        name="app_wide_config",
        root_name=".apprc-example-app-wide-config",
        kit=APP_WIDE_CONFIG_KIT,
        explicit_values={
            "APPRC_EXAMPLE_APP_WIDE_WORKERS": "8",
        },
        app_wide_values={
            "APPRC_EXAMPLE_APP_WIDE_REGION": "app-wide-region",
            "APPRC_EXAMPLE_APP_WIDE_WORKERS": "4",
        },
    ),
    ExampleAppSpec(
        name="app_wide_storage",
        root_name=".apprc-example-app-wide-storage",
        kit=APP_WIDE_STORAGE_KIT,
        explicit_values={
            "APPRC_EXAMPLE_APP_WIDE_STORAGE_REGION": "explicit-region",
        },
        app_wide_values={
            "APPRC_EXAMPLE_APP_WIDE_STORAGE_REGION": "app-wide-region",
        },
        storage_values={
            "APPRC_EXAMPLE_APP_WIDE_STORAGE_ACCESS_TOKEN": (
                "app-wide-storage-secret"
            ),
        },
    ),
    ExampleAppSpec(
        name="explicit_env_precedence",
        root_name=".apprc-example-explicit-env-precedence",
        kit=EXPLICIT_ENV_PRECEDENCE_KIT,
        explicit_values={
            "APPRC_EXAMPLE_PRECEDENCE_LABEL": "explicit-env-label",
        },
        app_wide_values={
            "APPRC_EXAMPLE_PRECEDENCE_LABEL": "app-wide-label",
        },
        storage_values={
            "APPRC_EXAMPLE_PRECEDENCE_LABEL": "storage-label",
        },
    ),
    ExampleAppSpec(
        name="cli_runtime",
        root_name=".apprc-example-cli-runtime",
        kit=CLI_RUNTIME_KIT,
        explicit_values={
            "APPRC_EXAMPLE_RUNTIME_PROFILE": "explicit-runtime-profile",
        },
        app_wide_values={
            "APPRC_EXAMPLE_RUNTIME_PROFILE": "app-wide-runtime-profile",
        },
        storage_values={
            "APPRC_EXAMPLE_RUNTIME_API_TOKEN": "runtime-secret-token",
        },
    ),
)


def example_app_specs() -> tuple[ExampleAppSpec, ...]:
    """Return all repository-local example app specs.

    :return: Immutable registry entries for dev-only example CLIs.
    """
    return EXAMPLE_APPS


def example_kits() -> dict[str, apprc.AppConfigKit]:
    """Return example AppRC kits keyed by registry name.

    :return: Mapping from example registry name to AppRC kit.
    """
    return {spec.name: spec.kit for spec in EXAMPLE_APPS}
