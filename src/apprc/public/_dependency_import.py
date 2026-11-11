"""Prepare parent-owned dependency bindings without changing registrations."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Set
from dataclasses import dataclass, fields
from typing import Any, Generic, TypeVar, cast

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config._validation import validate_config_owner
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.resolution import ImportedConfig
from apprc.public._config_registration import _humanize_title, _validate_prefix
from apprc.public.config import Config, ConfigBase
from apprc.public.field import (
    _FIELD_DECLARATION_METADATA_KEY,
    _FieldDeclaration,
)

ConfigInstanceT = TypeVar("ConfigInstanceT", bound=ConfigBase)


@dataclass(frozen=True, slots=True)
class _PreparedDependencyConfig(Generic[ConfigInstanceT]):
    """Carry a validated dependency binding and its pending registry entries."""

    binding: ImportedConfig[ConfigInstanceT]
    env_key_entries: dict[str, tuple[str, str]]
    source_env_keys: frozenset[str]


def _prepare_dependency_config(
    *,
    config_type: type[ConfigInstanceT],
    dependency_schema: AppConfigSpec,
    dependency_owner: ConfigOwner,
    dependency_env_prefixes: tuple[str, ...],
    parent_schema: AppConfigSpec,
    parent_registered_keys: Set[str],
    parent_registered_types: Set[type[ConfigBase]],
    parent_env_keys: Set[str],
    parent_source_env_keys: Set[str],
    parent_control_env_keys: Set[str],
    parent_dependency_env_prefixes: Set[str],
    key: str,
    prefix: str,
    fields: Mapping[str, dataclasses.Field[Any]],
    field_targets: Mapping[str, str] | None = None,
    title: str | None = None,
    rc_path: tuple[str, ...] | None = None,
    include_packaged_defaults: bool = False,
) -> _PreparedDependencyConfig[ConfigInstanceT]:
    """Validate a candidate import without changing live registrations."""
    if config_type in parent_registered_types:
        raise ValueError(
            f"{config_type.__name__} is already registered directly on "
            "the parent AppRC; import it through a separate config class."
        )
    if dependency_owner.requires_workspace and parent_schema.workspaces is None:
        raise ValueError(
            f"{config_type.__name__} requires a workspace; the parent "
            "AppRC must declare workspaces=rc.Workspaces()."
        )
    if include_packaged_defaults and dependency_schema.config_package is None:
        raise ValueError(
            "include_packaged_defaults=True requires the dependency "
            "AppRC to declare config_package."
        )
    if key in parent_registered_keys or any(
        owner.key == key for owner in parent_schema.owners
    ):
        raise ValueError(f'AppRC owner key "{key}" is already in use.')

    normalized_fields = _import_field_declarations(fields)
    source_names = {item.name for item in dependency_owner.fields}
    if field_targets is None:
        targets = {name: name for name in source_names}
    else:
        targets = dict(field_targets)
    if not set(targets) <= source_names:
        unknown = sorted(set(targets) - source_names)
        raise ValueError(
            "field_targets contains unknown dependency fields: "
            + ", ".join(unknown)
            + "."
        )
    dependency_dataclass_fields = {
        item.name: item for item in dataclasses.fields(config_type)
    }
    non_init_fields = sorted(
        field_name
        for field_name in targets
        if not dependency_dataclass_fields[field_name].init
    )
    if non_init_fields:
        raise TypeError(
            "Mapped dependency fields must be dataclass init=True fields: "
            + ", ".join(non_init_fields)
            + "."
        )
    unmapped = source_names - set(targets)
    unmapped_without_defaults = sorted(
        field_name
        for field_name in unmapped
        if not dependency_owner.field(field_name).has_default()
    )
    if unmapped_without_defaults:
        raise ValueError(
            "Unmapped dependency fields must have Python defaults: "
            + ", ".join(unmapped_without_defaults)
            + "."
        )
    if set(targets.values()) != set(normalized_fields):
        unused = sorted(set(normalized_fields) - set(targets.values()))
        unknown = sorted(set(targets.values()) - set(normalized_fields))
        details = []
        if unused:
            details.append(f"unused parent fields: {', '.join(unused)}")
        if unknown:
            details.append(f"undeclared parent fields: {', '.join(unknown)}")
        raise ValueError(
            "field_targets must use every parent field exactly as needed; "
            + "; ".join(details)
            + "."
        )

    parent_title = title or _humanize_title(key)
    parent_rc_path = rc_path or (key,)
    parent_owner = _build_imported_owner(
        config_type,
        key=key,
        title=parent_title,
        prefix=prefix,
        rc_path=parent_rc_path,
        declared_fields=normalized_fields,
        targets=targets,
        dependency_owner=dependency_owner,
        requires_workspace=dependency_owner.requires_workspace,
    )
    imported_source_keys = {dependency_owner.env_key(name) for name in targets}
    mapped_parent_keys = {
        parent_owner.env_key(item.name) for item in parent_owner.fields
    }
    dependency_control_env_keys = tuple(
        key
        for key in (
            dependency_schema.workspace_selector_env_key,
            dependency_schema.layout_env_key,
            dependency_schema.root_env_key,
        )
        if key is not None
    )
    dependency_control_keys = set(dependency_control_env_keys)
    parent_control_keys = {
        key
        for key in (
            parent_schema.workspace_selector_env_key,
            parent_schema.layout_env_key,
            parent_schema.root_env_key,
        )
        if key is not None
    }
    parent_keys = set(parent_env_keys) | mapped_parent_keys
    parent_keys.update(parent_control_keys)
    excluded_dependency_keys = (
        parent_source_env_keys
        | parent_control_env_keys
        | imported_source_keys
        | dependency_control_keys
    )
    excluded_dependency_env_prefixes = parent_dependency_env_prefixes | set(
        dependency_env_prefixes
    )
    collisions = parent_keys & excluded_dependency_keys
    collisions.update(
        key
        for key in parent_keys
        if any(
            key.startswith(prefix)
            for prefix in excluded_dependency_env_prefixes
        )
    )
    collisions.update(imported_source_keys & parent_control_env_keys)
    collisions.update(
        dependency_control_keys
        & (imported_source_keys | parent_source_env_keys)
    )
    if collisions:
        joined = ", ".join(sorted(collisions))
        raise ValueError(
            "Dependency environment keys and prefixes cannot overlap "
            f"parent inputs or another import: {joined}."
        )
    runtime_owner = _dependency_runtime_owner(
        parent_owner=parent_owner,
        dependency_owner=dependency_owner,
        field_targets=targets,
    )
    runtime_config_type = _secret_safe_dependency_type(
        config_type, runtime_owner
    )
    binding = ImportedConfig(
        dependency_app_id=dependency_schema.app_id,
        config_type=config_type,
        parent_owner=parent_owner,
        dependency_owner=dependency_owner,
        runtime_owner=runtime_owner,
        field_targets=targets,
        dependency_env_prefixes=dependency_env_prefixes,
        dependency_control_env_keys=dependency_control_env_keys,
        config_package=dependency_schema.config_package,
        include_packaged_defaults=include_packaged_defaults,
        runtime_config_type=runtime_config_type,
    )
    env_key_entries = {
        parent_owner.env_key(field_spec.name): (
            f"{dependency_schema.app_id}.{config_type.__name__}",
            field_spec.name,
        )
        for field_spec in parent_owner.fields
    }
    return _PreparedDependencyConfig(
        binding=binding,
        env_key_entries=env_key_entries,
        source_env_keys=frozenset(imported_source_keys),
    )


def _import_field_declarations(
    fields_by_name: Mapping[str, dataclasses.Field[Any]],
) -> dict[str, _FieldDeclaration]:
    """Normalize explicit parent declarations for imported fields."""
    if not isinstance(fields_by_name, Mapping) or not fields_by_name:
        raise TypeError(
            "fields must be a non-empty mapping of rc.field declarations."
        )
    normalized: dict[str, _FieldDeclaration] = {}
    for field_name, dataclass_field in fields_by_name.items():
        if not isinstance(field_name, str) or not field_name:
            raise TypeError("Parent field names must be non-empty strings.")
        if not isinstance(dataclass_field, dataclasses.Field):
            raise TypeError(
                f"fields[{field_name!r}] must be declared with rc.field(...)."
            )
        declaration = dataclass_field.metadata.get(
            _FIELD_DECLARATION_METADATA_KEY
        )
        if not isinstance(declaration, _FieldDeclaration):
            raise TypeError(
                f"fields[{field_name!r}] must be declared with rc.field(...)."
            )
        normalized[field_name] = declaration
    return normalized


def _build_imported_owner(
    config_type: type[ConfigBase],
    *,
    key: str,
    title: str,
    prefix: str,
    rc_path: tuple[str, ...],
    declared_fields: Mapping[str, _FieldDeclaration],
    targets: Mapping[str, str],
    dependency_owner: ConfigOwner,
    requires_workspace: bool,
) -> ConfigOwner:
    """Build and validate parent-owned fields for an imported section."""
    if not prefix:
        raise ValueError("import_dependency_config(...) requires a prefix.")
    target_specs = {
        field_name: dependency_owner.field(field_name) for field_name in targets
    }
    fields_by_parent: dict[str, list[str]] = {}
    for dependency_field, parent_field in targets.items():
        fields_by_parent.setdefault(parent_field, []).append(dependency_field)

    fields: list[ConfigField] = []
    for parent_field, declaration in declared_fields.items():
        dependency_fields = fields_by_parent[parent_field]
        source_specs = [target_specs[name] for name in dependency_fields]
        source_type = source_specs[0].python_type
        if any(item.python_type is not source_type for item in source_specs):
            raise TypeError(
                f"Parent field {parent_field!r} aliases dependency fields "
                "with incompatible types."
            )
        if (
            declaration.python_type is not None
            and declaration.python_type is not source_type
        ):
            raise TypeError(
                f"Parent field {parent_field!r} declares type "
                f"{declaration.python_type.__name__}, but its dependency "
                f"field type is {source_type.__name__}."
            )
        if any(item.secret for item in source_specs) and not declaration.secret:
            raise ValueError(
                f"Parent field {parent_field!r} cannot weaken secret "
                "metadata from its dependency fields."
            )
        if not declaration.env_key.startswith(prefix):
            raise ValueError(
                f"Parent field {parent_field!r} uses env key "
                f"{declaration.env_key}, which must start with {prefix}."
            )
        fields.append(
            ConfigField(
                name=parent_field,
                env_var=declaration.env_key.removeprefix(prefix),
                python_type=source_type,
                default=declaration.default,
                default_factory=declaration.default_factory,
                packaged_default=declaration.packaged_default,
                title=declaration.title or "",
                explanation_short=declaration.explanation_short,
                explanation_long=declaration.explanation_long,
                secret=declaration.secret,
                editable=declaration.editable,
                required=declaration.inferred_required(),
                choices=declaration.choices,
                restart_required=declaration.restart_required,
            )
        )
    owner = ConfigOwner(
        key=key,
        title=title,
        env_prefix=prefix,
        rc_path=rc_path,
        fields=tuple(fields),
        requires_workspace=requires_workspace,
    )
    validate_config_owner(owner)
    _validate_prefix(
        config_type=config_type,
        config_key=key,
        prefix=prefix,
        fields=declared_fields,
    )
    return owner


def _dependency_runtime_owner(
    *,
    parent_owner: ConfigOwner,
    dependency_owner: ConfigOwner,
    field_targets: Mapping[str, str],
) -> ConfigOwner:
    """Map imported fields and retain safe Python defaults for the rest."""
    dependency_fields = []
    for dependency_spec in dependency_owner.fields:
        parent_field = field_targets.get(dependency_spec.name)
        if parent_field is None:
            dependency_fields.append(
                dataclasses.replace(
                    dependency_spec,
                    env_var=dependency_owner.env_key(dependency_spec.name),
                )
            )
            continue
        dependency_fields.append(
            dataclasses.replace(
                parent_owner.field(parent_field),
                name=dependency_spec.name,
                env_var=parent_owner.env_key(parent_field),
            )
        )
    return ConfigOwner(
        key=parent_owner.key,
        title=parent_owner.title,
        env_prefix="",
        rc_path=parent_owner.rc_path,
        fields=tuple(dependency_fields),
        requires_workspace=parent_owner.requires_workspace,
    )


def _secret_safe_dependency_type(
    config_type: type[ConfigInstanceT],
    runtime_owner: ConfigOwner,
) -> type[ConfigInstanceT]:
    """Add an instance-owner-aware repr when the parent adds secret fields."""
    dataclass_fields = {
        item.name: item for item in fields(cast(Any, config_type))
    }
    newly_secret = any(
        spec.secret and dataclass_fields[spec.name].repr
        for spec in runtime_owner.fields
    )
    if not newly_secret:
        return config_type

    def __repr__(instance: object) -> str:
        """Redact fields marked secret by the instance's parent owner."""
        owner = cast(Config, instance)._config_owner()
        values: list[str] = []
        for item in fields(cast(Any, instance)):
            if (
                not item.repr
                or item.name.startswith("_")
                or item.metadata.get("internal")
            ):
                continue
            try:
                secret = owner.field(item.name).secret
            except KeyError:
                secret = False
            rendered = (
                "<redacted>" if secret else repr(getattr(instance, item.name))
            )
            values.append(f"{item.name}={rendered}")
        return f"{type(instance).__qualname__}({', '.join(values)})"

    return cast(
        type[ConfigInstanceT],
        type(
            f"{config_type.__name__}Imported",
            (config_type,),
            {
                "__module__": config_type.__module__,
                "__slots__": (),
                "__repr__": __repr__,
            },
        ),
    )
