"""Exercise the durable local package bundle and GitHub publication boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apprc_dev.packaging import release_assets as assets


def _package_files(directory: Path, version: str) -> None:
    for name in assets.PROJECTS:
        for suffix in ("-py3-none-any.whl", ".tar.gz"):
            (directory / f"{name}-{version}{suffix}").write_bytes(name.encode())


@pytest.mark.parametrize("suffix", ["b", "rc"])
def test_retention_leaves_other_channels_and_tags_alone(suffix: str) -> None:
    def release(
        number: int, tag: str, *, draft: bool = False, preview: bool = True
    ) -> dict[str, object]:
        return {
            "id": number,
            "published_at": f"2026-11-{number:02}T00:00:00Z",
            "tag_name": tag,
            "draft": draft,
            "prerelease": preview,
        }

    other = "rc" if suffix == "b" else "b"
    releases = [
        release(4, f"v1.0.0{suffix}1"),
        release(3, f"v0.9.0{suffix}1"),
        release(2, f"v1.0.0{suffix}2"),
        release(1, f"v1.0.0{suffix}3"),
        release(7, f"v1.0.0{suffix}5", draft=True),
        release(8, f"v1.0.0{suffix}6", preview=False),
        release(9, "v1.0.0", preview=False),
        release(10, "testing"),
        release(11, f"v1.0.0{other}1"),
    ]
    assert assets.expired_releases(releases, f"v1.0.0{suffix}1") == [3, 2, 1]
    assert assets.expired_releases(releases, "v1.0.0") == []


def test_staging_detects_changed_bytes(tmp_path: Path) -> None:
    _package_files(tmp_path, "1.0.0b1")
    checksums = assets.bundle(tmp_path, "1.0.0b1", write=True)
    assert assets.bundle(tmp_path, "1.0.0b1") == checksums
    (tmp_path / "apprc-1.0.0b1.tar.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksums differ"):
        assets.bundle(tmp_path, "1.0.0b1")


def test_publisher_retries_only_missing_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "1.0.0rc1"
    tag = f"v{version}"
    _package_files(tmp_path, version)
    checksums = assets.bundle(tmp_path, version, write=True)
    remote_assets = [
        {"name": name, "digest": f"sha256:{digest}"}
        for name, digest in checksums.items()
    ]
    release = {
        "id": 1,
        "draft": True,
        "prerelease": True,
        "tag_name": tag,
        "assets": remote_assets[:1],
    }
    uploads: list[str] = []
    commit = "a" * 40
    requests: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        requests.append(args)
        if args[:2] == ("release", "upload"):
            uploads.extend(Path(value).name for value in args[5:])
            release["assets"] = remote_assets
        elif args[:2] == ("release", "edit"):
            release["draft"] = False
        elif args[0] == "api":
            return json.dumps(release)
        else:
            pytest.fail(f"unexpected request {args!r}")
        return ""

    monkeypatch.setattr(assets, "_gh", gh)
    monkeypatch.setattr(assets, "_releases", lambda _: [release])
    monkeypatch.setattr(assets, "_remote_tag_matches", lambda *args: None)
    for _ in range(2):
        assets.publish("owner/repo", tag, commit, tmp_path, tmp_path / "notes")
    assert sorted(uploads) == sorted(
        checksums.keys() - {remote_assets[0]["name"]}
    )
    assert sum(args[:2] == ("release", "edit") for args in requests) == 1

    remote_assets[0]["digest"] = "sha256:mismatch"
    with pytest.raises(ValueError, match="conflicts"):
        assets.publish("owner/repo", tag, commit, tmp_path, tmp_path / "notes")


def test_remote_tag_resolves_inside_release_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = "v1.0.0rc1"
    annotation = "b" * 40
    commit = "a" * 40
    responses = {
        f"repos/owner/target/git/ref/tags/{tag}": {
            "object": {"type": "tag", "sha": annotation}
        },
        f"repos/owner/target/git/tags/{annotation}": {
            "object": {"type": "commit", "sha": commit}
        },
    }
    monkeypatch.setattr(
        assets, "_gh", lambda _, endpoint: json.dumps(responses[endpoint])
    )
    assets._remote_tag_matches("owner/target", tag, commit)
    with pytest.raises(ValueError, match="does not resolve"):
        assets._remote_tag_matches("owner/target", tag, "c" * 40)


def test_rc_evidence_can_only_reuse_matching_dependencies() -> None:
    candidate = """
    [project]
    name = "apprc"
    version = "1.0.0rc1"
    dependencies = ["apprc-core==1.0.0rc1", "rich>=14"]
    """
    stable = candidate.replace("1.0.0rc1", "1.0.0")
    previous = assets._metadata_without_version(candidate, "1.0.0rc1")
    assert previous == assets._metadata_without_version(stable, "1.0.0")
    assert previous != assets._metadata_without_version(
        stable.replace("rich>=14", "rich>=15"), "1.0.0"
    )
