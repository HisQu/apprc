"""Parent-owned dependency config imports stay within one resolution."""

import importlib
import logging
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass, field as dc_field
from pathlib import Path
from typing import Any, cast

import pytest
from typed_settings.exceptions import InvalidSettingsError

import apprc as rc


def _dependency(
    tmp_path: Path,
    *,
    config_package: str | None = None,
) -> tuple[rc.AppRC, type[Any]]:
    """Declare a dependency with a complete client section."""
    dependency = rc.AppRC(
        app_id="dependency",
        config_package=config_package,
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(),
        apprc_dir=tmp_path / "dependency-apprc",
    )

    @dependency.config("client", prefix="DEP_")
    class ClientRC(rc.Config):
        api_key: str = rc.field("DEP_API_KEY", secret=True)
        base_url: str = rc.field("DEP_BASE_URL", default="dependency-url")
        model_llm: str = rc.field("DEP_MODEL_LLM", default="dependency-model")
        model_fast: str = rc.field("DEP_MODEL_FAST", default="dependency-model")
        timeout: int = rc.field("DEP_TIMEOUT", default=5)

    return dependency, ClientRC


def _host_import(
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


def test_parent_apps_import_one_dependency_without_changing_its_owner(
    tmp_path: Path,
) -> None:
    """Different parents map the same section to independent namespaces."""
    dependency, ClientRC = _dependency(tmp_path)
    dependency_owner = ClientRC.config_owner
    first = rc.AppRC(app_id="first-host")
    second = rc.AppRC(app_id="second-host")
    first_binding = _host_import(
        first, dependency, ClientRC, prefix="FIRST_CLIENT_"
    )
    second_binding = _host_import(
        second, dependency, ClientRC, prefix="SECOND_CLIENT_"
    )

    first_resolved = first.resolve(
        environment={
            "FIRST_CLIENT_API_KEY": "first-secret",
            "FIRST_CLIENT_ENDPOINT": "https://first.example",
            "FIRST_CLIENT_CHAT_MODEL": "model-first",
            "DEP_API_KEY": "ambient-dependency-secret",
        }
    )
    second_resolved = second.resolve(
        environment={
            "SECOND_CLIENT_API_KEY": "second-secret",
            "SECOND_CLIENT_ENDPOINT": "https://second.example",
            "SECOND_CLIENT_CHAT_MODEL": "model-second",
        }
    )
    first_config = cast(Any, first_resolved.build(first_binding))
    second_config = cast(Any, second_resolved.build(second_binding))

    assert isinstance(first_config, ClientRC)
    assert first_config.api_key == "first-secret"
    assert first_config.base_url == "https://first.example"
    assert first_config.model_llm == first_config.model_fast == "model-first"
    assert second_config.api_key == "second-secret"
    assert second_config.base_url == "https://second.example"
    assert second_config.model_llm == second_config.model_fast == "model-second"
    assert ClientRC.config_owner is dependency_owner
    assert "DEP_API_KEY" not in first_resolved.values

    api_key_source = first_config.provenance_of("api_key")
    assert api_key_source.env_key == "FIRST_CLIENT_API_KEY"
    assert api_key_source.origin == "shell_export_variable"
    assert api_key_source.secret is True
    assert first_config.provenance_of("base_url").env_key == (
        "FIRST_CLIENT_ENDPOINT"
    )
    assert first_config.provenance_of("base_url").secret is True
    assert "https://first.example" not in repr(first_config)

    first_config.reload_from(first_resolved)
    with pytest.raises(ValueError, match="exact ImportedConfig binding"):
        first_config.reload_from(second_resolved)
    with pytest.raises(RuntimeError, match="ambient environment"):
        first_config.reload()
    with pytest.raises(RuntimeError, match="ambient environment"):
        first_config.bind_from_env()
    assert first_config.base_url == "https://first.example"


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


def test_import_binding_identity_survives_deepcopy_and_scoped_reload(
    tmp_path: Path,
) -> None:
    """Runtime copies reload only from the binding that created them."""
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
    copied = deepcopy(client)
    scoped = client.scoped(model_llm="scoped-model")

    copied.reload_from(resolved)
    assert copied.model_llm == "constructor-model"
    assert copied.model_fast == "source-model"
    copied.reload_from(resolved, override_python_values=True)
    assert copied.model_llm == copied.model_fast == "source-model"
    scoped.reload_from(resolved)
    assert scoped.model_llm == "scoped-model"
    assert scoped.model_fast == "source-model"
    scoped.reload_from(resolved, override_python_values=True)
    assert scoped.model_llm == scoped.model_fast == "source-model"

    other = rc.AppRC(app_id="other-host")
    other_binding = _host_import(
        other, dependency, ClientRC, prefix="OTHER_CLIENT_"
    )
    other_resolved = other.resolve(
        environment={"OTHER_CLIENT_CHAT_MODEL": "other-model"}
    )
    assert other_binding is not binding
    with pytest.raises(ValueError, match="exact ImportedConfig binding"):
        copied.reload_from(other_resolved)


def test_parent_can_import_two_maps_of_the_same_dependency_section(
    tmp_path: Path,
) -> None:
    """Distinct parent namespaces can reuse one dependency's source schema."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")

    def add_client(name: str, prefix: str) -> rc.ImportedConfig[Any]:
        return host.import_dependency_config(
            dependency,
            ClientRC,
            key=f"{name}.client",
            prefix=prefix,
            fields={
                "api_key": rc.field(f"{prefix}API_KEY", secret=True),
                "endpoint": rc.field(
                    f"{prefix}ENDPOINT", default=f"{name}-endpoint"
                ),
                "model": rc.field(f"{prefix}MODEL", default=f"{name}-model"),
            },
            field_targets={
                "api_key": "api_key",
                "base_url": "endpoint",
                "model_llm": "model",
                "model_fast": "model",
            },
        )

    first_binding = add_client("first", "FIRST_CLIENT_")
    second_binding = add_client("second", "SECOND_CLIENT_")
    resolved = host.resolve(
        environment={
            "FIRST_CLIENT_API_KEY": "first-secret",
            "FIRST_CLIENT_ENDPOINT": "https://first.example",
            "SECOND_CLIENT_API_KEY": "second-secret",
            "SECOND_CLIENT_ENDPOINT": "https://second.example",
        }
    )

    first = resolved.build(first_binding)
    second = resolved.build(second_binding)
    assert first.api_key == "first-secret"
    assert first.base_url == "https://first.example"
    assert second.api_key == "second-secret"
    assert second.base_url == "https://second.example"
    with pytest.raises(ValueError, match="multiple imported bindings"):
        resolved.build(ClientRC)


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

    client.model_llm = "assigned-model"
    client.reload_from(resolved)
    assert client.model_llm == "assigned-model"
    assert client.model_fast == "source-model"
    assert client.provenance_of("model_fast").origin == (
        "shell_export_variable"
    )
    client.reload_from(resolved, override_python_values=True)
    assert client.model_llm == client.model_fast == "source-model"


def test_storage_import_requires_valid_parent_selection(
    tmp_path: Path,
) -> None:
    """Storage-bound dependency sections use only selected parent storage."""
    dependency_home = tmp_path / "dependency-home"
    dependency_storage = tmp_path / "dependency-storage"
    dependency_home.mkdir()
    dependency_storage.mkdir()
    (dependency_home / "apprc.user.env").write_text(
        "PROVIDER_RAG_SOURCE=dependency-user\n", encoding="utf-8"
    )
    (dependency_storage / "apprc.storage.env").write_text(
        "PROVIDER_RAG_SOURCE=dependency-storage\n", encoding="utf-8"
    )
    dependency = rc.AppRC(
        app_id="provider",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="PROVIDER_STORAGE"),
        apprc_dir=dependency_home,
        apprc_dir_env_key="PROVIDER_APPRC_DIR",
    )

    @dependency.config("rag", prefix="PROVIDER_RAG_", requires_storage=True)
    class RagRC(rc.Config):
        source: str = rc.field("PROVIDER_RAG_SOURCE", default="dep-default")

    storage_free_parent = rc.AppRC(app_id="storage-free")
    with pytest.raises(ValueError, match="parent AppRC must declare storage"):
        storage_free_parent.import_dependency_config(
            dependency,
            RagRC,
            key="rag",
            prefix="FREE_RAG_",
            fields={"source": rc.field("FREE_RAG_SOURCE", default="parent")},
            field_targets={"source": "source"},
        )

    parent_home = tmp_path / "parent-home"
    parent_storage = tmp_path / "parent-storage"
    parent_storage.mkdir()
    (parent_storage / "apprc.storage.env").write_text(
        "HOST_RAG_SOURCE=parent-storage\n", encoding="utf-8"
    )
    host = rc.AppRC(
        app_id="host",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="HOST_STORAGE"),
        apprc_dir=parent_home,
        apprc_dir_env_key="HOST_APPRC_DIR",
    )
    binding = host.import_dependency_config(
        dependency,
        RagRC,
        key="rag",
        prefix="HOST_RAG_",
        fields={"source": rc.field("HOST_RAG_SOURCE")},
        field_targets={"source": "source"},
    )
    assert binding.parent_owner.requires_storage is True

    dependency_environment = {
        "PROVIDER_STORAGE": str(dependency_storage),
        "PROVIDER_APPRC_DIR": str(dependency_home),
        "PROVIDER_RAG_SOURCE": "dependency-environment",
    }

    same_namespace_parent = rc.AppRC(
        app_id="provider",
        storage=rc.Storage(selector_env_key="PROVIDER_STORAGE"),
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
    with pytest.raises(ValueError, match="valid storage selection"):
        absent.build(binding)
    absent_inspection = host.manage(
        environment=dependency_environment
    ).inspect()
    assert absent_inspection.fields[0].active is False

    invalid_inspection = host.manage(
        environment=dependency_environment
    ).inspect(storage="missing-storage")
    assert invalid_inspection.fields[0].active is False
    with pytest.raises(ValueError, match="valid storage selection"):
        invalid_inspection.resolved.build(binding)

    selected = host.resolve(
        rc.ResolveOptions(storage=str(parent_storage)),
        environment=dependency_environment,
    )
    assert selected.selection is not None
    config = cast(Any, selected.build(binding))
    assert config.source == "parent-storage"
    assert "PROVIDER_STORAGE" not in selected.values
    assert "PROVIDER_APPRC_DIR" not in selected.values
    assert "PROVIDER_RAG_SOURCE" not in selected.values
    assert all(
        layer.path
        not in (
            dependency_home / "apprc.user.env",
            dependency_storage / "apprc.storage.env",
        )
        for layer in selected.layers
    )
    config.reload_from(selected)
    with pytest.raises(ValueError, match="valid storage selection"):
        config.reload_from(absent)


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


def test_parent_resolution_ignores_dependency_user_storage_and_environment(
    tmp_path: Path,
) -> None:
    """Parent mode reads only its mapped fields and never dependency files."""
    dependency, ClientRC = _dependency(tmp_path)
    dependency_home = tmp_path / "dependency-apprc"
    dependency_home.mkdir()
    (dependency_home / "apprc.user.env").write_text(
        "DEP_API_KEY=user-file-secret\n", encoding="utf-8"
    )
    storage_root = tmp_path / "dependency-storage"
    storage_root.mkdir()
    (storage_root / "apprc.storage.env").write_text(
        "DEP_API_KEY=storage-file-secret\n", encoding="utf-8"
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
    assert "DEP_API_KEY" not in resolved.values
    assert "DEP_UNDECLARED_SETTING" not in resolved.values
    assert all(
        "DEP_API_KEY" not in layer.source.values for layer in resolved.layers
    )
    assert all(
        layer.path
        not in (
            dependency_home / "apprc.user.env",
            storage_root / "apprc.storage.env",
        )
        for layer in resolved.layers
    )
    assert standalone.api_key == "standalone-secret"
    assert standalone.base_url == "https://standalone.example"


def test_manager_paths_and_edit_preview_filter_dependency_environment(
    tmp_path: Path,
) -> None:
    """Management paths and edit previews use the runtime input boundary."""
    dependency, ClientRC = _dependency(tmp_path)
    parent_home = tmp_path / "parent-home"
    dependency_home = tmp_path / "dependency-home"
    host = rc.AppRC(
        app_id="host",
        user_dotenv=rc.UserDotenv(),
        apprc_dir=parent_home,
        apprc_dir_env_key="HOST_APPRC_DIR",
    )
    _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    explicit = tmp_path / "host-inputs.env"
    explicit.write_text("HOST_APPRC_DIR=${DEP_LOCATION}\n", encoding="utf-8")
    manager = host.manage(
        rc.ResolveOptions(env_files=(explicit,)),
        environment={"DEP_LOCATION": str(dependency_home)},
    )

    runtime = manager.resolve()
    assert runtime.paths is not None
    assert manager.paths == runtime.paths
    assert manager.paths.root == parent_home.resolve()
    manager.setup_user_dotenv()

    plan = manager.plan_update("timeout", "12", scope="user")
    assert plan.path == manager.paths.user_dotenv
    preview = manager.preview_edit(plan)
    timeout = next(
        item for item in preview.fields if item.field.name == "timeout"
    )
    assert timeout.value == 12


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


def test_import_binding_is_immutable_and_captures_snapshot_membership(
    tmp_path: Path,
) -> None:
    """Resolved imports retain captured fields after the parent changes."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    first_binding = _host_import(
        host, dependency, ClientRC, prefix="HOST_CLIENT_"
    )
    first = host.resolve(environment={"HOST_CLIENT_API_KEY": "first-secret"})

    with pytest.raises(FrozenInstanceError):
        setattr(first_binding, "include_packaged_defaults", True)
    with pytest.raises(TypeError):
        cast(Any, first_binding.field_targets)["api_key"] = "endpoint"

    other_dependency = rc.AppRC(app_id="other-dependency")

    @other_dependency.config("other", prefix="OTHER_")
    class OtherRC(rc.Config):
        value: str = rc.field("OTHER_VALUE", default="other-default")

    later_binding = host.import_dependency_config(
        other_dependency,
        OtherRC,
        key="other.settings",
        prefix="HOST_OTHER_",
        fields={"value": rc.field("HOST_OTHER_VALUE", default="parent")},
    )
    second = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "second-secret",
            "HOST_OTHER_VALUE": "later",
        }
    )

    assert cast(Any, first.build(first_binding)).api_key == "first-secret"
    assert cast(Any, second.build(first_binding)).api_key == "second-secret"
    with pytest.raises(ValueError, match="was not registered"):
        first.build(later_binding)
    assert cast(Any, second.build(later_binding)).value == "later"


