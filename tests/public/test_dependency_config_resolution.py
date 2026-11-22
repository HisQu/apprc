"""Dependency imports resolve values and workspaces in the parent scope."""

import importlib
import logging
from dataclasses import (
    dataclass,
    replace,
)
from dataclasses import (
    field as dc_field,
)
from pathlib import Path
from typing import Any, cast

import pytest

import apprc as rc
from tests.support_dependency_config import (
    dependency as _dependency,
    host_import as _host_import,
)


def _write_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_name: str,
    defaults: str,
) -> str:
    """Create a tiny importable package containing AppRC defaults."""
    package = tmp_path / package_name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "apprc.defaults.env").write_text(defaults, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return package_name


def test_parent_secret_metadata_redacts_logs_and_nested_serialization(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Parent secret metadata applies to every AppRC display path."""
    dependency = rc.AppRC(app_id="dependency")

    @dependency.config("client", prefix="DEP_CLIENT_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field(
            "DEP_CLIENT_ENDPOINT", default="dependency-endpoint"
        )

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_CLIENT_",
        fields={"endpoint": rc.field("HOST_CLIENT_ENDPOINT", secret=True)},
        field_targets={"endpoint": "endpoint"},
    )

    @host.bundle
    @dataclass(kw_only=True)
    class HostSettings(rc.ConfigBase):
        client: ClientRC = dc_field(default_factory=ClientRC)  # pyright: ignore[reportInvalidTypeForm]

    resolved = host.resolve(
        environment={"HOST_CLIENT_ENDPOINT": "parent-secret-value"}
    )
    client = cast(Any, resolved.build(binding))
    bundle = resolved.build(HostSettings)

    assert client.to_dict()["endpoint"] == "<redacted>"
    assert bundle.to_dict()["client"]["endpoint"] == "<redacted>"
    assert ClientRC.__dataclass_fields__["endpoint"].repr is True
    assert binding.runtime_config_type is not ClientRC

    caplog.set_level(logging.WARNING, logger="apprc.runtime.config.base")
    client.endpoint = "mutated-parent-secret"
    assert "mutated-parent-secret" not in caplog.text
    assert "<redacted>" in caplog.text


def test_alias_source_binds_siblings_when_one_field_is_overridden(
    tmp_path: Path,
) -> None:
    """A Python override protects only its alias field, not the shared key."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    resolved = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "test-secret",
            "HOST_CLIENT_CHAT_MODEL": "source-model",
        }
    )

    client = cast(
        Any,
        resolved.build(binding, model_llm="constructor-model"),
    )
    assert client.model_llm == "constructor-model"
    assert client.model_fast == "source-model"
    assert client.provenance_of("model_fast").env_key == (
        "HOST_CLIENT_CHAT_MODEL"
    )
    assert client.provenance_of("model_fast").origin == (
        "shell_export_variable"
    )
    unprefixed = client.current_env_mapping(prefixed=False)
    assert unprefixed["CHAT_MODEL"] == "source-model"
    assert "HOST_CLIENT_CHAT_MODEL" not in unprefixed

    client.model_llm = "assigned-model"
    client.reload_from(resolved)
    assert client.model_llm == "assigned-model"
    assert client.model_fast == "source-model"
    assert client.provenance_of("model_fast").origin == (
        "shell_export_variable"
    )
    client.reload_from(resolved, override_python_values=True)
    assert client.model_llm == client.model_fast == "source-model"


