"""Create repository-local files used by the AppRC example CLIs."""

from __future__ import annotations

# == Standard Library ========================
import argparse
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

# == Internal ================================
import apprc

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SRC = ROOT / "examples" / "example_apps" / "src"


@dataclass(frozen=True, slots=True)
class ExampleBootstrapSpec:
    """Files and values needed to bootstrap one example app.

    :param name: Human-readable mode name used in summaries.
    :param root_name: Repository-local sandbox directory name.
    :param kit: AppRC contract for the example CLI.
    :param explicit_values: Values written to the arbitrary sourceable
        ``.env`` file.
    :param app_wide_values: Values written to the app-wide dotenv file.
    :param storage_values: Values written to the selected storage dotenv file.
    :param storage_name: Named-storage selector registered in the TOML index.
    """

    name: str
    root_name: str
    kit: apprc.AppConfigKit
    explicit_values: Mapping[str, str]
    app_wide_values: Mapping[str, str]
    storage_values: Mapping[str, str] | None = None
    storage_name: str = "alpha"

    @property
    def uses_storage(self) -> bool:
        """Return whether this example has a selected storage root."""
        return self.kit.spec.storage_required()


def _example_bootstraps() -> tuple[ExampleBootstrapSpec, ...]:
    """Return bootstrap specs after making local example packages importable."""
    _ensure_example_src_on_path()

    return (
        ExampleBootstrapSpec(
            name="env_only",
            root_name=".apprc-example-env-only",
            kit=_load_example_kit("apprc_env_only_example"),
            explicit_values={
                "APPRC_EXAMPLE_ENV_ONLY_PROFILE": "explicit-env-profile",
                "APPRC_EXAMPLE_ENV_ONLY_DEBUG": "true",
            },
            app_wide_values={
                "APPRC_EXAMPLE_ENV_ONLY_PROFILE": "app-wide-profile",
            },
        ),
        ExampleBootstrapSpec(
            name="storage_only",
            root_name=".apprc-example-storage-only",
            kit=_load_example_kit("apprc_storage_only_example"),
            explicit_values={
                "APPRC_EXAMPLE_STORAGE_ENABLED": "false",
                "APPRC_EXAMPLE_STORAGE_RETRY_COUNT": "7",
            },
            app_wide_values={
                "APPRC_EXAMPLE_STORAGE_PROFILE": "app-wide-profile",
            },
            storage_values={
                "APPRC_EXAMPLE_STORAGE_PROFILE": "storage-profile",
                "APPRC_EXAMPLE_STORAGE_MODE": "MANUAL",
                "APPRC_EXAMPLE_STORAGE_API_TOKEN": "storage-secret-token",
            },
        ),
        ExampleBootstrapSpec(
            name="app_wide_config",
            root_name=".apprc-example-app-wide-config",
            kit=_load_example_kit("apprc_app_wide_config_example"),
            explicit_values={
                "APPRC_EXAMPLE_APP_WIDE_WORKERS": "8",
            },
            app_wide_values={
                "APPRC_EXAMPLE_APP_WIDE_REGION": "app-wide-region",
                "APPRC_EXAMPLE_APP_WIDE_WORKERS": "4",
            },
        ),
        ExampleBootstrapSpec(
            name="app_wide_storage",
            root_name=".apprc-example-app-wide-storage",
            kit=_load_example_kit("apprc_app_wide_storage_example"),
            explicit_values={
                "APPRC_EXAMPLE_APP_WIDE_STORAGE_REGION": "explicit-region",
            },
            app_wide_values={
                "APPRC_EXAMPLE_APP_WIDE_STORAGE_REGION": "app-wide-region",
            },
            storage_values={
                "APPRC_EXAMPLE_APP_WIDE_STORAGE_ACCESS_TOKEN": (
                    "app-wide-storage-secret"
                ),
            },
        ),
        ExampleBootstrapSpec(
            name="explicit_env_precedence",
            root_name=".apprc-example-explicit-env-precedence",
            kit=_load_example_kit("apprc_explicit_env_precedence_example"),
            explicit_values={
                "APPRC_EXAMPLE_PRECEDENCE_LABEL": "explicit-env-label",
            },
            app_wide_values={
                "APPRC_EXAMPLE_PRECEDENCE_LABEL": "app-wide-label",
            },
            storage_values={
                "APPRC_EXAMPLE_PRECEDENCE_LABEL": "storage-label",
            },
        ),
        ExampleBootstrapSpec(
            name="cli_bridge",
            root_name=".apprc-example-cli-bridge",
            kit=_load_example_kit("apprc_cli_bridge_example"),
            explicit_values={
                "APPRC_EXAMPLE_BRIDGE_PROFILE": "explicit-bridge-profile",
            },
            app_wide_values={
                "APPRC_EXAMPLE_BRIDGE_PROFILE": "app-wide-bridge-profile",
            },
            storage_values={
                "APPRC_EXAMPLE_BRIDGE_API_TOKEN": "bridge-secret-token",
            },
        ),
    )


