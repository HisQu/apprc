"""Dependency imports validate declarations before mutating the parent."""

from dataclasses import (
    field as dc_field,
)
from pathlib import Path
from typing import Any

import pytest
from typed_settings.exceptions import InvalidSettingsError

import apprc as rc
from tests.support_dependency_config import (
    dependency as _dependency,
    host_import as _host_import,
)


def _single_field_dependency() -> tuple[rc.AppRC, type[Any]]:
    """Declare a small dependency section for owner-key collision tests."""
    dependency = rc.AppRC(app_id="single-field-dependency")

    @dependency.config("client", prefix="DEP_")
    class ClientRC(rc.Config):
        endpoint: str = rc.field("DEP_ENDPOINT", default="dependency")

    return dependency, ClientRC


def _import_single_field_client(
    host: rc.AppRC,
    dependency: rc.AppRC,
    config_type: type[Any],
) -> rc.ImportedConfig[Any]:
    """Import a small dependency section using the colliding owner key."""
    return host.import_dependency_config(
        dependency,
        config_type,
        key="client",
        prefix="HOST_IMPORTED_",
        fields={
            "endpoint": rc.field(
                "HOST_IMPORTED_ENDPOINT", default="host-default"
            )
        },
    )


def test_import_rejects_mapped_init_false_fields_before_registration() -> None:
    """Mapped imported fields must accept parent values at construction."""
    dependency = rc.AppRC(app_id="dependency")
    endpoint_declaration = rc.field("DEP_ENDPOINT", default="dependency")

    @dependency.config("client", prefix="DEP_")
    class ClientRC(rc.Config):
        endpoint: str = dc_field(
            init=False,
            default="dependency",
            metadata=endpoint_declaration.metadata,
        )

    host = rc.AppRC(app_id="host")
    schema_before = host.schema
    registered_by_key_before = dict(host._registered_by_key)
    registered_by_type_before = dict(host._registered_by_type)
    env_key_index_before = dict(host._env_key_index)

    with pytest.raises(
        TypeError,
        match="Mapped dependency fields must be dataclass init=True fields: endpoint",
    ):
        host.import_dependency_config(
            dependency,
            ClientRC,
            key="client",
            prefix="HOST_CLIENT_",
            fields={
                "endpoint": rc.field(
                    "HOST_CLIENT_ENDPOINT", default="host-default"
                )
            },
        )

    assert host.schema is schema_before
    assert host._registered_by_key == registered_by_key_before
    assert host._registered_by_type == registered_by_type_before
    assert host._env_key_index == env_key_index_before

    @host.config("valid", prefix="HOST_VALID_")
    class ValidRC(rc.Config):
        value: str = rc.field("HOST_VALID_VALUE", default="valid")

    resolved = host.resolve(environment={"HOST_VALID_VALUE": "ready"})
    assert resolved.build(ValidRC).value == "ready"


def test_later_import_rejects_parent_field_matching_prior_control_key(
    tmp_path: Path,
) -> None:
    """A previous dependency control key cannot become a parent setting."""
    first_dependency = rc.AppRC(
        app_id="first-dependency",
        paths=rc.Paths(config=True),
        workspaces=rc.Workspaces(selector_env_key="CUSTOM_DEP_CONTROL"),
    )

    @first_dependency.config("section", prefix="FIRST_DEP_")
    class FirstRC(rc.Config):
        value: str = rc.field("FIRST_DEP_VALUE", default="first")

    later_dependency = rc.AppRC(app_id="later-dependency")

    @later_dependency.config("section", prefix="LATER_DEP_")
    class LaterRC(rc.Config):
        value: str = rc.field("LATER_DEP_VALUE", default="later")

    host = rc.AppRC(app_id="host")
    host.import_dependency_config(
        first_dependency,
        FirstRC,
        key="first",
        prefix="HOST_FIRST_",
        fields={"value": rc.field("HOST_FIRST_VALUE", default="host")},
        field_targets={"value": "value"},
    )

    with pytest.raises(ValueError, match="environment"):
        host.import_dependency_config(
            later_dependency,
            LaterRC,
            key="later",
            prefix="CUSTOM_DEP_",
            fields={"value": rc.field("CUSTOM_DEP_CONTROL", default="host")},
            field_targets={"value": "value"},
        )
    assert len(host.schema.owners) == 1


