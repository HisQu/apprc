"""Keep repository-local example requirements compatible with the release."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

from apprc_dev.packaging.release_notes import validate_version

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROJECT = ROOT / "examples/example_apps/pyproject.toml"
REQUIREMENT_LINE = re.compile(r'"(?P<name>apprc(?:-gui)?)>=[^"]+"')


def render_example_pyproject(source: str, version: str) -> str:
    """Align CLI and desktop requirements without widening minor compatibility.

    :param source: Current example package metadata.
    :param version: Core release version without a leading ``v``.
    :return: Metadata requiring this release through its next minor boundary.
    :raises ValueError: If the version or managed requirements are malformed.
    """
    validate_version(version)
    project = tomllib.loads(source)["project"]
    if project["name"] != "apprc-example-apps":
        raise ValueError("Example metadata must declare apprc-example-apps.")
    for name, dependencies in (
        ("apprc", project["dependencies"]),
        ("apprc-gui", project["optional-dependencies"]["desktop"]),
    ):
        if sum(dep.startswith(f"{name}>=") for dep in dependencies) != 1:
            raise ValueError(
                f"Example metadata must contain exactly one {name} range."
            )

    major, minor, _ = map(int, version.split("."))
    compatibility = f">={version},<{major}.{minor + 1}"
    updated, count = REQUIREMENT_LINE.subn(
        lambda match: f'"{match["name"]}{compatibility}"',
        source,
    )
    if count != 2:
        raise ValueError(
            "Example metadata must contain exactly two managed requirement lines."
        )
    updated_project = tomllib.loads(updated)["project"]
    for name, dependencies in (
        ("apprc", updated_project["dependencies"]),
        ("apprc-gui", updated_project["optional-dependencies"]["desktop"]),
    ):
        if dependencies.count(f"{name}{compatibility}") != 1:
            raise ValueError(
                f"Example {name} range did not update as expected."
            )
    return updated


def sync_example_metadata(
    version: str,
    *,
    path: Path = EXAMPLE_PROJECT,
    check: bool = False,
) -> None:
    """Write or check the examples' CLI and optional desktop release ranges.

    :param version: Core release version without a leading ``v``.
    :param path: Example package metadata file, or an isolated test file.
    :param check: Report stale metadata instead of writing it.
    :raises SystemExit: If check mode finds stale metadata.
    """
    source = path.read_text(encoding="utf-8")
    expected = render_example_pyproject(source, version)
    if source == expected:
        return
    if check:
        raise SystemExit(
            "Example metadata is stale. Run "
            "PYTHONPATH=src python -m "
            "apprc_dev.packaging.example_metadata."
        )
    path.write_text(expected, encoding="utf-8")


def main() -> None:
    """Synchronize example requirements with the root project's version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    sync_example_metadata(project["version"], check=args.check)


if __name__ == "__main__":
    main()
