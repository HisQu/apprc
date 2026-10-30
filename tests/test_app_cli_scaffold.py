import importlib
import runpy
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import apprc as rc
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
            app_id="demo-app",
            target=source_root,
            workspaces=True,
            display_name="Demo App",
            workspace_selector_env_key="DEMO_APP_WORKSPACE",
        )
    )

    expected_files = {
        source_root / "demo_app" / "config" / "__init__.py",
        source_root / "demo_app" / "config" / "app.py",
        source_root / "demo_app" / "config" / "sections" / "__init__.py",
        source_root / "demo_app" / "config" / "sections" / "app.py",
        source_root / "demo_app" / "config" / "bundle.py",
    }
    assert set(result.written_files) == expected_files
    assert result.config_package_dir == source_root / "demo_app" / "config"

    monkeypatch.syspath_prepend(str(source_root))
    monkeypatch.setenv("DEMO_APP_WORKSPACE", str(tmp_path / "workspace"))
    config_module = importlib.import_module("demo_app.config.app")
    bundle_module = importlib.import_module("demo_app.config.bundle")

    assert config_module.MyRC.schema.uses_workspaces() is True
    assert config_module.MyRC.schema.uses_user_dotenv() is False
    assert config_module.MyRC.schema.owners[0].key == "app"
    config_module.MyRC.workspaces().register_workspace(
        "default", tmp_path / "workspace"
    )
    generated_bundle = config_module.MyRC.resolve().build(
        bundle_module.DemoAppConfig
    )
    assert generated_bundle.app.profile == "default"


def test_scaffold_config_package_keeps_leaf_imports_lightweight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf section imports should not load unrelated config modules."""
    source_root = tmp_path / "src"
    scaffold_config_package(
        ConfigScaffoldRequest(
            package="leaf_demo",
            app_id="leaf-demo",
            target=source_root,
        )
    )

    monkeypatch.syspath_prepend(str(source_root))
    importlib.import_module("leaf_demo.config.sections")

    assert "leaf_demo.config.app" not in sys.modules
    assert "leaf_demo.config.sections.app" not in sys.modules
    assert "leaf_demo.config.bundle" not in sys.modules
    assert "leaf_demo.config.catalog" not in sys.modules

    section_cls = importlib.import_module(
        "leaf_demo.config.sections.app"
    ).AppSection

    assert section_cls.__name__ == "AppSection"
    assert "leaf_demo.config.app" in sys.modules
    assert "leaf_demo.config.sections.app" in sys.modules
    assert "leaf_demo.config.bundle" not in sys.modules
    assert "leaf_demo.config.catalog" not in sys.modules

    config_pkg = importlib.import_module("leaf_demo.config.app")
    assert config_pkg.MyRC.schema.app_id == "leaf-demo"
    assert "leaf_demo.config.bundle" not in sys.modules
    assert "leaf_demo.config.catalog" not in sys.modules

    bundle = importlib.import_module("leaf_demo.config.bundle").LeafDemoConfig
    assert (
        config_pkg.MyRC.resolve(environment={}).build(bundle).app.profile
        == "default"
    )
    assert "leaf_demo.config.bundle" in sys.modules


def test_scaffold_config_package_refuses_unrelated_workspace_prefix(
    tmp_path: Path,
) -> None:
    """Workspace selector overrides must satisfy AppRC prefix checks."""
    with pytest.raises(ValueError, match="must start with --env-prefix"):
        scaffold_config_package(
            ConfigScaffoldRequest(
                package="demo_app",
                app_id="demo-app",
                workspaces=True,
                workspace_selector_env_key="OTHER_WORKSPACE",
                env_prefix="DEMO_APP_",
                target=tmp_path / "src",
            )
        )


@pytest.mark.parametrize(
    ("user_dotenv", "workspaces"),
    ((False, False), (True, False), (False, True), (True, True)),
)
def test_scaffold_config_package_renders_independent_capabilities(
    tmp_path: Path,
    *,
    user_dotenv: bool,
    workspaces: bool,
) -> None:
    """Every user-file and workspace capability combination is explicit."""
    result = scaffold_config_package(
        ConfigScaffoldRequest(
            package="capability_demo",
            app_id="capability-demo",
            target=tmp_path / "src",
            user_dotenv=user_dotenv,
            workspaces=workspaces,
        )
    )
    generated = runpy.run_path(str(result.config_package_dir / "app.py"))[
        "MyRC"
    ]
    assert isinstance(generated, rc.AppRC)
    root = tmp_path / "application"
    options = rc.ResolveOptions(layout=rc.Layout.single_root(root))
    if user_dotenv or workspaces:
        assert (
            generated.ensure_path("config", options, environment={})
            == root / "config"
        )
        assert (root / "config" / ".apprc-owner.json").is_file()
    else:
        with pytest.raises(ValueError):
            generated.ensure_path("config", options, environment={})
        assert not root.exists()


def test_scaffold_config_package_escapes_generated_python_literals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffolded modules should import when labels need string escaping."""
    source_root = tmp_path / "src"
    scaffold_config_package(
        ConfigScaffoldRequest(
            package="quoted_demo",
            app_id="quoted-demo",
            display_name="Demo's App",
            target=source_root,
        )
    )

    monkeypatch.syspath_prepend(str(source_root))
    config_module = importlib.import_module("quoted_demo.config.app")

    assert config_module.MyRC.schema.display_name == "Demo's App"


def test_scaffold_config_package_refuses_overwrite_without_force(
    tmp_path: Path,
) -> None:
    """Scaffold reruns should be explicit about replacing files."""
    request = ConfigScaffoldRequest(
        package="demo_app",
        app_id="demo-app",
        target=tmp_path / "src",
    )

    scaffold_config_package(request)

    with pytest.raises(FileExistsError, match="already exist"):
        scaffold_config_package(request)

    forced = scaffold_config_package(
        ConfigScaffoldRequest(
            package="demo_app",
            app_id="demo-app",
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
            "--app-id",
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