def _load_example_kit(package_name: str) -> apprc.AppConfigKit:
    """Load a dev-only example kit without exposing optional imports globally.

    :param package_name: Import package that owns an example app.
    :return: AppRC kit declared by that package's ``config`` module.
    :raises TypeError: If the package does not expose ``KIT`` correctly.
    """
    module = import_module(f"{package_name}.config")
    # !! Dynamic boundary: example packages are optional dev-only source that
    # downstream repos do not add to their static type-checker paths.
    kit = getattr(module, "KIT")
    if isinstance(kit, apprc.AppConfigKit):
        return kit
    raise TypeError(f"{package_name}.config.KIT is not an AppConfigKit.")


def _ensure_example_src_on_path() -> None:
    """Make repository-local example packages importable before installation."""
    example_src_text = str(EXAMPLE_SRC)
    if example_src_text not in sys.path:
        sys.path.insert(0, example_src_text)


def bootstrap_example_apps(
    *,
    repo_root: Path = ROOT,
    clean: bool = False,
) -> list[Path]:
    """Create deterministic local files for all example CLIs.

    The generated directories are ignored by the repository. They mirror real
    AppRC file ownership while keeping the developer's actual config home and
    storage roots untouched.

    :param repo_root: Repository root where sandbox directories should live.
    :param clean: Whether to remove existing example sandboxes first.
    :return: Sourceable ``.env`` files written for each example.
    """
    env_files: list[Path] = []
    for spec in _example_bootstraps():
        root = repo_root / spec.root_name
        if clean and root.exists():
            shutil.rmtree(root)
        env_files.append(_bootstrap_one(root=root, spec=spec))
    return env_files


def _bootstrap_one(*, root: Path, spec: ExampleBootstrapSpec) -> Path:
    """Create one example sandbox and return its sourceable env file."""
    root.mkdir(parents=True, exist_ok=True)
    xdg_config_home = root / "xdg-config-home"
    config_home = xdg_config_home / spec.kit.spec.app_name
    config_home.mkdir(parents=True, exist_ok=True)

    app_wide_env = config_home / spec.kit.spec.app_wide_env_filename
    _write_env_layer(
        path=app_wide_env,
        layer="app-wide dotenv overrides",
        real_location=(
            "<platform config home>/"
            f"{spec.kit.spec.app_name}/{spec.kit.spec.app_wide_env_filename}"
        ),
        values=spec.app_wide_values,
    )

    storage_root = None
    index_path = config_home / spec.kit.spec.index_filename
    if spec.uses_storage:
        storage_root = root / "storages" / spec.storage_name
        storage_root.mkdir(parents=True, exist_ok=True)
        _write_env_layer(
            path=storage_root / spec.kit.spec.storage_env_filename,
            layer="storage-local dotenv overrides",
            real_location=(
                f"<selected storage root>/{spec.kit.spec.storage_env_filename}"
            ),
            values=spec.storage_values or {},
        )
        _write_storage_index(
            path=index_path,
            storage_name=spec.storage_name,
            storage_root=storage_root,
            app_name=spec.kit.spec.app_name,
            index_filename=spec.kit.spec.index_filename,
        )

    env_path = root / ".env"
    _write_sourceable_env(
        path=env_path,
        spec=spec,
        xdg_config_home=xdg_config_home,
        index_path=index_path,
        storage_root=storage_root,
    )
    return env_path


