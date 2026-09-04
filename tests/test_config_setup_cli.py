from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
)
from tests.support_config import (
    ApprcExampleAppConfigState,
    StorageFreeExampleConfigState,
    assert_apprc_dir_cli_error,
    block_apprc_dir_with_file,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_storage_free_setup_creates_empty_user_dotenv() -> None:
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert kit.spec.user_dotenv_path().read_text(encoding="utf-8") == ""
    assert not kit.spec.preferred_apprc_toml_path().exists()
    assert "user_dotenv:" in result.output


def test_storage_setup_creates_fixed_files_and_default_registry(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    storage_root = tmp_path / "storage"

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert result.exit_code == 0, result.output
    assert kit.spec.user_dotenv_path().is_file()
    assert (storage_root / "apprc.storage.env").is_file()
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected_storage == "default"
    assert registry.selected("default").root == storage_root.resolve()
    assert "selected_storage: default" in result.output


def test_storage_setup_uses_default_storage_root_without_extra_nesting() -> (
    None
):
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected("default").root == kit.spec.apprc_dir() / "storage"
    assert not (kit.spec.apprc_dir() / "storage" / "default").exists()


def test_storage_setup_rejects_blank_storage_root(tmp_path: Path) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", ""],
    )

    assert result.exit_code != 0, result.output
    assert "must not be empty" in result.output
    assert not (tmp_path / "apprc.storage.env").exists()


def test_repeated_setup_never_implicitly_repoints_default_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = runner.invoke(
        app, ["setup", "--yes", "--storage-root", str(first_root)]
    )
    second = runner.invoke(
        app, ["setup", "--yes", "--storage-root", str(second_root)]
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code != 0, second.output
    assert "storage repoint" in second.output
    registry = load_storage_registry_or_empty(
        kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected("default").root == first_root.resolve()
    assert not second_root.exists()


def test_setup_reports_blocking_apprc_directory_without_touching_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    storage_dotenv = storage_root / "apprc.storage.env"
    storage_dotenv.write_text("KEEP=1\n", encoding="utf-8")
    block_apprc_dir_with_file(kit)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert_apprc_dir_cli_error(result)
    assert storage_dotenv.read_text(encoding="utf-8") == "KEEP=1\n"
