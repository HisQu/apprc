"""SDK requirement selection and authenticated output replacement behavior."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from packaging.requirements import Requirement

import apprc.distribution.frontends as frontends
from apprc.definition.installation import InstallationIdentity
from apprc.distribution.models import DistributionSpec, ProjectMetadata


class _Metadata:
    def __init__(self, requirements: tuple[str, ...]) -> None:
        self._requirements = requirements

    def get_all(self, name: str) -> tuple[str, ...] | None:
        assert name == "Requires-Dist"
        return self._requirements


class _Distribution:
    version = "0.34.0"

    def __init__(self, requirements: tuple[str, ...]) -> None:
        self.metadata = _Metadata(requirements)


def test_bootstrap_requirements_select_extras_and_preserve_full_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distributions = {
        "apprc-core": _Distribution(
            (
                "attrs>=23",
                'typed-settings[dotenv]>=24; extra == "distribution"',
                'platformdirs>=4; sys_platform == "win32" '
                'and extra == "distribution"',
                'test-only>=1; extra == "test"',
                'apprc-core==0.34; extra == "distribution"',
                "local-plugin @ https://example.invalid/local_plugin.whl",
            )
        ),
        "apprc": _Distribution(
            (
                "rich>=13",
                'terminal-extra>=1; extra == "distribution"',
                "apprc-core==0.34",
            )
        ),
    }
    monkeypatch.setattr(
        frontends.importlib.metadata,
        "distribution",
        lambda name: distributions[name],
    )

    requirements = {
        Requirement(row) for row in frontends._bootstrap_requirements()
    }

    assert Requirement("attrs>=23") in requirements
    assert Requirement("typed-settings[dotenv]>=24") in requirements
    assert (
        Requirement('platformdirs>=4; sys_platform == "win32"') in requirements
    )
    assert (
        Requirement("local-plugin @ https://example.invalid/local_plugin.whl")
        in requirements
    )
    assert Requirement("rich>=13") in requirements
    assert not any(
        item.name in {"test-only", "terminal-extra", "apprc-core"}
        for item in requirements
    )


def _spec(project_root: Path) -> DistributionSpec:
    identity = InstallationIdentity(
        "publication-fixture",
        "publication-fixture",
        "publication_fixture",
        None,
        ("publication-fixture",),
    )
    metadata = ProjectMetadata(
        project_root.resolve(),
        identity,
        "1.0.0",
        command_name="publication-fixture",
    )
    return DistributionSpec(metadata)


def _linux_name(spec: DistributionSpec) -> str:
    return f"{spec.metadata.identity.app_id}-setup-linux-x86_64"


def test_publication_refuses_unauthenticated_collision_without_mutation(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    name = _linux_name(spec)
    path = dist / name
    original = b"user-owned setup"
    path.write_bytes(original)

    with pytest.raises(FileExistsError, match="unauthenticated native output"):
        frontends._publish(spec, {name: (b"new setup", True)})

    assert path.read_bytes() == original
    assert not (dist / "SHA256SUMS").exists()


def test_publication_replaces_only_checksum_authenticated_output(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    name = _linux_name(spec)
    original = b"previous authenticated setup"
    (dist / name).write_bytes(original)
    old_digest = hashlib.sha256(original).hexdigest()
    (dist / "SHA256SUMS").write_text(
        f"{old_digest}  {name}\n", encoding="ascii"
    )

    content = b"new setup"
    manifest = frontends._publish(spec, {name: (content, True)})

    assert (dist / name).read_bytes() == content
    assert (dist / "SHA256SUMS").read_bytes() == manifest.content
    assert manifest.content == (
        f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()
    )


@pytest.mark.parametrize("failure_number", (1, 2), ids=("setup", "manifest"))
def test_publication_restores_outputs_and_cleans_staging_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_number: int,
) -> None:
    spec = _spec(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    name = _linux_name(spec)
    old_output = b"old setup"
    old_manifest = (
        f"{hashlib.sha256(old_output).hexdigest()}  {name}\n".encode()
    )
    (dist / name).write_bytes(old_output)
    (dist / "SHA256SUMS").write_bytes(old_manifest)
    unknown = dist / "preserve-me.txt"
    unknown.write_bytes(b"unknown dist file")
    original_replace = os.replace
    replacements = 0

    def fail_replace(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == failure_number:
            raise OSError("controlled publication replacement failure")
        original_replace(source, destination)

    monkeypatch.setattr(frontends.os, "replace", fail_replace)
    with pytest.raises(
        OSError, match="controlled publication replacement failure"
    ):
        frontends._publish(spec, {name: (b"replacement", True)})

    assert (dist / name).read_bytes() == old_output
    assert (dist / "SHA256SUMS").read_bytes() == old_manifest
    assert unknown.read_bytes() == b"unknown dist file"
    assert {path.name for path in dist.iterdir()} == {
        name,
        "SHA256SUMS",
        "preserve-me.txt",
    }