def _write_sourceable_env(
    *,
    path: Path,
    spec: ExampleBootstrapSpec,
    xdg_config_home: Path,
    index_path: Path,
    storage_root: Path | None,
) -> None:
    """Write the arbitrary user-owned env file for one example."""
    values = {
        "XDG_CONFIG_HOME": str(xdg_config_home.resolve()),
        **dict(spec.explicit_values),
    }
    if spec.uses_storage:
        storage_env_key = spec.kit.spec.require_storage_env_key()
        if storage_root is None:
            raise RuntimeError(f"{spec.name} requires a storage root.")
        values[storage_env_key] = str(storage_root.resolve())
        values[spec.kit.spec.index_env_key] = str(index_path.resolve())

    comment = [
        "# Generated by python -m apprc_dev.example_apps.bootstrap.",
        "# AppRC layer: explicit env file or shell-exported values.",
        "# AppRC does not choose a location for this file in real apps.",
        "# Source it manually, for example: set -a; source .env; set +a",
        f"# Example command: {spec.kit.spec.config_command_name()} config doctor",
        "",
    ]
    path.write_text(
        "\n".join(comment + _dotenv_lines(values)) + "\n",
        encoding="utf-8",
    )


def _write_env_layer(
    *,
    path: Path,
    layer: str,
    real_location: str,
    values: Mapping[str, str],
) -> None:
    """Write one AppRC-managed dotenv layer with explanatory comments."""
    path.parent.mkdir(parents=True, exist_ok=True)
    comment = [
        "# Generated by python -m apprc_dev.example_apps.bootstrap.",
        f"# AppRC layer: {layer}.",
        f"# Bootstrapped checkout path: {path.resolve()}",
        f"# Real app location: {real_location}",
        "",
    ]
    path.write_text(
        "\n".join(comment + _dotenv_lines(values)) + "\n",
        encoding="utf-8",
    )


def _write_storage_index(
    *,
    path: Path,
    storage_name: str,
    storage_root: Path,
    app_name: str,
    index_filename: str,
) -> None:
    """Write a named-storage TOML index with explanatory comments."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "# Generated by python -m apprc_dev.example_apps.bootstrap.",
            "# AppRC layer: named-storage TOML index.",
            f"# Bootstrapped checkout path: {path.resolve()}",
            f"# Real app location: <platform config home>/{app_name}/{index_filename}",
            "",
            f"[storages.{storage_name}]",
            f"root = {json.dumps(str(storage_root.resolve()))}",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _dotenv_lines(values: Mapping[str, str]) -> list[str]:
    """Return deterministic dotenv assignment lines."""
    return [
        f"{key}={json.dumps(value)}" for key, value in sorted(values.items())
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the bootstrap helper.

    :param argv: Optional argument vector used by tests.
    :return: Parsed command namespace.
    """
    parser = argparse.ArgumentParser(
        description="Bootstrap repository-local AppRC example app files.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing example sandboxes before writing files.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Repository root where .apprc-example* directories are written.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the example bootstrap helper.

    :param argv: Optional argument vector used by tests.
    :return: Process exit code.
    """
    args = parse_args(argv)
    env_files = bootstrap_example_apps(
        repo_root=args.repo_root,
        clean=args.clean,
    )
    print("Bootstrapped AppRC example files:")
    for env_file in env_files:
        print(f"  {env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
