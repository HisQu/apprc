"""Public registry for repository-local AppRC example apps."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping
from dataclasses import dataclass

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from cli_runtime.config import KIT as CLI_RUNTIME_KIT
from config_only.config import KIT as CONFIG_ONLY_KIT
from explicit_env_precedence.config import (
    KIT as EXPLICIT_ENV_PRECEDENCE_KIT,
)
from config_with_storage.config import KIT as CONFIG_WITH_STORAGE_KIT


@dataclass(frozen=True, slots=True)
class ExampleAppSpec:
    """Files and values needed to bootstrap one example app.

    :param name: Human-readable scenario name used in summaries.
    :param root_name: Repository-local sandbox directory name.
    :param kit: AppRC contract for the example CLI.
    :param explicit_values: Values written to the arbitrary sourceable
        ``.env`` file.
    :param app_values: Values written to the per-user dotenv file.
    :param storage_values: Values written to the selected storage dotenv file.
    :param storage_name: Named-storage selector registered in the TOML index.
    """

    name: str
    root_name: str
    kit: AppConfigKit
    explicit_values: Mapping[str, str]
    app_values: Mapping[str, str]
    storage_values: Mapping[str, str] | None = None
    storage_name: str = "alpha"

    @property
    def uses_storage(self) -> bool:
        """Return whether this example has a selected storage root."""
        return self.kit.spec.uses_storage()


EXAMPLE_APPS = (
    ExampleAppSpec(
        name="config_only",
        root_name=".apprc-example-config-only",
        kit=CONFIG_ONLY_KIT,
        explicit_values={
            "APPRC_EXAMPLE_CONFIG_PROFILE": "explicit-env-profile",
            "APPRC_EXAMPLE_CONFIG_DEBUG": "true",
        },
        app_values={
            "APPRC_EXAMPLE_CONFIG_PROFILE": "app-wide-profile",
        },
    ),
    ExampleAppSpec(
        name="config_with_storage",
        root_name=".apprc-example-config-with-storage",
        kit=CONFIG_WITH_STORAGE_KIT,
        explicit_values={
            "APPRC_EXAMPLE_STORAGE_ENABLED": "false",
            "APPRC_EXAMPLE_STORAGE_RETRY_COUNT": "7",
        },
        app_values={
            "APPRC_EXAMPLE_STORAGE_PROFILE": "app-wide-profile",
        },
        storage_values={
            "APPRC_EXAMPLE_STORAGE_PROFILE": "storage-profile",
            "APPRC_EXAMPLE_STORAGE_MODE": "MANUAL",
            "APPRC_EXAMPLE_STORAGE_API_TOKEN": "storage-secret-token",
        },
    ),
    ExampleAppSpec(
        name="explicit_env_precedence",
        root_name=".apprc-example-explicit-env-precedence",
        kit=EXPLICIT_ENV_PRECEDENCE_KIT,
        explicit_values={
            "APPRC_EXAMPLE_PRECEDENCE_LABEL": "explicit-env-label",
        },
        app_values={
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
        app_values={
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


def example_kits() -> dict[str, AppConfigKit]:
    """Return example AppRC kits keyed by registry name.

    :return: Mapping from example registry name to AppRC kit.
    """
    return {spec.name: spec.kit for spec in EXAMPLE_APPS}
