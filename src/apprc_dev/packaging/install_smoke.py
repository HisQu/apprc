"""Verify core or terminal installation in an otherwise fresh pip environment."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import importlib.util
from pathlib import Path
import sys
import tempfile


def verify_install(*, core_only: bool, gui: bool = False) -> None:
    """Exercise real construction and management under the selected dependency set.

    :param core_only: Whether terminal libraries and entrypoints must be absent.
    :param gui: Whether the separate native view distribution must import.
    """
    import apprc

    assert isinstance(apprc.ConfigBase, type)
    assert callable(apprc.field)
    terminal_modules = ("typer", "rich", "prompt_toolkit", "textual")
    assert not any(name in sys.modules for name in terminal_modules)
    assert all(
        (importlib.util.find_spec(name) is None) == core_only
        for name in terminal_modules
    )
    core = metadata.distribution("apprc-core")
    assert not core.entry_points
    with tempfile.TemporaryDirectory() as directory:
        app = apprc.AppRC(
            app_id="install_test",
            display_name="Install test",
            user_dotenv=apprc.UserDotenv(),
            apprc_dir=Path(directory),
        )

        @app.config("settings", prefix="INSTALL_")
        class Settings(apprc.Config):
            count: int = apprc.field("INSTALL_COUNT", default=2)

        manager = app.manage(environment={})
        assert manager.inspect().ready
        manager.setup()
        manager.apply_edit(
            manager.plan_update("settings.count", "7", scope="user")
        )
        assert manager.resolve().build(Settings).count == 7
    if core_only:
        assert not any(
            ep.name == "apprc"
            for ep in metadata.entry_points(group="console_scripts")
        )
    else:
        wrapper = metadata.distribution("apprc")
        assert wrapper.version == core.version
        assert any(ep.name == "apprc" for ep in wrapper.entry_points)
        assert not any(
            str(path).startswith("apprc/") for path in wrapper.files or ()
        )
        from apprc._cli_app import app as terminal_app
        from typer.testing import CliRunner

        assert CliRunner().invoke(terminal_app, ["--help"]).exit_code == 0
        assert apprc.tui.ConfigEditorApp is not None
    if gui:
        from apprc_gui import ConfigView

        assert metadata.distribution("apprc-gui").version == core.version
        assert isinstance(ConfigView, type)
    print(
        "apprc core install passed"
        if core_only
        else "apprc terminal install passed"
    )


def main() -> None:
    """Select and run one installation check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    verify_install(core_only=args.core_only, gui=args.gui)


if __name__ == "__main__":
    main()
