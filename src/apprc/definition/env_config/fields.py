"""Config declaration helpers for EnvConfig-backed app sections."""

from __future__ import annotations

# == Standard Library ========================
import logging
import re
from collections.abc import Callable
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from functools import wraps
from typing import Any, TypeVar, cast, get_type_hints

# == Internal ================================
import apprc.utils as ut
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.env_config._validation import (
    validate_config_owner,
)
from apprc.definition.env_config.sentinels import (
    CONFIG_MISSING,
    ENV_FIELD_METADATA_KEY,
    ENV_FIELD_MISSING,
)

EnvClsT = TypeVar("EnvClsT", bound=type[Any])


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    """Author-facing metadata attached to one ``EnvConfig`` dataclass field.

    :param env_var: Env variable name without the owner prefix. When omitted,
        AppRC derives the key from the Python attribute name.
    :param default: Runtime fallback when no Python value or env value wins.
    :param default_factory: Runtime fallback factory used to build one fresh
        value per config instance.
    :param packaged_default: Packaged defaults dotenv value when intentionally
        different from the runtime fallback.
    :param title: Short display label for docs and terminal UIs.
    :param explanation_short: Compact table-facing description.
    :param explanation_long: Full editor-facing description.
    :param secret: Whether UIs and provenance reprs should redact the value.
    :param editable: Whether config editors should allow direct editing.
    :param required: Whether a value must come from Python or env.
    :param choices: Optional string choices.
    :param python_type: Optional override for the annotation-derived type.
    """

    env_var: str | None = None
    default: Any = CONFIG_MISSING
    default_factory: Callable[[], Any] | object = CONFIG_MISSING
    packaged_default: Any = CONFIG_MISSING
    title: str = ""
    explanation_short: str = ""
    explanation_long: str = ""
    secret: bool = False
    editable: bool = True
    required: bool = False
    choices: tuple[str, ...] = ()
    python_type: type[Any] | None = None

    @property
    def shared_default(self) -> Any:
        """Return ``packaged_default`` through the deprecated 0.19 name."""
        return self.packaged_default


def env_field(
    env_var: str | None = None,
    *,
    default: Any = CONFIG_MISSING,
    default_factory: Callable[[], Any] | object = CONFIG_MISSING,
    packaged_default: Any = CONFIG_MISSING,
    shared_default: Any = CONFIG_MISSING,
    title: str = "",
    explanation_short: str = "",
    explanation_long: str = "",
    secret: bool = False,
    editable: bool = True,
    required: bool = False,
    choices: Iterable[str] = (),
    repr: bool | None = None,
    python_type: type[Any] | None = None,
) -> Any:
    """Declare one env-backed ``EnvConfig`` attribute.

    ``env_field`` stores AppRC metadata in a normal dataclass field. The
    surrounding :func:`env_owner` decorator derives the normalized
    :class:`ConfigField` inventory from that metadata and the attribute type
    annotation.

    :param env_var: Env variable name without the owner prefix. When omitted,
        the Python field name is converted to upper snake case.
    :param default: Runtime fallback when Python and env do not provide a
        value. Omit this for required env-backed settings.
    :param default_factory: Runtime fallback factory used to build one fresh
        value per config instance. Mutually exclusive with ``default``.
    :param packaged_default: Packaged defaults value when intentionally
        different from ``default``.
    :param shared_default: Deprecated alias for ``packaged_default``.
    :param title: Short display label for docs and terminal UIs.
    :param explanation_short: Compact table-facing description.
    :param explanation_long: Full editor-facing description.
    :param secret: Whether display surfaces should redact the value.
    :param editable: Whether config editors should allow direct editing.
    :param required: Whether Python or env must provide a value.
    :param choices: Optional accepted string values.
    :param repr: Whether dataclass ``repr`` should include this value. Defaults
        to hiding secret fields and showing non-secret fields.
    :param python_type: Optional override for the annotation-derived type.
    :return: Dataclass field consumed by ``EnvConfig`` and AppRC tooling.
    """
    if default is not CONFIG_MISSING and default_factory is not CONFIG_MISSING:
        raise ValueError(
            "env_field cannot declare both default and default_factory."
        )
    if (
        packaged_default is not CONFIG_MISSING
        and shared_default is not CONFIG_MISSING
    ):
        raise ValueError(
            "env_field cannot declare both packaged_default and the "
            "deprecated shared_default."
        )
    resolved_packaged_default = (
        shared_default
        if packaged_default is CONFIG_MISSING
        else packaged_default
    )
    spec = EnvFieldSpec(
        env_var=env_var,
        default=default,
        default_factory=default_factory,
        packaged_default=resolved_packaged_default,
        title=title,
        explanation_short=explanation_short,
        explanation_long=explanation_long,
        secret=secret,
        editable=editable,
        required=required,
        choices=tuple(choices),
        python_type=python_type,
    )
    field_kwargs: dict[str, Any] = {
        "repr": (not secret if repr is None else repr),
        "metadata": {ENV_FIELD_METADATA_KEY: spec},
    }
    if default_factory is not CONFIG_MISSING:
        field_kwargs["default_factory"] = cast(
            Callable[[], Any],
            default_factory,
        )
        return field(**field_kwargs)
    dataclass_default = (
        ENV_FIELD_MISSING if default is CONFIG_MISSING else default
    )
    field_kwargs["default"] = dataclass_default
    return field(
        **field_kwargs,
    )


