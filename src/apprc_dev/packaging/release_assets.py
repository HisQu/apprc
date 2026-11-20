"""Validate and publish AppRC's locally staged release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any

from apprc_dev.packaging.release_notes import VERSION_RE, validate_tag_version

PROJECTS = ("apprc_core", "apprc", "apprc_gui")
CHECKSUMS = "SHA256SUMS"


def channel(tag: str) -> str | None:
    """Classify a canonical tag, leaving unrelated tags outside the channels."""
    if not tag.startswith("v") or VERSION_RE.fullmatch(tag[1:]) is None:
        return None
    if "rc" in tag:
        return "Pre-release"
    if "b" in tag:
        return "Beta"
    return "Stable"


def expected_checksums(directory: Path, version: str) -> dict[str, str]:
    """Read exactly the three wheels and three source archives for a version."""
    names = {
        f"{project}-{version}{suffix}"
        for project in PROJECTS
        for suffix in ("-py3-none-any.whl", ".tar.gz")
    }
    if {path.name for path in directory.iterdir()} - {CHECKSUMS} != names:
        raise ValueError(
            "Expected exactly three wheels and three source archives for the tag."
        )
    checksums = {}
    for name in sorted(names):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid artifact: {path}")
        with path.open("rb") as stream:
            checksums[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return checksums


def bundle(
    directory: Path, version: str, *, write: bool = False
) -> dict[str, str]:
    """Create or verify the package checksum manifest."""
    checksums = expected_checksums(directory, version)
    manifest = directory / CHECKSUMS
    contents = "".join(
        f"{digest}  {name}\n" for name, digest in checksums.items()
    )
    if manifest.is_symlink():
        raise ValueError("The release checksum manifest is a symbolic link.")
    if write:
        manifest.write_text(contents, encoding="ascii")
    elif manifest.read_text(encoding="ascii") != contents:
        raise ValueError("Locally staged package checksums differ.")
    return checksums | {
        CHECKSUMS: hashlib.sha256(contents.encode("ascii")).hexdigest()
    }


def expired_releases(releases: list[dict[str, Any]], tag: str) -> list[int]:
    """Return GitHub release IDs to prune, ordered by publication time."""
    preview_channel = channel(tag)
    if preview_channel not in ("Beta", "Pre-release"):
        return []
    candidates = [
        release
        for release in releases
        if release.get("draft") is False
        and release.get("prerelease") is True
        and release.get("published_at")
        and channel(release["tag_name"]) == preview_channel
    ]
    candidates.sort(
        key=lambda item: (
            datetime.fromisoformat(item["published_at"]),
            item["id"],
        ),
        reverse=True,
    )
    return [item["id"] for item in candidates[3:]]


def _gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def _releases(repository: str) -> list[dict[str, Any]]:
    pages = json.loads(
        _gh(
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/releases?per_page=100",
        )
    )
    return [release for page in pages for release in page]


def _remote_tag_matches(tag: str, commit: str) -> None:
    ref = f"refs/tags/{tag}^{{}}"
    advertised = subprocess.check_output(
        ["git", "ls-remote", "origin", ref], text=True
    ).strip()
    if advertised != f"{commit}\t{ref}":
        raise ValueError(
            f"Remote annotated tag {tag} does not resolve to {commit}."
        )


def _missing_assets(
    release: dict[str, Any], checksums: dict[str, str]
) -> list[str]:
    assets = release["assets"]
    for asset in assets:
        name = asset["name"]
        if (
            name not in checksums
            or asset["digest"] != f"sha256:{checksums[name]}"
        ):
            raise ValueError(
                f"Existing GitHub asset conflicts with the local bundle: {name}"
            )
    return sorted(checksums.keys() - {asset["name"] for asset in assets})


def publish(
    repository: str, tag: str, commit: str, directory: Path, notes: Path
) -> None:
    """Upload verified package bytes, finalize the matching draft, and prune."""
    checksums = bundle(directory, tag[1:])
    _remote_tag_matches(tag, commit)
    preview = channel(tag) != "Stable"
    release_options = (
        "--repo",
        repository,
        f"--prerelease={str(preview).lower()}",
    )
    matches = [
        item for item in _releases(repository) if item["tag_name"] == tag
    ]
    if not matches:
        _gh(
            "release",
            "create",
            tag,
            "--verify-tag",
            "--draft",
            "--title",
            f"AppRC {tag[1:]} · {channel(tag)}",
            "--notes-file",
            str(notes),
            *release_options,
        )
        matches = [
            item for item in _releases(repository) if item["tag_name"] == tag
        ]
    if len(matches) != 1 or matches[0]["prerelease"] is not preview:
        raise ValueError(
            f"Could not verify the matching {tag} release and channel."
        )
    release = matches[0]
    missing = _missing_assets(release, checksums)
    if release["draft"]:
        if missing:
            _gh(
                "release",
                "upload",
                tag,
                "--repo",
                repository,
                *(str(directory / name) for name in missing),
            )
        updated = json.loads(
            _gh("api", f"repos/{repository}/releases/{release['id']}")
        )
        if _missing_assets(updated, checksums) or not updated["draft"]:
            raise ValueError("The GitHub draft changed during upload.")
        _remote_tag_matches(tag, commit)
        _gh("release", "edit", tag, "--draft=false", *release_options)
    elif missing:
        raise ValueError(f"Published release {tag} is missing expected assets.")

    print(f"GitHub release {tag} is published.")
    if preview:
        try:
            for release_id in expired_releases(_releases(repository), tag):
                _gh(
                    "api",
                    "--method",
                    "DELETE",
                    f"repos/{repository}/releases/{release_id}",
                )
        except subprocess.SubprocessError as error:
            print(
                f"Warning: preview retention failed. Retry just release-push {tag}: {error}",
                file=sys.stderr,
            )


_METADATA = {
    "pyproject.toml",
    "uv.lock",
    "pylock.toml",
    "examples/example_apps/pyproject.toml",
    "src/apprc_dev/packaging/gui/pyproject.toml",
    "src/apprc_dev/packaging/terminal/pyproject.toml",
}
_WORKSPACE = ("apprc", "apprc-core", "apprc-gui")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def _metadata_without_version(contents: str, version: str) -> Any:
    # > Compare dependency resolutions and requirements after removing only the
    # > workspace's generated version pins.
    release_range = (
        f">={version},<{version.split('.')[0]}.{int(version.split('.')[1]) + 1}"
    )
    pins = {
        f"{name}{specifier}": f"{name}{placeholder}"
        for name in _WORKSPACE
        for specifier, placeholder in (
            (f"=={version}", "==VERSION"),
            (release_range, ">=VERSION"),
        )
    }

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: normalize(item) for key, item in value.items()}
            if value.get("name") in _WORKSPACE:
                if value.get("version") == version:
                    result["version"] = "VERSION"
                if value.get("specifier") in (f"=={version}", release_range):
                    result["specifier"] = pins[
                        value["name"] + value["specifier"]
                    ]
            return result
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            return pins.get(value, value)
        return value

    return normalize(tomllib.loads(contents))


def reuse_rc(tag: str) -> bool:
    """Use a successful same-cycle RC when the source and dependencies match."""
    if channel(tag) != "Stable":
        return False
    candidates = _git(
        "tag", "--list", "--sort=-version:refname", f"{tag}rc*"
    ).splitlines()
    for candidate in candidates:
        if (
            channel(candidate) != "Pre-release"
            or subprocess.run(
                ["git", "merge-base", "--is-ancestor", candidate, tag],
                check=False,
            ).returncode
            != 0
        ):
            continue
        paths = set(_git("diff", "--name-only", candidate, tag).splitlines())
        paths.discard("CHANGELOG.md")
        if paths - _METADATA:
            continue
        if not all(
            _metadata_without_version(
                _git("show", f"{candidate}:{path}"), candidate[1:]
            )
            == _metadata_without_version(_git("show", f"{tag}:{path}"), tag[1:])
            for path in paths
        ):
            continue
        commit = _git("rev-parse", f"{candidate}^{{commit}}").strip()
        if json.loads(
            _gh(
                "run",
                "list",
                "--workflow",
                "ci.yml",
                "--event",
                "push",
                "--branch",
                candidate,
                "--commit",
                commit,
                "--status",
                "success",
                "--json",
                "databaseId",
                "--limit",
                "1",
            )
        ):
            print(f"Using successful CI from {candidate} ({commit}).")
            return True
    return False


def main() -> int:
    """Validate or publish a bundle for the checked-out project version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("seal", "verify", "publish", "reuse-rc")
    )
    parser.add_argument("tag")
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--repository", default="HisQu/apprc")
    parser.add_argument("--commit")
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "reuse-rc":
            return 0 if reuse_rc(args.tag) else 1
        if args.directory is None:
            parser.error("a package directory is required")
        project = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )
        validate_tag_version(args.tag, project["project"]["version"])
        if args.command == "publish":
            if args.commit is None or args.notes is None:
                parser.error("publish needs --commit and --notes")
            publish(
                args.repository,
                args.tag,
                args.commit,
                args.directory,
                args.notes,
            )
        else:
            bundle(args.directory, args.tag[1:], write=args.command == "seal")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"release-assets: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
