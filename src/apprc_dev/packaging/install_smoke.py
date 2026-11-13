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
    """Exercise committed project snapshot creation from an installed SDK.

    :return: None.
    """
    import os
    import subprocess
    from zipfile import ZipFile

    from apprc.distribution import build_project_snapshot, read_distribution_spec
    from apprc.distribution.runtime.acquisition import materialize_project_snapshot

    with tempfile.TemporaryDirectory(prefix="apprc-installed-snapshot-") as temporary:
        root = Path(temporary)
        (root / "src" / "fixture").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "snapshot-fixture"\nversion = "1.0.0"\n'
            'requires-python = ">=3.12"\n'
            '[project.scripts]\nsnapshot-fixture = "fixture:main"\n'
            '[tool.apprc.distribution]\napp-id = "snapshot-fixture"\n'
            'import-package = "fixture"\ncommand-name = "snapshot-fixture"\n',
            encoding="utf-8",
        )
        (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (root / "src" / "fixture" / "__init__.py").write_text(
            'def main() -> None:\n    print("fixture")\n', encoding="utf-8"
        )
        environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "AppRC smoke",
            "GIT_AUTHOR_EMAIL": "smoke@example.invalid",
            "GIT_COMMITTER_NAME": "AppRC smoke",
            "GIT_COMMITTER_EMAIL": "smoke@example.invalid",
        }
        subprocess.run(["git", "init", "-q", str(root)], env=environment, check=True)
        subprocess.run(
            ["git", "-C", str(root), "add", "pyproject.toml", "uv.lock", "src"],
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
            env=environment,
            check=True,
        )
        spec = read_distribution_spec(root)
        prepared = build_project_snapshot(
            spec,
            revision="HEAD",
            destination=root / "project.zip",
        )
        materialized = root / "materialized"
        materialize_project_snapshot(prepared.archive, materialized, prepared.source)
        with ZipFile(prepared.archive) as package:
            assert "pyproject.toml" in package.namelist()
            assert "uv.lock" in package.namelist()
        assert (materialized / "uv.lock").read_text(encoding="utf-8") == "version = 1\n"
    print("apprc installed project snapshot passed")

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
