"""Behavioral coverage for immutable GitHub source identity."""

from apprc.definition._source_identity import parse_immutable_github_source
from apprc.definition.installation import InstallationSource
from apprc.user_files.installation.operations import _requires_record_proof


def test_parse_immutable_github_source_preserves_raw_identity() -> None:
    identity = parse_immutable_github_source(
        "git+https://github.com/Example/Project.git@"
        "0123456789abcdef0123456789abcdef01234567"
        "#subdirectory=packages/app"
    )

    assert identity is not None
    assert identity.owner == "Example"
    assert identity.repository == "Project.git"
    assert identity.commit == "0123456789abcdef0123456789abcdef01234567"
    assert identity.subdirectory == "packages/app"
    assert identity.repository_url == "https://github.com/Example/Project.git"


def test_parse_immutable_github_source_without_subdirectory() -> None:
    identity = parse_immutable_github_source(
        "git+https://github.com/owner/repository@"
        "0123456789abcdef0123456789abcdef01234567"
    )

    assert identity is not None
    assert identity.subdirectory is None


def test_parse_immutable_github_source_rejects_unaccepted_requirements() -> (
    None
):
    accepted_base = (
        "git+https://github.com/owner/repository@"
        "0123456789abcdef0123456789abcdef01234567"
    )
    rejected = (
        accepted_base.replace("github.com/", "user@github.com/"),
        accepted_base.replace("owner/", "owner@other/"),
        accepted_base[:-40] + "0123456789abcdef0123456789abcdef0123456",
        accepted_base[:-40] + "0123456789ABCDEF0123456789ABCDEF01234567",
        accepted_base + "\n",
        accepted_base + "#subdirectory=bad\\path",
    )

    for requirement in rejected:
        assert parse_immutable_github_source(requirement) is None


def test_observation_digest_requires_immutable_github_source() -> None:
    requirement = (
        "git+https://github.com/owner/repository.git@"
        "0123456789abcdef0123456789abcdef01234567"
        "#subdirectory=packages/app"
    )
    selected = InstallationSource("index", requirement)
    observed = InstallationSource("index", requirement, digest="a" * 64)

    assert selected.matches_observation(observed)
    assert not selected.matches_observation(
        InstallationSource("index", requirement + "\n", digest="a" * 64)
    )
    assert not selected.matches_observation(
        InstallationSource("index", requirement, digest="A" * 64)
    )
    assert not selected.matches_observation(
        InstallationSource("index", requirement, digest="a" * 63)
    )
    assert not InstallationSource("wheel", requirement).matches_observation(
        InstallationSource("wheel", requirement, digest="a" * 64)
    )


def test_record_proof_classification_keeps_source_and_digest_boundaries() -> (
    None
):
    requirement = (
        "git+https://github.com/owner/repository@"
        "0123456789abcdef0123456789abcdef01234567"
    )

    assert _requires_record_proof(
        InstallationSource("index", requirement, digest="a" * 64)
    )
    assert not _requires_record_proof(InstallationSource("index", requirement))
    assert not _requires_record_proof(
        InstallationSource("index", requirement + "\n", digest="a" * 64)
    )
    assert _requires_record_proof(
        InstallationSource("release-sdist", "https://example.invalid/source")
    )