@pytest.mark.parametrize(
    ("control_kind", "control_key", "host_options"),
    [
        (
            "workspace",
            "VENDOR_WORKSPACE",
            {
                "paths": rc.Paths(config=True),
                "workspaces": rc.Workspaces(
                    selector_env_key="VENDOR_WORKSPACE"
                ),
            },
        ),
        (
            "root",
            "VENDOR_PARENT_HOME_ROOT",
            {
                "paths": rc.Paths(config=True),
                "user_dotenv": rc.UserDotenv(),
                "bootstrap_env_prefix": "VENDOR_PARENT_HOME",
            },
        ),
    ],
)
def test_import_rejects_dependency_prefix_covering_parent_controls(
    control_kind: str,
    control_key: str,
    host_options: dict[str, Any],
) -> None:
    """Dependency field prefixes cannot hide parent storage or path inputs."""
    dependency = rc.AppRC(app_id="vendor")

    @dependency.config("section", prefix="VENDOR_")
    class VendorRC(rc.Config):
        value: str = rc.field("VENDOR_VALUE", default="vendor")

    host = rc.AppRC(app_id="host", **host_options)
    assert control_key in {
        host.schema.workspace_selector_env_key,
        host.schema.root_env_key,
    }
    with pytest.raises(ValueError, match="environment"):
        host.import_dependency_config(
            dependency,
            VendorRC,
            key=f"vendor.{control_kind}",
            prefix="HOST_VENDOR_",
            fields={"value": rc.field("HOST_VENDOR_VALUE", default="host")},
            field_targets={"value": "value"},
        )
    assert host.schema.owners == ()


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


def test_imported_owner_key_rejects_python_only_registration_before_mutation() -> (
    None
):
    """Imported owner keys cannot be reused by Python-only direct configs."""
    dependency, ClientRC = _single_field_dependency()
    host = rc.AppRC(app_id="host")
    binding = _import_single_field_client(host, dependency, ClientRC)
    schema_before = host.schema
    registered_by_key_before = dict(host._registered_by_key)
    registered_by_type_before = dict(host._registered_by_type)
    env_key_index_before = dict(host._env_key_index)

    class ConflictingRC(rc.ConfigBase):
        label: str = "local"

    with pytest.raises(ValueError, match='AppRC owner key "client"'):
        host.config("client")(ConflictingRC)

    assert host.schema is schema_before
    assert host._registered_by_key == registered_by_key_before
    assert host._registered_by_type == registered_by_type_before
    assert host._env_key_index == env_key_index_before
    assert "__dataclass_fields__" not in ConflictingRC.__dict__

    @host.config("valid", prefix="HOST_VALID_")
    class ValidRC(rc.Config):
        value: str = rc.field("HOST_VALID_VALUE", default="valid")

    resolved = host.resolve(environment={"HOST_VALID_VALUE": "ready"})
    assert resolved.build(ValidRC).value == "ready"
    assert resolved.build(binding).endpoint == "host-default"


def test_imported_owner_key_rejects_env_registration_before_mutation() -> None:
    """Failed env config registration leaves the owner registries usable."""
    dependency, ClientRC = _single_field_dependency()
    host = rc.AppRC(app_id="host")
    binding = _import_single_field_client(host, dependency, ClientRC)
    schema_before = host.schema
    registered_by_key_before = dict(host._registered_by_key)
    registered_by_type_before = dict(host._registered_by_type)
    env_key_index_before = dict(host._env_key_index)

    class ConflictingRC(rc.Config):
        value: str = rc.field("HOST_CONFLICT_VALUE", default="conflict")

    with pytest.raises(ValueError, match='AppRC owner key "client"'):
        host.config("client", prefix="HOST_CONFLICT_")(ConflictingRC)

    assert host.schema is schema_before
    assert host._registered_by_key == registered_by_key_before
    assert host._registered_by_type == registered_by_type_before
    assert host._env_key_index == env_key_index_before

    @host.config("valid", prefix="HOST_VALID_")
    class ValidRC(rc.Config):
        value: str = rc.field("HOST_VALID_VALUE", default="valid")

    resolved = host.resolve(environment={"HOST_VALID_VALUE": "ready"})
    assert resolved.build(ValidRC).value == "ready"
    assert resolved.build(binding).endpoint == "host-default"


