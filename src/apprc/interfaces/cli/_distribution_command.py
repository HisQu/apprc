"""Mount distribution authoring for explicitly opted-in editable checkouts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from apprc.interfaces.cli._distribution_authoring import (
    CheckoutAuthoring,
    _build,
    _check,
    _revision,
    _targets,
)
from apprc.interfaces.cli._typer_utils import click

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def distribution_group() -> None:
    """Build and verify native setups from the development checkout."""


def build_authoring_group(
    authoring: CheckoutAuthoring,
    apprc: AppRC,
    maintenance_group: str,
    *,
    installation_management: bool,
) -> typer.Typer:
    """Create shared build and check commands without importing the backend."""
    app = typer.Typer(no_args_is_help=True)
    app.callback()(distribution_group)

    @app.command()
    def build(
        ctx: typer.Context,
        target_current: Annotated[
            bool,
            typer.Option(
                "--target-current", "-t", help="Build only for this platform."
            ),
        ] = False,
        olis_repo: Annotated[
            str | None,
            typer.Option(
                "--olis-repo",
                "-o",
                metavar="OWNER/REPO",
                help="GitHub release source for the scripts. Overrides RELEASE_REPO_OLIS.",
            ),
        ] = None,
    ) -> None:
        """Build verified setup executables from the committed checkout."""
        from apprc.distribution import (
            MissingNativeArtifact,
            StaleNativeArtifact,
        )
        from apprc.interfaces._terminal_console import cli_line

        backend = authoring.backend()
        try:
            targets = _targets(current=target_current)
            revision = _revision(authoring.root)
            try:
                _check(
                    backend, authoring.root, revision=revision, targets=targets
                )
            except (MissingNativeArtifact, StaleNativeArtifact):
                pass
            _build(
                backend, authoring.root, revision, targets, olis_repo=olis_repo
            )
            for path in _check(
                backend, authoring.root, revision=revision, targets=targets
            ):
                cli_line(ctx, "Built", path=path)
            if not (
                os.environ.get("RELEASE_REPO_OLIS")
                if olis_repo is None
                else olis_repo
            ):
                cli_line(
                    ctx,
                    "Native installers built. OLIS generation skipped. "
                    "Set RELEASE_REPO_OLIS or pass --olis-repo OWNER/REPO.",
                )
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.command()
    def check(
        ctx: typer.Context,
        target_current: Annotated[
            bool,
            typer.Option(
                "--target-current",
                "-t",
                help="Require a current setup only for this platform.",
            ),
        ] = False,
    ) -> None:
        """Check setup integrity and freshness without running the artifacts."""
        from apprc.interfaces._terminal_console import cli_line

        backend = authoring.backend()
        try:
            for path in _check(
                backend,
                authoring.root,
                revision=_revision(authoring.root),
                targets=_targets(current=target_current),
            ):
                cli_line(ctx, "Verified", path=path)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise click.ClickException(str(exc)) from exc

    def test(
        ctx: typer.Context,
        editable: Annotated[
            bool,
            typer.Option(
                "--editable",
                "-e",
                help="Test editable registration (the default).",
            ),
        ] = False,
        managed: Annotated[
            bool,
            typer.Option(
                "--managed", "-m", help="Test a managed native installation."
            ),
        ] = False,
        update_from: Annotated[
            Path | None,
            typer.Option(
                "--update-from",
                "-u",
                help="Install this older native setup before testing the update.",
                exists=True,
                dir_okay=False,
            ),
        ] = None,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Run unattended. Refuses a pre-existing installation.",
            ),
        ] = False,
    ) -> None:
        """Guide installation, verification, and uninstallation on this machine."""
        if editable and (managed or update_from is not None):
            raise typer.BadParameter(
                "--editable cannot be combined with --managed or --update-from."
            )
        try:
            from apprc.interfaces.cli._distribution_test import (
                run_distribution_test,
            )
        except ImportError as exc:
            raise click.ClickException(
                f"Cannot load guided distribution testing: {exc}.\n"
                "Set up this checkout with `uv sync --locked --all-groups`."
            ) from exc

        command = apprc.schema.command_name
        assert command is not None
        run_distribution_test(
            ctx,
            authoring,
            apprc,
            maintenance_group,
            command,
            managed=managed or update_from is not None,
            update_from=update_from,
            assume_yes=assume_yes,
        )

    if installation_management:
        app.command()(test)
    return app
