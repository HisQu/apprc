"""Public AppRC field declarations."""

# == Standard Library ========================
from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Final, cast

# == Internal ================================
from apprc.definition.env_config.sentinels import (
    CONFIG_MISSING,
    ENV_FIELD_MISSING,
)

PUBLIC_FIELD_METADATA_KEY: Final = "apprc.public.field"


@dataclass(frozen=True, slots=True)
class PublicFieldSpec:
    """Public metadata for one env-backed config attribute.

    App authors write full environment variable names through
    :func:`apprc.field`. The public registration decorator validates those
    names against the config prefix and translates them into AppRC's internal
    owner-local field metadata.

    :param env_key: Full environment variable name shown to users.
    :param default: Runtime fallback when no Python or env value exists.
    :param default_factory: Runtime fallback factory for fresh instance values.
    :param packaged_default: Value documented in ``apprc.defaults.env`` when a
        required field has a shipped value or the shipped value differs from
        the Python fallback.
    :param required: Explicit requiredness override, or ``None`` for inferred
        dataclass-style requiredness.
    :param title: Short display label for docs and terminal UIs.
    :param description: Human-readable field explanation.
    :param explanation_short: Compact table-facing explanation.
    :param explanation_long: Full editor-facing explanation.
    :param editable: Whether config editors should allow direct editing.
    :param secret: Whether display surfaces should redact the value.
    :param choices: Optional accepted string values.
    :param python_type: Optional override for the annotation-derived type.
    """

    env_key: str
    default: Any = CONFIG_MISSING
    default_factory: Callable[[], Any] | object = CONFIG_MISSING
    packaged_default: Any = CONFIG_MISSING
    required: bool | None = None
    title: str | None = None
    description: str | None = None
    explanation_short: str = ""
    explanation_long: str = ""
    editable: bool = True
    secret: bool = False
    choices: tuple[str, ...] = ()
    python_type: type[Any] | None = None

    @property
    def shared_default(self) -> Any:
        """Return ``packaged_default`` through the deprecated 0.19 name."""
        return self.packaged_default

    def inferred_required(self) -> bool:
        """Return requiredness after applying dataclass-style defaults."""
        if self.required is not None:
            return self.required
        return (
            self.default is CONFIG_MISSING
            and self.default_factory is CONFIG_MISSING
        )


def field(
    env: str,
    *,
    default: object = CONFIG_MISSING,
    default_factory: Callable[[], object] | object = CONFIG_MISSING,
    required: bool | None = None,
    title: str | None = None,
    description: str | None = None,
    packaged_default: object = CONFIG_MISSING,
    editable: bool = True,
    secret: bool = False,
    choices: tuple[str, ...] | list[str] | None = None,
    shared_default: object = CONFIG_MISSING,
    python_type: type[Any] | None = None,
    explanation_short: str | None = None,
    explanation_long: str | None = None,
) -> Any:
    """Declare one env-backed AppRC config field.

    The ``env`` argument is always the full environment variable name. AppRC
    never derives names from Python attributes and never treats this value as a
    suffix; the enclosing ``@MyRC.config(..., prefix=...)`` decorator validates
    that the full name starts with the declared prefix.

    :param env: Full environment variable name.
    :param default: Runtime fallback when no Python or env value exists.
    :param default_factory: Runtime fallback factory for fresh instance values.
    :param required: Explicit requiredness override. When omitted, fields
        without defaults are required and fields with defaults are optional.
        ``True`` cannot be combined with ``default`` or ``default_factory``.
    :param title: Short display label for docs and terminal UIs.
    :param description: Human-readable field explanation.
    :param packaged_default: Value documented in ``apprc.defaults.env`` when a
        required field has a shipped value or the shipped value intentionally
        differs from the Python fallback.
    :param editable: Whether config editors should allow direct editing.
    :param secret: Whether display surfaces should redact the value. This does
        not encrypt values, change storage, or imply requiredness.
    :param choices: Optional accepted string values.
    :param shared_default: Deprecated name for ``packaged_default``.
    :param python_type: Type to use when the Python attribute cannot carry a
        usable annotation.
    :param explanation_short: Compact table-facing explanation. Defaults to
        ``description``.
    :param explanation_long: Full editor-facing explanation. Defaults to
        ``description`` and then ``explanation_short``.
    :return: Dataclass field consumed by ``@MyRC.config(...)``.
    :raises TypeError: If ``env`` is not a non-empty string or an unsupported
        keyword argument is passed.
    :raises ValueError: If conflicting defaults, required Python fallbacks, or
        unsupported optional missing semantics are requested.
    """
    if not isinstance(env, str) or not env:
        raise TypeError("rc.field(...) requires a non-empty full env key.")
    if default is not CONFIG_MISSING and default_factory is not CONFIG_MISSING:
        raise ValueError(
            "rc.field(...) cannot declare both default and default_factory."
        )
    if required is True and (
        default is not CONFIG_MISSING or default_factory is not CONFIG_MISSING
    ):
        raise ValueError(
            "rc.field(..., required=True) cannot declare a Python default "
            "or default_factory. Use packaged_default to describe a value "
            "shipped in apprc.defaults.env."
        )
    if (
        required is False
        and default is CONFIG_MISSING
        and default_factory is CONFIG_MISSING
    ):
        raise ValueError(
            "rc.field(..., required=False) requires default or "
            "default_factory because missing optional env values cannot be "
            "represented safely."
        )

    if (
        packaged_default is not CONFIG_MISSING
        and shared_default is not CONFIG_MISSING
    ):
        raise ValueError(
            "rc.field(...) cannot declare both packaged_default and the "
            "deprecated shared_default."
        )
    resolved_packaged_default = (
        shared_default
        if packaged_default is CONFIG_MISSING
        else packaged_default
    )
    resolved_explanation_short = (
        explanation_short
        if explanation_short is not None
        else description or ""
    )
    resolved_explanation_long = (
        explanation_long
        if explanation_long is not None
        else description or resolved_explanation_short
    )
    spec = PublicFieldSpec(
        env_key=env,
        default=default,
        default_factory=default_factory,
        packaged_default=resolved_packaged_default,
        required=required,
        title=title,
        description=description,
        explanation_short=resolved_explanation_short,
        explanation_long=resolved_explanation_long,
        editable=editable,
        secret=secret,
        choices=tuple(choices or ()),
        python_type=python_type,
    )
    field_kwargs: dict[str, Any] = {
        "repr": not secret,
        "metadata": {PUBLIC_FIELD_METADATA_KEY: spec},
    }
    if default_factory is not CONFIG_MISSING:
        field_kwargs["default_factory"] = cast(
            Callable[[], object],
            default_factory,
        )
        return dataclass_field(**field_kwargs)
    field_kwargs["default"] = (
        ENV_FIELD_MISSING if default is CONFIG_MISSING else default
    )
    return dataclass_field(**field_kwargs)
