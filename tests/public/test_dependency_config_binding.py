"""Imported config bindings retain ownership across app lifecycle steps."""

from copy import deepcopy
from dataclasses import (
    FrozenInstanceError,
    dataclass,
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


def test_imported_mapped_fields_skip_dependency_default_factories() -> None:
    """Imported construction uses only parent defaults and sources."""
    dependency = rc.AppRC(app_id="dependency")
    factory_calls: list[str] = []

    def unavailable_dependency_default() -> str:
        factory_calls.append("called")
        raise RuntimeError("dependency default is unavailable")

    @dependency.config("client", prefix="DEP_CLIENT_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field(
            "DEP_CLIENT_ENDPOINT",
            default_factory=unavailable_dependency_default,
        )

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="OTHER_HOST_",
        fields={
            "endpoint": rc.field(
                "OTHER_HOST_ENDPOINT", default="parent-default"
            )
        },
    )

    defaulted = host.resolve(environment={}).build(binding)
    assert defaulted.endpoint == "parent-default"
    assert defaulted.provenance_of("endpoint").origin == "python_config_default"
    assert factory_calls == []

    sourced = host.resolve(
        environment={"OTHER_HOST_ENDPOINT": "parent-source"}
    ).build(binding)
    assert sourced.endpoint == "parent-source"
    assert sourced.provenance_of("endpoint").origin == "shell_export_variable"
    assert factory_calls == []

    with pytest.raises(RuntimeError, match="dependency default is unavailable"):
        ClientRC()
    assert factory_calls == ["called"]


def test_import_metadata_is_available_during_dependency_post_init() -> None:
    """Dependency hooks see parent mapping tags before base post-init returns."""
    dependency = rc.AppRC(app_id="dependency")
    hook_mappings: list[tuple[dict[str, str], dict[str, str]]] = []

    @dependency.config("client", prefix="DEP_CLIENT_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field(
            "DEP_CLIENT_ENDPOINT", default="dependency-endpoint"
        )
        local_label: str = rc.field(
            "DEP_CLIENT_LOCAL_LABEL", default="dependency-label"
        )

        def __post_init__(self) -> None:
            """Record the mapping exposed after base initialization."""
            super().__post_init__()
            hook_mappings.append(
                (
                    self.current_env_mapping(),
                    self.current_env_mapping(prefixed=False),
                )
            )

    standalone = ClientRC(bind_from_env_on_init=False)
    assert standalone._apprc_imported_field_names is None
    assert standalone._apprc_imported_binding is None
    assert standalone.current_env_mapping() == {
        "DEP_CLIENT_ENDPOINT": "dependency-endpoint",
        "DEP_CLIENT_LOCAL_LABEL": "dependency-label",
    }
    hook_mappings.clear()

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_CLIENT_",
        fields={
            "api_endpoint": rc.field(
                "HOST_CLIENT_API_ENDPOINT", default="host-endpoint"
            )
        },
        field_targets={"endpoint": "api_endpoint"},
    )
    resolved = host.resolve(
        environment={"HOST_CLIENT_API_ENDPOINT": "parent-source"}
    )
    imported = cast(Any, resolved.build(binding))

    expected = {
        "HOST_CLIENT_API_ENDPOINT": "parent-source",
    }
    assert hook_mappings == [(expected, {"API_ENDPOINT": "parent-source"})]

    imported.local_label = "python-only"
    imported.reload_from(resolved)
    assert imported.local_label == "python-only"
    assert imported.provenance_of("local_label").origin == (
        "python_runtime_assignment"
    )
    assert imported.current_env_mapping() == expected
    assert imported.endpoint == "parent-source"
    with pytest.raises(TypeError, match="resolution state is reserved"):
        resolved.build(binding, _apprc_imported_binding=binding)
    with pytest.raises(TypeError, match="resolution state is reserved"):
        resolved.build(
            binding,
            _apprc_imported_field_names=frozenset({"endpoint"}),
        )


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


def test_alias_default_factory_resolves_once_during_build_and_reload() -> None:
    """Aliased dependency fields share one resolved parent default value."""
    dependency = rc.AppRC(app_id="dependency")
    factory_values: list[int] = []

    def next_shared_value() -> int:
        value = 10 + len(factory_values)
        factory_values.append(value)
        return value

    @dependency.config("client", prefix="DEP_")
    class ClientRC(rc.Config):
        first: int = rc.field("DEP_FIRST", default=1)
        second: int = rc.field("DEP_SECOND", default=2)
        third: int = rc.field("DEP_THIRD", default=3)

    host = rc.AppRC(app_id="host")
    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="client",
        prefix="HOST_",
        fields={
            "shared": rc.field("HOST_SHARED", default_factory=next_shared_value)
        },
        field_targets={
            "first": "shared",
            "second": "shared",
            "third": "shared",
        },
    )
    resolved = host.resolve(environment={})

    config = cast(Any, resolved.build(binding, first=99))
    assert config.first == 99
    assert config.second == config.third == 10
    assert factory_values == [10]
    assert config.current_env_mapping(prefixed=False) == {"SHARED": "10"}

    config.reload_from(resolved)
    assert config.first == 99
    assert config.second == config.third == 11
    assert factory_values == [10, 11]

    config.reload_from(resolved, override_python_values=True)
    assert config.first == config.second == config.third == 12
    assert factory_values == [10, 11, 12]


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