def _default_env_var(field_name: str) -> str:
    """Return the conventional owner-local env key for ``field_name``."""
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", field_name).replace("-", "_")
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


def _field_spec_from_metadata(
    metadata: Mapping[str, Any],
) -> EnvFieldSpec | None:
    """Return the AppRC field spec stored in dataclass metadata."""
    spec = metadata.get(ENV_FIELD_METADATA_KEY)
    if spec is None:
        return None
    if not isinstance(spec, EnvFieldSpec):
        raise TypeError(
            f"{ENV_FIELD_METADATA_KEY!r} metadata must contain EnvFieldSpec, "
            f"got {type(spec).__name__}."
        )
    return spec


def _derive_owner_fields(env_cls: type[Any]) -> tuple[ConfigField, ...]:
    """Derive normalized fields from one decorated ``EnvConfig`` class."""
    type_hints = get_type_hints(env_cls, include_extras=True)
    owner_fields: list[ConfigField] = []
    seen_env_vars: set[str] = set()
    for item in fields(env_cls):
        spec = _field_spec_from_metadata(item.metadata)
        if spec is None:
            continue
        env_var = spec.env_var or _default_env_var(item.name)
        if env_var in seen_env_vars:
            raise ValueError(
                f"{env_cls.__name__} declares duplicate env var {env_var!r}."
            )
        seen_env_vars.add(env_var)
        python_type = spec.python_type or type_hints.get(item.name, Any)
        if python_type is Any:
            raise TypeError(
                f"{env_cls.__name__}.{item.name} must have a type annotation "
                "or env_field(python_type=...)."
            )
        owner_fields.append(
            ConfigField(
                name=item.name,
                env_var=env_var,
                python_type=python_type,
                default=spec.default,
                default_factory=spec.default_factory,
                packaged_default=spec.packaged_default,
                title=spec.title,
                explanation_short=spec.explanation_short,
                explanation_long=spec.explanation_long,
                secret=spec.secret,
                editable=spec.editable,
                required=spec.required
                or (
                    spec.default is CONFIG_MISSING
                    and spec.default_factory is CONFIG_MISSING
                ),
                choices=spec.choices,
            )
        )
    return tuple(owner_fields)


