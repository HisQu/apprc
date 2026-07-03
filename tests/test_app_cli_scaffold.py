import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc._cli_app import app
from apprc.scaffold import ConfigScaffoldRequest, scaffold_config_package


def test_scaffold_config_package_generates_importable_standard_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated packages should teach the standard bundle layout."""
    source_root = tmp_path / "src"
    result = scaffold_config_package(
        ConfigScaffoldRequest(
            package="demo_app",
            mode="storage-only",
            app_name="demo-app",
            display_name="Demo App",
            storage_env_key="DEMO_APP_STORAGE",
            target=source_root,
        )
    )

    expected_files = {
        source_root / "demo_app" / "config" / "__init__.py",
        source_root / "demo_app" / "config" / "app.py",
        source_root / "demo_app" / "config" / "sections" / "__init__.py",
        source_root / "demo_app" / "config" / "sections" / "app.py",
        source_root / "demo_app" / "config" / "bundle.py",
        source_root / "demo_app" / "config" / "catalog.py",
    }
    assert set(result.written_files) == expected_files
    assert result.config_package_dir == source_root / "demo_app" / "config"

    monkeypatch.syspath_prepend(str(source_root))
    monkeypatch.setenv("DEMO_APP_STORAGE", str(tmp_path / "storage"))
    config_module = importlib.import_module("demo_app.config")

    assert config_module.MyRC.kit.spec.storage_required() is True
    assert config_module.CONFIG_SPEC.owners[0].key == "app"
    assert "app" in config_module.SECTION_BY_KEY
    generated_bundle = config_module.DemoAppConfig()
    assert generated_bundle.app.profile == "default"


def test_scaffold_config_package_refuses_unrelated_storage_prefix(
    tmp_path: Path,
) -> None:
    """Generated storage selector fields must satisfy AppRC prefix checks."""
    with pytest.raises(ValueError, match="must start with --env-prefix"):
        scaffold_config_package(
            ConfigScaffoldRequest(
                package="demo_app",
                mode="storage-only",
                app_name="demo-app",
                storage_env_key="OTHER_STORAGE",
                env_prefix="DEMO_APP_",
                target=tmp_path / "src",
            )
        )


def test_scaffold_config_package_escapes_generated_python_literals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffolded modules should import when labels need string escaping."""
    source_root = tmp_path / "src"
    scaffold_config_package(
        ConfigScaffoldRequest(
            package="quoted_demo",
            mode="env-only",
            app_name="quoted-demo",
            display_name="Demo's App",
            target=source_root,
        )
    )

    monkeypatch.syspath_prepend(str(source_root))
    config_module = importlib.import_module("quoted_demo.config")

    assert config_module.MyRC.kit.spec.display_name == "Demo's App"


def test_scaffold_config_package_refuses_overwrite_without_force(
    tmp_path: Path,
) -> None:
    """Scaffold reruns should be explicit about replacing files."""
    request = ConfigScaffoldRequest(
        package="demo_app",
        mode="env-only",
        app_name="demo-app",
        target=tmp_path / "src",
    )

    scaffold_config_package(request)

    with pytest.raises(FileExistsError, match="already exist"):
        scaffold_config_package(request)

    forced = scaffold_config_package(
        ConfigScaffoldRequest(
            package="demo_app",
            mode="env-only",
            app_name="demo-app",
            target=tmp_path / "src",
            force=True,
        )
    )
    assert forced.config_package_dir == tmp_path / "src" / "demo_app" / "config"


def test_app_cli_scaffold_config_command_writes_standard_layout(
    tmp_path: Path,
) -> None:
    """The public ``apprc scaffold config`` command should call the writer."""
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "scaffold",
            "config",
            "--package",
            "cli_demo",
            "--mode",
            "env-only",
            "--app-name",
            "cli-demo",
            "--display-name",
            "CLI Demo",
            "--target",
            str(tmp_path / "src"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Created AppRC config package" in result.output
    assert (tmp_path / "src" / "cli_demo" / "config" / "bundle.py").exists()


def test_app_cli_help_exposes_scaffold_group() -> None:
    """The first-party CLI app should expose scaffold commands."""
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "scaffold" in result.output