def test_workspace_import_requires_valid_parent_selection(
    tmp_path: Path,
) -> None:
    """Workspace-bound dependency sections use only the selected parent root."""
    dependency_root = tmp_path / "dependency-workspace"
    dependency_root.mkdir()
    (dependency_root / "apprc.workspace.env").write_text(
        "PROVIDER_RAG_SOURCE=dependency-workspace\n",
        encoding="utf-8",
    )
    dependency = rc.AppRC(
        app_id="provider",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "dependency-home"),
        workspaces=rc.Workspaces(selector_env_key="PROVIDER_WORKSPACE"),
    )

    @dependency.config("rag", prefix="PROVIDER_RAG_", requires_workspace=True)
    class RagRC(rc.Config):
        source: str = rc.field("PROVIDER_RAG_SOURCE", default="dep-default")

    workspace_free_parent = rc.AppRC(app_id="workspace-free")
    with pytest.raises(ValueError):
        workspace_free_parent.import_dependency_config(
            dependency,
            RagRC,
            key="rag",
            prefix="FREE_RAG_",
            fields={"source": rc.field("FREE_RAG_SOURCE", default="parent")},
            field_targets={"source": "source"},
        )

    parent_root = tmp_path / "parent-workspace"
    parent_root.mkdir()
    (parent_root / "apprc.workspace.env").write_text(
        "HOST_RAG_SOURCE=parent-workspace\n",
        encoding="utf-8",
    )
    host = rc.AppRC(
        app_id="host",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "host-home"),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(selector_env_key="HOST_WORKSPACE"),
    )
    binding = host.import_dependency_config(
        dependency,
        RagRC,
        key="rag",
        prefix="HOST_RAG_",
        fields={"source": rc.field("HOST_RAG_SOURCE")},
        field_targets={"source": "source"},
    )
    assert binding.parent_owner.requires_workspace is True

    dependency_environment = {
        "PROVIDER_WORKSPACE": str(dependency_root),
        "PROVIDER_RAG_SOURCE": "dependency-environment",
    }
    same_namespace_parent = rc.AppRC(
        app_id="provider",
        paths=rc.Paths(config=True),
        workspaces=rc.Workspaces(selector_env_key="PROVIDER_WORKSPACE"),
    )
    with pytest.raises(ValueError, match="Dependency environment keys"):
        same_namespace_parent.import_dependency_config(
            dependency,
            RagRC,
            key="same-namespace-rag",
            prefix="HOST_RAG_",
            fields={"source": rc.field("HOST_RAG_SOURCE")},
            field_targets={"source": "source"},
        )

    absent = host.resolve(environment=dependency_environment)
    with pytest.raises(ValueError, match="valid workspace selection"):
        absent.build(binding)
    absent_inspection = host.manage(
        environment=dependency_environment
    ).inspect()
    assert absent_inspection.fields[0].active is False

    invalid_inspection = host.manage(
        environment=dependency_environment
    ).inspect(workspace="missing-workspace")
    assert invalid_inspection.fields[0].active is False
    with pytest.raises(ValueError, match="valid workspace selection"):
        invalid_inspection.resolved.build(binding)

    selected = host.resolve(
        rc.ResolveOptions(workspace=str(parent_root)),
        environment=dependency_environment,
    )
    assert selected.workspace is not None
    config = cast(Any, selected.build(binding))
    assert config.source == "parent-workspace"
    assert "PROVIDER_WORKSPACE" not in selected.values
    assert "PROVIDER_RAG_SOURCE" not in selected.values
    assert dependency_root / "apprc.workspace.env" not in tuple(
        layer.path for layer in selected.layers
    )
    config.reload_from(selected)
    with pytest.raises(ValueError, match="valid workspace selection"):
        config.reload_from(absent)


@pytest.mark.parametrize("root_state", ["missing", "uninitialized"])
def test_workspace_import_rejects_invalid_absolute_roots(
    tmp_path: Path,
    root_state: str,
) -> None:
    """Failed workspace paths stay inspectable but cannot build or reload."""
    dependency = rc.AppRC(
        app_id="provider",
        paths=rc.Paths(config=True),
        workspaces=rc.Workspaces(selector_env_key="PROVIDER_WORKSPACE"),
    )

    @dependency.config("rag", prefix="PROVIDER_RAG_", requires_workspace=True)
    class RagRC(rc.Config):
        source: str = rc.field("PROVIDER_RAG_SOURCE", default="dependency")

    host = rc.AppRC(
        app_id="host",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "host-home"),
        workspaces=rc.Workspaces(selector_env_key="HOST_WORKSPACE"),
    )
    binding = host.import_dependency_config(
        dependency,
        RagRC,
        key="rag",
        prefix="HOST_RAG_",
        fields={"source": rc.field("HOST_RAG_SOURCE")},
        field_targets={"source": "source"},
    )

    candidate_root = tmp_path / f"{root_state}-workspace"
    if root_state == "uninitialized":
        candidate_root.mkdir()
    inspection = host.manage(environment={}).inspect(
        workspace=str(candidate_root)
    )
    assert inspection.resolved.workspace is not None
    assert inspection.resolved.workspace.root == candidate_root.resolve()
    assert inspection.resolved.workspace_issues
    assert inspection.fields[0].active is False
    with pytest.raises(ValueError, match="valid workspace selection"):
        inspection.resolved.build(binding)

    initialized_root = tmp_path / "initialized-workspace"
    initialized_root.mkdir()
    (initialized_root / "apprc.workspace.env").write_text(
        "HOST_RAG_SOURCE=parent-workspace\n",
        encoding="utf-8",
    )
    valid = host.resolve(
        rc.ResolveOptions(workspace=str(initialized_root)),
        environment={},
    )
    config = valid.build(binding)
    assert config.source == "parent-workspace"
    with pytest.raises(ValueError, match="valid workspace selection"):
        config.reload_from(inspection.resolved)
    assert config.source == "parent-workspace"