def test_import_rejects_missing_fields_incompatible_aliases_and_secret_weakening(
    tmp_path: Path,
) -> None:
    """Invalid parent projections fail while the declaration is built."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")

    with pytest.raises(ValueError, match="must have Python defaults"):
        host.import_dependency_config(
            dependency,
            ClientRC,
            key="missing",
            prefix="MISSING_",
            fields={
                "endpoint": rc.field(
                    "MISSING_ENDPOINT", default="https://host.example"
                )
            },
            field_targets={"base_url": "endpoint"},
        )

    with pytest.raises(ValueError, match="cannot weaken secret"):
        host.import_dependency_config(
            dependency,
            ClientRC,
            key="weakened",
            prefix="WEAK_",
            fields={
                "api_key": rc.field("WEAK_API_KEY", default="fallback"),
                "endpoint": rc.field("WEAK_ENDPOINT", default="url"),
                "chat_model": rc.field("WEAK_MODEL", default="model"),
                "timeout": rc.field("WEAK_TIMEOUT", default=5),
            },
            field_targets={
                "api_key": "api_key",
                "base_url": "endpoint",
                "model_llm": "chat_model",
                "model_fast": "chat_model",
                "timeout": "timeout",
            },
        )

    other = rc.AppRC(app_id="other")

    @other.config("other", prefix="OTHER_")
    class OtherRC(rc.Config):
        text: str = rc.field("OTHER_TEXT", default="text")
        count: int = rc.field("OTHER_COUNT", default=1)

    with pytest.raises(TypeError, match="incompatible types"):
        host.import_dependency_config(
            other,
            OtherRC,
            key="bad-alias",
            prefix="BAD_",
            fields={"shared": rc.field("BAD_SHARED", default="value")},
            field_targets={"text": "shared", "count": "shared"},
        )


def test_import_validation_and_parent_env_key_collisions(
    tmp_path: Path,
) -> None:
    """Mapped values use parent validation and owner collision rules."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    resolved = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "secret",
            "HOST_CLIENT_TIMEOUT": "not-an-int",
        }
    )
    with pytest.raises(InvalidSettingsError):
        resolved.build(binding)

    colliding_host = rc.AppRC(app_id="collision")

    @colliding_host.config("local", prefix="HOST_CLIENT_")
    class LocalRC(rc.Config):
        endpoint: str = rc.field("HOST_CLIENT_ENDPOINT", default="local")

    with pytest.raises(ValueError, match="Duplicate env key"):
        _host_import(
            colliding_host,
            dependency,
            ClientRC,
            prefix="HOST_CLIENT_",
        )