def _log_init_lifecycle(
    label: str = "Runtime Config",
    log_start: bool = True,
    log_done: bool = False,
) -> Callable[[EnvClsT], EnvClsT]:
    """Return a class decorator that logs object initialization.

    AppRC keeps this helper private because logging is no longer a public
    package feature. It preserves the existing config-construction breadcrumbs
    with stdlib logging so host applications can format them however they
    choose.

    :param label: Human-readable subsystem label.
    :param log_start: Whether to emit a pre-initialization message.
    :param log_done: Whether to emit a post-initialization message.
    :return: Class decorator for an ``EnvConfig`` subclass.
    """

    def decorator(cls: EnvClsT) -> EnvClsT:
        original_init = cast(Callable[..., None], cls.__init__)
        if getattr(original_init, "__init_lifecycle_wrapped__", False):
            return cls

        @wraps(original_init)
        def wrapped_init(self: Any, *args: Any, **kwargs: Any) -> None:
            logger = logging.getLogger(cls.__module__)
            name = self.__class__.__name__
            if log_start:
                logger.info(
                    "⚙️🔜 INITIALIZING: %s '%s' ...",
                    label,
                    name,
                    stacklevel=2,
                )
            original_init(self, *args, **kwargs)
            if log_done:
                logger.info(
                    "⚙️✔️  %s '%s' initialized!",
                    label,
                    name,
                    stacklevel=2,
                )

        setattr(wrapped_init, "__init_lifecycle_wrapped__", True)
        setattr(cls, "__init__", wrapped_init)
        return cls

    return decorator


def env_owner(
    *,
    key: str,
    title: str,
    env_prefix: str,
    rc_path: tuple[str, ...],
    slots: bool = True,
    kw_only: bool = False,
    log_lifecycle: bool = True,
    lifecycle_label: str = "EnvConfig",
    log_start: bool = True,
    log_done: bool = False,
) -> Any:
    """Decorate an ``EnvConfig`` class and derive its normalized owner schema.

    The decorated class becomes a dataclass by default. ``ConfigOwner`` remains
    AppRC's internal normalized inventory, but application authors define the
    fields only once on the typed runtime config class. Initialization
    lifecycle logging is enabled by default so app-level config construction is
    visible without host applications importing logging decorators themselves.

    :param key: Stable owner key such as ``"app.runtime_settings"``.
    :param title: Short display label for docs and terminal UIs.
    :param env_prefix: Env key prefix for all owned fields.
    :param rc_path: Runtime config path components from the application root.
    :param slots: Whether to apply slotted dataclass generation.
    :param kw_only: Whether generated dataclass fields are keyword-only.
    :param log_lifecycle: Whether to wrap initialization with AppRC lifecycle
        logging.
    :param lifecycle_label: Human-readable label used by lifecycle logs.
    :param log_start: Whether lifecycle logging emits a start message.
    :param log_done: Whether lifecycle logging emits a completion message.
    :return: Class decorator for an ``EnvConfig`` subclass.
    """

    def _decorate(cls: EnvClsT) -> EnvClsT:
        from apprc.definition.env_config.env import EnvConfig

        if not issubclass(cls, EnvConfig):
            raise TypeError(
                f"{cls.__name__} must inherit EnvConfig before @env_owner "
                "can derive config metadata."
            )
        # > Dataclass subclasses inherit is_dataclass(cls)=True before their
        # > own annotations are processed, so inspect the class dictionary.
        env_cls = (
            cls
            if "__dataclass_fields__" in cls.__dict__
            else dataclass(
                slots=ut.dataclass_slots_preserving_class_identity(
                    cls,
                    requested_slots=slots,
                ),
                kw_only=kw_only,
            )(cls)
        )
        owner = ConfigOwner(
            key=key,
            title=title,
            env_prefix=env_prefix,
            rc_path=rc_path,
            fields=_derive_owner_fields(env_cls),
        )
        validate_config_owner(owner)
        setattr(env_cls, "config_owner", owner)
        if not log_lifecycle:
            return env_cls
        return _log_init_lifecycle(
            label=lifecycle_label,
            log_start=log_start,
            log_done=log_done,
        )(env_cls)

    return _decorate


def config_owner_for(env_cls: type[Any]) -> ConfigOwner:
    """Return the owner schema derived for one ``EnvConfig`` class.

    :param env_cls: Class decorated with :func:`env_owner`.
    :return: Normalized owner inventory used by AppRC internals.
    :raises TypeError: If the class has not been decorated.
    """
    owner = getattr(env_cls, "config_owner", None)
    if isinstance(owner, ConfigOwner):
        return owner
    raise TypeError(f"{env_cls.__name__} is not decorated with @env_owner.")
