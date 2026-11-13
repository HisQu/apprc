"""Visible contracts for opt-in AppRC root help."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from apprc.cli import AppRCRootGroup
from apprc.interfaces.cli import _root_help
from apprc.interfaces.cli.options import (
    AppRootOption,
    EnvFileOverridesOption,
    EnvFilesOption,
    LayoutOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    WorkspaceOption,
)


def _build_app(
    maintenance_commands: tuple[str, ...] = ("doctor", "paths"),
) -> typer.Typer:
    """Build a small host app with AppRC's runtime and maintenance panels."""
    app = typer.Typer(
        cls=AppRCRootGroup,
        help="Host application help text.",
        epilog="Host application epilog.",
    )

    @app.callback()
    def root(
        env_file: EnvFilesOption = None,
        env_override: EnvFileOverridesOption = False,
        skip_layers: SkipDotenvLayersOption = False,
        workspace: WorkspaceOption = None,
        layout: LayoutOption = None,
        app_root: AppRootOption = None,
        log_level: LogLevelOption = None,
        host: bool = typer.Option(False, "--host-option", help="Host option."),
    ) -> None:
        del (
            env_file,
            env_override,
            skip_layers,
            workspace,
            layout,
            app_root,
            log_level,
            host,
        )

    @app.command(
        help="Run the host application.",
        short_help=(
            "Launch the interactive host application with its configured "
            "workspace selection."
        ),
    )
    def serve() -> None:
        pass

    @app.command(
        short_help="Open the interactive AppRC application launcher.",
        rich_help_panel="AppRC: Commands",
    )
    def launch() -> None:
        pass

    maintenance = typer.Typer()
    for command_name in maintenance_commands:

        def command() -> None:
            pass

        maintenance.command(name=command_name)(command)
    app.add_typer(
        maintenance,
        name="app",
        cls=_root_help._AppRCMaintenanceGroup,
        rich_help_panel="AppRC: Commands",
    )

    config = typer.Typer(help="Inspect and update saved configuration.")
    app.add_typer(
        config,
        name="config",
        short_help=(
            "Inspect resolved settings, update saved configuration, or open "
            "the interactive configuration editor."
        ),
        rich_help_panel="AppRC: Commands",
    )
    return app


def test_root_help_interleaves_host_and_apprc_panels() -> None:
    """Root help separates host and AppRC metadata in the required order."""
    result = CliRunner().invoke(_build_app(), ["--help"], color=False)

    assert result.exit_code == 0, result.output
    headings = [
        "Options",
        "Commands",
        "AppRC: Runtime Options",
        "AppRC: Commands",
    ]
    positions = [result.output.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "--host-option" in result.output
    assert "--env-file" in result.output
    assert "-o" in result.output
    assert "-s" in result.output
    assert "--workspace" in result.output
    assert "--layout" in result.output
    assert "--app-root" in result.output
    assert "--log-level" in result.output
    assert "serve" in result.output
    assert "config" in result.output
    assert "app" in result.output
    visible_text = " ".join(
        line.strip(" │") for line in result.output.splitlines()
    )
    visible_text = " ".join(visible_text.split())
    assert (
        "Inspect resolved settings, update saved configuration, or open the "
        "interactive configuration editor." in visible_text
    )
    assert "--install-completion" in result.output
    assert "--show-completion" in result.output
    assert "Host application help text." in result.output
    assert "Host application epilog." in result.output
    assert "\x1b[" not in result.output


def test_root_help_maintenance_summary_uses_available_order_without_truncation() -> (
    None
):
    """The maintenance row lists exactly its registered immediate commands."""
    names = (
        "doctor",
        "paths",
        "repair",
        "uninstall",
        "migrate",
        "data",
        "cache",
        "state",
    )
    result = CliRunner().invoke(_build_app(names), ["--help"], color=False)

    assert result.exit_code == 0, result.output
    summary = f"Inspect and maintain the application ({', '.join(names)})."
    visible_text = " ".join(
        line.strip(" │") for line in result.output.splitlines()
    )
    visible_text = " ".join(visible_text.split())
    assert summary in visible_text
    assert "app doctor" not in result.output
    assert "app cache" not in result.output
    assert (
        "Launch the interactive host application with its configured "
        "workspace selection." in visible_text
    )


def test_root_help_wraps_to_requested_width() -> None:
    """Root panels fit the active Click formatter width at common terminals."""
    for width in (80, 120):
        result = CliRunner().invoke(
            _build_app(
                (
                    "doctor",
                    "paths",
                    "repair",
                    "uninstall",
                    "migrate",
                    "data",
                    "cache",
                    "state",
                )
            ),
            ["--help"],
            terminal_width=width,
            color=False,
        )
        assert result.exit_code == 0, result.output
        assert max(map(len, result.output.splitlines())) <= width


def test_nested_help_uses_normal_typer_rendering() -> None:
    """The root customization does not replace ordinary nested help."""
    result = CliRunner().invoke(_build_app(), ["app", "--help"], color=False)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "doctor" in result.output
    assert "paths" in result.output
    assert "AppRC: Runtime Options" not in result.output


def test_root_help_is_eager_and_renders_only_nonempty_panels() -> None:
    """Eager help exits successfully, omitting empty host command panels."""
    app = typer.Typer(cls=AppRCRootGroup)

    @app.callback()
    def root() -> None:
        pass

    result = CliRunner().invoke(app, ["--help"], color=False)

    assert result.exit_code == 0, result.output
    assert "Options" in result.output
    assert "Commands" not in result.output
    assert "AppRC: Runtime Options" not in result.output
    assert "AppRC: Commands" not in result.output
    assert "\x1b[" not in result.output


def test_non_opted_in_typer_keeps_its_normal_help() -> None:
    """Applications without the explicit root class keep Typer help."""
    app = typer.Typer()

    @app.command()
    def serve() -> None:
        pass

    result = CliRunner().invoke(app, ["--help"], color=False)

    assert result.exit_code == 0, result.output
    assert "serve" in result.output
    assert "AppRC: Runtime Options" not in result.output
    assert "AppRC: Commands" not in result.output