def test_direct_owner_key_rejects_later_import_and_parent_remains_usable() -> (
    None
):
    """A later import cannot reuse a directly registered owner key."""
    dependency, ClientRC = _single_field_dependency()
    host = rc.AppRC(app_id="host")

    @host.config("client", prefix="HOST_CLIENT_")
    class LocalClient(rc.Config):
        endpoint: str = rc.field("HOST_CLIENT_ENDPOINT", default="local")

    schema_before = host.schema
    registered_by_key_before = dict(host._registered_by_key)
    registered_by_type_before = dict(host._registered_by_type)
    env_key_index_before = dict(host._env_key_index)

    with pytest.raises(ValueError, match='AppRC owner key "client"'):
        _import_single_field_client(host, dependency, ClientRC)

    assert host.schema is schema_before
    assert host._registered_by_key == registered_by_key_before
    assert host._registered_by_type == registered_by_type_before
    assert host._env_key_index == env_key_index_before

    @host.config("valid", prefix="HOST_VALID_")
    class ValidRC(rc.Config):
        value: str = rc.field("HOST_VALID_VALUE", default="valid")

    resolved = host.resolve(environment={"HOST_CLIENT_ENDPOINT": "local"})
    assert resolved.build(LocalClient).endpoint == "local"
    assert resolved.build(ValidRC).value == "valid"


def test_direct_owner_path_collision_fails_before_registration_mutation() -> (
    None
):
    """A direct owner's field path cannot poison later registrations."""
    dependency, ClientRC = _single_field_dependency()
    host = rc.AppRC(app_id="host")
    binding = _import_single_field_client(host, dependency, ClientRC)
    schema_before = host.schema
    registered_by_key_before = dict(host._registered_by_key)
    registered_by_type_before = dict(host._registered_by_type)
    env_key_index_before = dict(host._env_key_index)

    class ConflictingRC(rc.Config):
        endpoint: str = rc.field("HOST_DIRECT_ENDPOINT", default="direct")

    with pytest.raises(ValueError, match="Duplicate config path"):
        host.config(
            "direct",
            prefix="HOST_DIRECT_",
            rc_path=("client",),
        )(ConflictingRC)

    assert host.schema is schema_before
    assert host._registered_by_key == registered_by_key_before
    assert host._registered_by_type == registered_by_type_before
    assert host._env_key_index == env_key_index_before
    assert ConflictingRC.__dict__.get("config_owner") is None

    @host.config("valid", prefix="HOST_VALID_")
    class ValidRC(rc.Config):
        value: str = rc.field("HOST_VALID_VALUE", default="valid")

    resolved = host.resolve(environment={"HOST_VALID_VALUE": "ready"})
    assert resolved.build(ValidRC).value == "ready"
    assert resolved.build(binding).endpoint == "host-default"


def test_failed_import_path_collision_can_be_corrected() -> None:
    """A rejected imported path does not reserve its key or environment data."""
    dependency, ClientRC = _single_field_dependency()
    host = rc.AppRC(app_id="host")

    @host.config("local", prefix="HOST_LOCAL_", rc_path=("client",))
    class LocalClient(rc.Config):
        endpoint: str = rc.field("HOST_LOCAL_ENDPOINT", default="local")

    schema_before = host.schema

    with pytest.raises(ValueError, match="Duplicate config path"):
        host.import_dependency_config(
            dependency,
            ClientRC,
            key="imported",
            prefix="HOST_IMPORTED_",
            fields={
                "endpoint": rc.field(
                    "HOST_IMPORTED_ENDPOINT", default="imported"
                )
            },
            rc_path=("client",),
        )

    assert host.schema is schema_before
    local_resolved = host.resolve(
        environment={"HOST_LOCAL_ENDPOINT": "local-value"}
    )
    assert local_resolved.build(LocalClient).endpoint == "local-value"

    binding = host.import_dependency_config(
        dependency,
        ClientRC,
        key="imported",
        prefix="HOST_IMPORTED_",
        fields={
            "endpoint": rc.field("HOST_IMPORTED_ENDPOINT", default="imported")
        },
        rc_path=("imported",),
    )
    resolved = host.resolve(
        environment={
            "HOST_LOCAL_ENDPOINT": "local-value",
            "HOST_IMPORTED_ENDPOINT": "imported-value",
        }
    )

    assert resolved.build(LocalClient).endpoint == "local-value"
    assert resolved.build(binding).endpoint == "imported-value"


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
