"""Verify core or terminal installation in an otherwise fresh pip environment."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from importlib import metadata
from pathlib import Path


def verify_install(*, core_only: bool, gui: bool = False) -> None:
    """Exercise real construction and management under the selected dependency set.

    :param core_only: Whether terminal libraries and entrypoints must be absent.
    :param gui: Whether the separate Gradio editor distribution must import.
    """
    import apprc

    assert isinstance(apprc.ConfigBase, type)
    assert callable(apprc.field)
    terminal_modules = ("typer", "rich", "prompt_toolkit", "textual")
    assert not any(name in sys.modules for name in terminal_modules)
    assert "jinja2" not in sys.modules
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
            paths=apprc.Paths(config=True),
            user_dotenv=apprc.UserDotenv(),
            layout=apprc.Layout.single_root(Path(directory)),
        )

        @app.config("settings", prefix="INSTALL_")
        class Settings(apprc.Config):
            count: int = apprc.field("INSTALL_COUNT", default=2)

        manager = app.manage(
            environment={
                "HOME": str(Path(directory) / "home"),
                "USERPROFILE": str(Path(directory) / "home"),
                "LOCALAPPDATA": str(Path(directory) / "native"),
                "XDG_DATA_HOME": str(Path(directory) / "native"),
            }
        )
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
        from typer.testing import CliRunner

        from apprc._cli_app import app as terminal_app

        assert CliRunner().invoke(terminal_app, ["--help"]).exit_code == 0
        assert apprc.tui.ConfigEditorApp is not None
    if gui:
        from apprc_gui import ConfigEditor

        assert metadata.distribution("apprc-gui").version == core.version
        assert isinstance(ConfigEditor, type)
    print(
        "apprc core install passed"
        if core_only
        else "apprc terminal install passed"
    )


def verify_distribution_install() -> None:
    """Generate actual artifacts using only installed package resources.

    The payload deliberately fails if imported: author generation must serialize
    repository-owned composition, not execute it or resolve business settings.
    """
    from pathlib import PurePosixPath

    from apprc.distribution import (
        DistributionSpec,
        PayloadTree,
        generate_artifacts,
        read_project_metadata,
        write_artifacts,
    )

    with tempfile.TemporaryDirectory(
        prefix="apprc-installed-generation-"
    ) as temporary:
        root = Path(temporary)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "installed-generation-fixture"\nversion = "1.0.0"\n'
            '[project.scripts]\ninstalled-fixture = "not_imported:main"\n',
            encoding="utf-8",
        )
        payload_root = root / "payload"
        package = payload_root / "app_lifecycle"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            '"""Explicit author composition."""\n', encoding="utf-8"
        )
        for name in ("install.py", "uninstall.py"):
            (package / name).write_text(
                'raise RuntimeError("Author payload must not execute during artifact generation.")\n',
                encoding="utf-8",
            )
        payload = PayloadTree(
            payload_root,
            tuple(
                PurePosixPath("app_lifecycle") / name
                for name in (
                    "__init__.py",
                    "install.py",
                    "uninstall.py",
                )
            ),
        )
        artifacts = generate_artifacts(
            DistributionSpec(read_project_metadata(root)), payload
        )
        write_artifacts(artifacts)
        write_artifacts(artifacts, check=True)
        for filename in (
            "app-install.sh",
            "app-install.cmd",
            "app-launch.sh",
            "app-launch.cmd",
            "app-uninstall.sh",
            "app-uninstall.cmd",
        ):
            assert (root / filename).is_file()
    print("apprc installed distribution resources passed")


def main() -> None:
    """Select and run one installation check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--distribution", action="store_true")
    args = parser.parse_args()
    verify_install(core_only=args.core_only, gui=args.gui)
    if args.distribution:
        verify_distribution_install()


if __name__ == "__main__":
    main()
