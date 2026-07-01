"""Selector context and state resolution for generated config commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command.state import DefaultConfigCliState
from apprc.interfaces.cli.context import apprc_context_from
from apprc.interfaces.cli._typer_utils import state_from
from apprc.runtime._dotenv_layers import (
    ExplicitEnvFileError,
    read_explicit_env_files,
)
from apprc.runtime._process_env import selection_env


@dataclass(frozen=True, slots=True)
class ConfigSelectorContext:
    """Host CLI explicit env values used only for selector resolution."""

    explicit_values: Mapping[str, str]
    env_file_overrides_os_environ: bool
    proc_env: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ResolvedConfigState:
    """Config state plus whether host hooks may inspect it.

    :param state: State object used by generated config logic.
    :param app_owned: Whether ``state`` came from the host application's
        runtime bootstrap path.
    """

    state: Any
    app_owned: bool


@dataclass(frozen=True, slots=True)
class ConfigStateResolver:
    """Resolve host-owned state and context-derived generic state.

    :param state_type: Application host CLI state type expected on ``ctx.obj``.
    """

    state_type: type[Any]

    def state(self, ctx: typer.Context) -> Any:
        """Return the application host state stored by the parent CLI."""
        return state_from(ctx, self.state_type)

    def context_state(self, ctx: typer.Context) -> DefaultConfigCliState | None:
        """Return AppRC context as generic config state when available."""
        context = apprc_context_from(ctx)
        if context is None:
            return None
        return DefaultConfigCliState.from_context(context)

    def resolved_config_state(
        self,
        ctx: typer.Context,
    ) -> ResolvedConfigState | None:
        """Return state plus whether app-owned hooks may inspect it."""
        context = apprc_context_from(ctx)
        if context is not None and context.skipped_runtime_bootstrap:
            context_state = self.context_state(ctx)
            if context_state is None:
                return None
            return ResolvedConfigState(context_state, app_owned=False)
        if isinstance(ctx.obj, self.state_type):
            return ResolvedConfigState(ctx.obj, app_owned=True)
        if context is not None:
            raise RuntimeError(
                "CLI state is not initialized. Runtime config commands require "
                f"{self.state_type.__name__} on ctx.obj when runtime bootstrap "
                "was not skipped."
            )
        context_state = self.context_state(ctx)
        if context_state is None:
            return None
        return ResolvedConfigState(context_state, app_owned=False)

    def runtime_payload_state(
        self,
        resolved_state: ResolvedConfigState | None,
    ) -> Any | None:
        """Return state that is valid for app-owned runtime payload hooks."""
        if resolved_state is None or not resolved_state.app_owned:
            return None
        return resolved_state.state


@dataclass(frozen=True, slots=True)
class SelectorContextReader:
    """Read host-level selector options from Typer context metadata."""

    def host_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        context = apprc_context_from(ctx)
        if context is not None:
            option_values = {
                "env_files": context.options.env_files,
                "env_file_overrides_os_environ": (
                    context.options.env_file_overrides_os_environ
                ),
                "load_dotenv_layers": context.options.load_dotenv_layers,
                "log_level": context.options.log_level,
                "skip_dotenv_layers": (not context.options.load_dotenv_layers),
                "storage": context.options.storage,
            }
            if name in option_values:
                return option_values[name]
        current = ctx.parent
        while current is not None:
            if name in current.params:
                return current.params.get(name)
            current = current.parent
        return None

    def cli_selector_context(
        self,
        ctx: typer.Context,
    ) -> ConfigSelectorContext:
        """Return host explicit env-file values for selector-only reads."""
        env_files = _host_env_files(self.host_context_param(ctx, "env_files"))
        overrides = bool(
            self.host_context_param(ctx, "env_file_overrides_os_environ")
        )
        try:
            _, _, explicit_values = read_explicit_env_files(env_files)
        except FileNotFoundError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="--env-file",
            ) from exc
        except ExplicitEnvFileError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="--env-file",
            ) from exc
        return _selector_context(
            explicit_values=explicit_values,
            env_file_overrides_os_environ=overrides,
        )


def _host_env_files(raw_value: object | None) -> tuple[Path, ...]:
    """Return host-level ``--env-file`` option values as paths."""
    if raw_value is None:
        return ()
    if isinstance(raw_value, Path):
        return (raw_value,)
    if isinstance(raw_value, str):
        return (Path(raw_value),)
    if isinstance(raw_value, list | tuple):
        values = cast(list[str | Path] | tuple[str | Path, ...], raw_value)
        return tuple(Path(value) for value in values)
    return ()


def _selector_context(
    *,
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> ConfigSelectorContext:
    """Return selector-only context for explicit env-file values."""
    copied_values = dict(explicit_values)
    return ConfigSelectorContext(
        explicit_values=copied_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        proc_env=selection_env(
            original_env=os.environ,
            explicit_values=copied_values,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        ),
    )


def _empty_selector_context() -> ConfigSelectorContext:
    """Return a selector context with no explicit env-file values."""
    return _selector_context(
        explicit_values={},
        env_file_overrides_os_environ=False,
    )
