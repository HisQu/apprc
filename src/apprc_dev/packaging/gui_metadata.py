"""Keep the GUI distribution version and core pin aligned with AppRC core."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUI_PROJECT = ROOT / "src/apprc_dev/packaging/gui/pyproject.toml"
VERSION_LINE = re.compile(
    r'(?m)^(?P<prefix>[ \t]*version[ \t]*=[ \t]*)"[^"]+"(?P<suffix>[ \t]*)$'
)
CORE_PIN_LINE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)"(?P<pin>apprc-core==[^"]+)"'
    r"(?P<suffix>[ \t]*,?[ \t]*)$"
)
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def render_gui_pyproject(source: str, version: str) -> str:
    """Return GUI metadata with its version and core pin set to ``version``.

    :param source: Current GUI ``pyproject.toml`` contents.
    :param version: Core release version without a leading ``v``.
    :return: GUI metadata preserving all fields unrelated to the version.
    :raises ValueError: If the version or GUI metadata has an unexpected form.
    """
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"Invalid AppRC version {version!r}.")

    project = tomllib.loads(source)["project"]
    if project["name"] != "apprc-gui":
        raise ValueError("GUI metadata must declare the apprc-gui project.")
    core_pins = [
        dependency
        for dependency in project["dependencies"]
        if dependency.startswith("apprc-core==")
    ]
    if len(core_pins) != 1:
        raise ValueError(
            "GUI metadata must contain exactly one exact apprc-core pin."
        )

    updated, version_count = VERSION_LINE.subn(
        lambda match: f'{match["prefix"]}"{version}"{match["suffix"]}',
        source,
    )
    if version_count != 1:
        raise ValueError(
            "GUI metadata must contain exactly one project version."
        )
    updated, pin_count = CORE_PIN_LINE.subn(
        lambda match: (
            f'{match["indent"]}"apprc-core=={version}"{match["suffix"]}'
        ),
        updated,
    )
    if pin_count != 1:
        raise ValueError(
            "GUI metadata must contain exactly one exact apprc-core pin line."
        )

    updated_project = tomllib.loads(updated)["project"]
    if updated_project["version"] != version:
        raise ValueError("GUI project version did not update as expected.")
    if updated_project["dependencies"].count(f"apprc-core=={version}") != 1:
        raise ValueError("GUI core pin did not update as expected.")
    return updated


def sync_gui_metadata(
    version: str,
    *,
    path: Path = GUI_PROJECT,
    check: bool = False,
) -> None:
    """Write or check the GUI version and exact core dependency pin.

    :param version: Core release version without a leading ``v``.
    :param path: GUI package metadata file, or an isolated test file.
    :param check: Report stale metadata instead of writing it.
    :raises SystemExit: If check mode finds stale metadata.
    """
    source = path.read_text(encoding="utf-8")
    expected = render_gui_pyproject(source, version)
    if source == expected:
        return
    if check:
        raise SystemExit(
            "GUI metadata is stale. Run python "
            "src/apprc_dev/packaging/gui_metadata.py."
        )
    path.write_text(expected, encoding="utf-8")


def main() -> None:
    """Synchronize GUI metadata with the root project's current version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    sync_gui_metadata(project["version"], check=args.check)


if __name__ == "__main__":
    main()