def test_bundle_injects_imported_child_from_same_parent_snapshot(
    tmp_path: Path,
) -> None:
    """Imported bundle children use the captured parent resolver once."""
    dependency, ClientRC = _dependency(tmp_path)
    host = rc.AppRC(app_id="host")
    binding = _host_import(host, dependency, ClientRC, prefix="HOST_CLIENT_")
    post_init_values: list[str] = []

    @host.bundle
    @dataclass(kw_only=True)
    class HostSettings:
        client: ClientRC = dc_field(default_factory=ClientRC)  # pyright: ignore[reportInvalidTypeForm]

        def __post_init__(self) -> None:
            post_init_values.append(self.client.api_key)

    @host.bundle
    @dataclass(kw_only=True)
    class CustomFactory:
        client: ClientRC = dc_field(  # pyright: ignore[reportInvalidTypeForm]
            default_factory=lambda: ClientRC(api_key="factory-secret")
        )

    with pytest.raises(TypeError, match="requires the parent ResolvedConfig"):
        HostSettings()

    resolved = host.resolve(
        environment={
            "HOST_CLIENT_API_KEY": "bundle-secret",
            "HOST_CLIENT_ENDPOINT": "https://bundle.example",
        }
    )
    bundle = resolved.build(HostSettings)

    assert bundle.client.api_key == "bundle-secret"
    assert bundle.client.base_url == "https://bundle.example"
    assert post_init_values == ["bundle-secret"]
    assert cast(Any, resolved.build(binding)).api_key == "bundle-secret"

    with pytest.raises(TypeError, match="Inject 'client' explicitly"):
        resolved.build(CustomFactory)
    explicit_client = resolved.build(binding)
    assert (
        resolved.build(CustomFactory, client=explicit_client).client
        is explicit_client
    )