def test_import_can_select_fields_and_keep_defaulted_dependency_fields(
    tmp_path: Path,
) -> None:
    """Unmapped settings keep Python defaults and ignore dependency inputs."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_CLIENT_",
        fields={
            "api_key": rc.field("HOST_CLIENT_API_KEY", secret=True),
            "endpoint": rc.field(
                "HOST_CLIENT_ENDPOINT", default="https://host.example"
            ),
        },
        field_targets={"api_key": "api_key", "base_url": "endpoint"},
    )

    resolved = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "host-secret",
            "DEP_BASE_URL": "https://ambient.example",
            "DEP_MODEL_LLM": "ambient-model",
            "DEP_MODEL_FAST": "ambient-model",
            "DEP_TIMEOUT": "80",
        }
    )
    client = cast(Any, resolved.build(binding))

    assert client.api_key == "host-secret"
    assert client.base_url == "https://host.example"
    assert client.model_llm == client.model_fast == "dependency-model"
    assert client.timeout == 5
    assert client.current_env_mapping() == {
        "HOST_CLIENT_API_KEY": "host-secret",
        "HOST_CLIENT_ENDPOINT": "https://host.example",
    }
    assert client.provenance_of("model_llm").origin == "python_config_default"
    assert "DEP_MODEL_LLM" not in resolved.values
    assert {item.name for item in binding.parent_owner.fields} == {
        "api_key",
        "endpoint",
    }


def test_required_parent_fields_do_not_fall_back_to_dependency_defaults() -> (
    None
):
    """Parent-required fields stay missing despite dependency defaults."""
    dependency = rc.AppRC(app_id="dependency")

    @dependency.config("client", prefix="DEP_CLIENT_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field(
            "DEP_CLIENT_ENDPOINT", default="dependency-endpoint"
        )
        token: str = rc.field(
            "DEP_CLIENT_TOKEN",
            default_factory=lambda: "dependency-factory-token",
        )

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_CLIENT_",
        fields={
            "endpoint": rc.field("HOST_CLIENT_ENDPOINT"),
            "token": rc.field("HOST_CLIENT_TOKEN"),
        },
        field_targets={"endpoint": "endpoint", "token": "token"},
    )

    empty = host.resolve(environment={})
    with pytest.raises(RuntimeError, match="Missing required config value"):
        empty.build(binding)

    supplied = host.resolve(
        environment={
            "HOST_CLIENT_ENDPOINT": "parent-endpoint",
            "HOST_CLIENT_TOKEN": "parent-token",
        }
    )
    config = supplied.build(binding)
    assert config.endpoint == "parent-endpoint"
    assert config.token == "parent-token"
    with pytest.raises(RuntimeError, match="Missing required config value"):
        config.reload_from(empty)
    assert config.endpoint == "parent-endpoint"
    assert config.token == "parent-token"


def test_omitted_secret_default_stays_redacted_on_imported_config() -> None:
    """Private runtime metadata preserves redaction for omitted fields."""
    dependency = rc.AppRC(app_id="dependency")

    @dependency.config("client", prefix="DEP_CLIENT_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field(
            "DEP_CLIENT_ENDPOINT", default="https://dependency.example"
        )
        token: str = rc.field(
            "DEP_CLIENT_TOKEN", default="dependency-secret", secret=True
        )

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_CLIENT_",
        fields={
            "endpoint": rc.field(
                "HOST_CLIENT_ENDPOINT",
                default="https://host.example",
                secret=True,
            )
        },
        field_targets={"endpoint": "endpoint"},
    )

    resolved = host.resolve(
        environment={
            "HOST_CLIENT_ENDPOINT": "https://private.example",
            "DEP_CLIENT_TOKEN": "ambient-secret",
        }
    )
    client = cast(Any, resolved.build(binding))

    assert client.token == "dependency-secret"
    assert client.provenance_of("token").secret is True
    assert "dependency-secret" not in repr(client)
    assert "ambient-secret" not in repr(client)


def test_parent_resolution_ignores_dependency_user_workspace_and_environment(
    tmp_path: Path,
) -> None:
    """Parent mode reads only its mapped fields and never dependency files."""
    dependency, ClientRC = _dependency(tmp_path)
    dependency_home = tmp_path / "dependency-apprc"
    dependency_config = dependency_home / "config"
    dependency_config.mkdir(parents=True)
    (dependency_config / "apprc.user.env").write_text(
        "DEP_API_KEY=user-file-secret\n", encoding="utf-8"
    )
    workspace_root = tmp_path / "dependency-workspace"
    workspace_root.mkdir()
    (workspace_root / "apprc.workspace.env").write_text(
        "DEP_API_KEY=workspace-file-secret\n", encoding="utf-8"
    )
    explicit_file = tmp_path / "host-inputs.env"
    explicit_file.write_text(
        "DEP_API_KEY=explicit-file-secret\n", encoding="utf-8"
    )
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")

    resolved = host.resolve(
        rc.ResolveOptions(env_files=(explicit_file,)),
        environment={
            "HOST_CLIENT_API_KEY": "host-secret",
            "DEP_API_KEY": "ambient-secret",
            "DEP_UNDECLARED_SETTING": "ambient-value",
        },
    )
    config = cast(Any, resolved.build(binding))
    standalone = cast(
        Any,
        dependency.resolve(
            rc.ResolveOptions(load_dotenv_layers=False),
            environment={
                "DEP_API_KEY": "standalone-secret",
                "DEP_BASE_URL": "https://standalone.example",
            },
        ).build(ClientRC),
    )

    assert config.api_key == "host-secret"
    assert config.base_url == "host-default-url"
    assert all(
        layer.path
        not in (
            dependency_config / "apprc.user.env",
            workspace_root / "apprc.workspace.env",
        )
        for layer in resolved.layers
    )
    assert standalone.api_key == "standalone-secret"
    assert standalone.base_url == "https://standalone.example"


def test_parent_dotenv_interpolation_excludes_dependency_assignments(
    tmp_path: Path,
) -> None:
    """A dependency assignment cannot feed a parent field in the same file."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    explicit = tmp_path / "host-inputs.env"
    explicit.write_text(
        "DEP_BASE_URL=file-dependency-value\n"
        "HOST_CLIENT_ENDPOINT=${DEP_BASE_URL:-parent-fallback}\n",
        encoding="utf-8",
    )

    resolved = host.resolve(
        rc.ResolveOptions(
            env_files=(explicit,),
            env_file_overrides_os_environ=True,
        ),
        environment={"HOST_CLIENT_API_KEY": "host-secret"},
    )
    config = cast(Any, resolved.build(binding))

    assert config.base_url == "parent-fallback"
    assert "DEP_BASE_URL" not in resolved.values


