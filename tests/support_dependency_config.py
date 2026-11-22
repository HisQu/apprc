"""Shared declarations for public dependency config import tests."""

from pathlib import Path
from typing import Any

import apprc as rc


def dependency(
    tmp_path: Path,
    *,
    config_package: str | None = None,
) -> tuple[rc.AppRC, type[Any]]:
    """Declare a dependency with a complete client section."""
    dependency = rc.AppRC(
        app_id="dependency",
        config_package=config_package,
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "dependency-apprc"),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(registry=False),
    )

    @dependency.config("client", prefix="DEP_")
    class ClientRC(rc.Config):
        api_key: str = rc.field("DEP_API_KEY", secret=True)
        base_url: str = rc.field("DEP_BASE_URL", default="dependency-url")
        model_llm: str = rc.field("DEP_MODEL_LLM", default="dependency-model")
        model_fast: str = rc.field("DEP_MODEL_FAST", default="dependency-model")
        timeout: int = rc.field("DEP_TIMEOUT", default=5)

    return dependency, ClientRC


def host_import(
    host: rc.AppRC,
    dependency: rc.AppRC,
    config_type: type[Any],
    *,
    prefix: str,
    include_packaged_defaults: bool = False,
) -> rc.ImportedConfig[Any]:
    """Map client fields to a parent namespace, including model aliases."""
    return host.import_dependency_config(
        dependency,
        config_type,
        key="llm.client",
        prefix=prefix,
        title="Host LLM Client",
        fields={
            "api_key": rc.field(f"{prefix}API_KEY", secret=True),
            "endpoint": rc.field(
                f"{prefix}ENDPOINT", default="host-default-url", secret=True
            ),
            "chat_model": rc.field(
                f"{prefix}CHAT_MODEL", default="host-default-model"
            ),
            "timeout": rc.field(f"{prefix}TIMEOUT", default=11),
        },
        field_targets={
            "api_key": "api_key",
            "base_url": "endpoint",
            "model_llm": "chat_model",
            "model_fast": "chat_model",
            "timeout": "timeout",
        },
        include_packaged_defaults=include_packaged_defaults,
    )
