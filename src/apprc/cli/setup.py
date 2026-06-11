"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.doctor import print_config_doctor
from apprc.config.diagnostics import build_config_doctor_payload
from apprc.config.kit import AppConfigKit
import apprc.config.setup.flow as setup_flow
import apprc.config.setup.text as setup_text
from apprc.config.storage.registry import StorageRegistry
from apprc.config.tui.setup import ConfigSetupApp


def run_config_setup(
    kit: AppConfigKit,
    *,
    assume_yes: bool = False,
    apprc_dir: Path | None = None,
    storage_root: Path | None = None,
    storage_name: str | None = None,
    existing_action: setup_flow.ExistingSetupAction | None = None,
) -> None:
    """Run the Textual setup wizard or a non-interactive setup command.

    :param kit: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to run without opening the Textual wizard.
    :param apprc_dir: Optional AppRC directory for non-interactive setup.
    :param storage_root: Optional default storage root for setup.
    :param storage_name: Optional default storage selector for setup.
    :param existing_action: Optional action for an existing registry.
    :raises typer.Exit: If the user cancels or setup diagnostics fail.
    :raises typer.BadParameter: If setup inputs are invalid.
    """
    has_setup_options = any(
        option is not None
        for option in (
            apprc_dir,
            storage_root,
            storage_name,
            existing_action,
        )
    )
    if has_setup_options and not assume_yes:
        raise typer.BadParameter(
            "Setup options run non-interactively and require --yes.",
            param_hint="--yes",
        )

    if not assume_yes:
        result = ConfigSetupApp(kit=kit).run()
        if result is None:
            raise typer.Exit(code=1)
        _raise_if_doctor_failed(kit, apprc_toml_path=result.registry.path)
        return

    try:
        setup_result = setup_flow.prepare_setup_registry(
            kit,
            apprc_dir=apprc_dir,
            existing_action=existing_action,
            replace_existing_file=True,
        )
        registry = setup_flow.ensure_default_storage(
            kit,
            setup_result.registry,
            storage_name=storage_name,
            storage_root=storage_root,
            allow_non_empty_storage=True,
        )
    except setup_flow.ConfigSetupError as exc:
        _raise_setup_error(exc)
    _print_setup_finish(kit, registry)


def _print_setup_finish(
    kit: AppConfigKit,
    registry: StorageRegistry,
) -> None:
    """Print diagnostics and next commands after non-interactive setup.

    :param kit: Application config facade.
    :param registry: Registry selected by setup.
    :raises typer.Exit: If doctor reports that setup is incomplete.
    """
    typer.echo(f"{kit.spec.display_name} setup complete")
    typer.echo(f"AppRC TOML: {registry.path}")
    typer.echo(f"default_storage: {registry.default_storage or '<none>'}")
    typer.echo("")
    payload = build_config_doctor_payload(
        kit,
        storage_name=registry.default_storage,
        apprc_toml_path=registry.path,
    )
    print_config_doctor(kit, payload)
    typer.echo("")
    typer.echo("Next steps:")
    for line in setup_text.next_steps_text(kit, registry).splitlines():
        typer.echo(f"  {line}" if line else "")
    if not payload["ok"]:
        raise typer.Exit(code=1)


def _raise_if_doctor_failed(
    kit: AppConfigKit,
    *,
    apprc_toml_path: Path,
) -> None:
    """Exit when the setup wizard completed but diagnostics still fail.

    :param kit: Application config facade.
    :param apprc_toml_path: AppRC TOML path setup selected.
    :raises typer.Exit: If doctor reports that setup is incomplete.
    """
    payload = build_config_doctor_payload(
        kit,
        storage_name=kit.load_registry(path=apprc_toml_path).default_storage,
        apprc_toml_path=apprc_toml_path,
    )
    if not payload["ok"]:
        raise typer.Exit(code=1)


def _raise_setup_error(exc: setup_flow.ConfigSetupError) -> None:
    """Convert setup workflow errors to Typer's CLI errors.

    :param exc: Setup-layer error with optional CLI context.
    :raises typer.Exit: For setup refusals that should keep exit code ``1``.
    :raises typer.BadParameter: For invalid command input.
    """
    exit_code = getattr(exc, "exit_code", None)
    if exit_code is not None:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exit_code)
    raise typer.BadParameter(str(exc), param_hint=exc.param_hint) from exc