def test_standalone_dependency_config_rejects_parent_resolution_reload(
    tmp_path: Path,
) -> None:
    """A parent snapshot cannot reload an independently built dependency."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    standalone = dependency.resolve(
        environment={
            "DEP_API_KEY": "standalone-secret",
            "DEP_BASE_URL": "https://standalone.example",
        }
    ).build(ClientRC)
    parent_resolved = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "parent-secret",
            "HOST_CLIENT_ENDPOINT": "https://parent.example",
        }
    )
    before_values = standalone.to_dict()
    before_provenance = standalone.provenance()

    with pytest.raises(ValueError, match="Standalone dependency configs"):
        standalone.reload_from(parent_resolved)

    assert standalone.to_dict() == before_values
    assert standalone.provenance() == before_provenance
    imported = cast(Any, parent_resolved.build(binding))
    imported.reload_from(parent_resolved)
    assert imported.base_url == "https://parent.example"


def test_manager_paths_and_edit_preview_filter_dependency_environment(
    tmp_path: Path,
) -> None:
    """Management paths and edit previews use the runtime input boundary."""
    dependency, ClientRC = _dependency(tmp_path)
    parent_home = tmp_path / "parent-home"
    dependency_home = tmp_path / "dependency-home"
    host = rc.AppRC(
        app_id="host",
        paths=rc.Paths(config=True),
        user_dotenv=rc.UserDotenv(),
        bootstrap_env_prefix="HOST",
    )
    _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    explicit = tmp_path / "host-inputs.env"
    explicit.write_text(
        "HOST_LAYOUT=single-root\n"
        f"HOST_ROOT=${{DEP_LOCATION:-{parent_home}}}\n",
        encoding="utf-8",
    )
    manager = host.manage(
        rc.ResolveOptions(env_files=(explicit,)),
        environment={"DEP_LOCATION": str(dependency_home)},
    )

    runtime = manager.resolve()
    assert runtime.paths is not None
    assert manager.paths == runtime.paths
    assert manager.paths.layout.root == parent_home.resolve()
    manager.setup()

    plan = manager.plan_update("timeout", "12", scope="user")
    assert plan.path == manager.writable_path("user")
    plan = replace(
        plan,
        text=(
            "DEP_SHARED=preview-dependency-value\n"
            "HOST_CLIENT_ENDPOINT=${DEP_SHARED:-safe-parent}\n"
            "HOST_CLIENT_TIMEOUT=12\n"
        ),
    )
    preview = manager.preview_edit(plan)
    timeout = next(
        item for item in preview.fields if item.field.name == "timeout"
    )
    endpoint = next(
        item for item in preview.fields if item.field.name == "endpoint"
    )
    assert timeout.value == 12
    assert endpoint.value == "safe-parent"


def test_dependency_packaged_defaults_are_opt_in_and_below_parent_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only selected dependency package values participate when opted in."""
    dependency_package = _write_package(
        tmp_path,
        monkeypatch,
        "dependency_defaults",
        "DEP_API_KEY=dependency-packaged-secret\n"
        "DEP_BASE_URL=https://dependency-package.example\n"
        "DEP_MODEL_LLM=packaged-model\n"
        "DEP_MODEL_FAST=packaged-model\n"
        "DEP_TIMEOUT=20\n",
    )
    parent_package = _write_package(
        tmp_path,
        monkeypatch,
        "host_defaults",
        "HOST_CLIENT_ENDPOINT=https://parent-package.example\n",
    )
    dependency, ClientRC = _dependency(
        tmp_path, config_package=dependency_package
    )
    host = rc.AppRC(app_id="host", config_package=parent_package)
    binding = _host_import(
        host,
        dependency,
        ClientRC,
        prefix="HOST_CLIENT_",
        include_packaged_defaults=True,
    )

    resolved = host.resolve(environment={})
    config = cast(Any, resolved.build(binding))

    assert config.api_key == "dependency-packaged-secret"
    assert config.base_url == "https://parent-package.example"
    assert config.model_llm == config.model_fast == "packaged-model"
    assert config.timeout == 20
    assert config.provenance_of("api_key").resource == (
        dependency_package,
        "apprc.defaults.env",
    )
    assert config.provenance_of("base_url").resource == (
        parent_package,
        "apprc.defaults.env",
    )
    default_layers = [
        layer.resource
        for layer in resolved.layers
        if layer.origin == "shell_dotenv_defaults"
    ]
    assert default_layers == [
        (dependency_package, "apprc.defaults.env"),
        (parent_package, "apprc.defaults.env"),
    ]


def test_dependency_package_interpolation_cannot_read_ambient_dependency_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dependency namespace variables are removed before defaults expand."""
    dependency_package = _write_package(
        tmp_path,
        monkeypatch,
        "interpolated_dependency_defaults",
        "DEP_API_KEY=${DEP_DEFAULT_SECRET}\n",
    )
    dependency, ClientRC = _dependency(
        tmp_path, config_package=dependency_package
    )
    host = rc.AppRC(app_id="host")
    binding = _host_import(
        host,
        dependency,
        ClientRC,
        prefix="HOST_CLIENT_",
        include_packaged_defaults=True,
    )

    resolved = host.resolve(
        environment={"DEP_DEFAULT_SECRET": "ambient-secret"}
    )
    config = resolved.build(binding)

    assert config.api_key == ""
    assert config.provenance_of("api_key").origin == "shell_dotenv_defaults"
    assert "DEP_DEFAULT_SECRET" not in resolved.values
