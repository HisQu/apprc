"""Validate target-interpreter observations before committing ready authority."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from apprc.distribution.runtime.acquisition import (
    _validate_content_addressed_origin,
)
from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
    InstalledSnapshot,
    UvToolTarget,
)
from apprc.user_files.app_home.locations import assert_no_links

from apprc.distribution.runtime.backend import (
    backend_environment,
    tool_interpreter,
)
from apprc.user_files.app_home.writes import file_revision


def _repository_identity(
    address: str,
) -> tuple[str, str, int | None, str] | None:
    """Normalize only public repository URL components for VCS provenance checks."""
    parsed = urlsplit(address)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    path = parsed.path.rstrip("/")
    if path.casefold().endswith(".git"):
        path = path[:-4]
    return parsed.scheme, parsed.hostname.casefold(), port, path


def _archive_sha256(direct: object) -> str | None:
    """Read consistent SHA-256 values from PEP 610 archive metadata.

    :param direct: PEP 610 direct-URL observation.
    :return: Observed lowercase SHA-256, or ``None`` if absent or conflicting.
    """
    archive = direct.get("archive_info") if isinstance(direct, dict) else None
    if not isinstance(archive, dict):
        return None
    observed: list[str] = []
    hashes = archive.get("hashes")
    if isinstance(hashes, dict) and isinstance(hashes.get("sha256"), str):
        observed.append(hashes["sha256"])
    legacy_hash = archive.get("hash")
    if isinstance(legacy_hash, str):
        algorithm, separator, digest = legacy_hash.partition("=")
        if algorithm == "sha256" and separator:
            observed.append(digest)
    if not observed or any(value != observed[0] for value in observed[1:]):
        return None
    return observed[0]


def probe_installed_tool(
    target: UvToolTarget,
    identity: InstallationIdentity,
    source: InstallationSource,
    placement: InstallationPlacement,
    *,
    probe_path: Path,
    environment: Mapping[str, str],
    operation_context: Path | None = None,
    acquisition_requirement: str | None = None,
    acquisition_digest: str | None = None,
    expected_record_digest: str | None = None,
) -> InstalledSnapshot:
    """Execute the staged probe with the target's own isolated interpreter.

    :param target: Selected or recorded uv backend.
    :param identity: Expected host/package/import/commands declaration.
    :param source: Exact acquisition input to validate against metadata.
    :param placement: Intended captured resource addresses.
    :param probe_path: Absolute ordinary-Python installed_probe.py file.
    :param environment: Captured invocation environment.
    :param operation_context: Private pending authorization for resource setup.
    :param acquisition_requirement: Optional local source directory path for this install.
    :param acquisition_digest: SHA-256 of the independently validated original archive.
    :param expected_record_digest: Previously observed installed RECORD SHA-256.
    :return: Actual validated snapshot, never a prediction from uv's exit code.
    """
    if (
        expected_record_digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", expected_record_digest) is None
    ):
        raise InstallationError(
            "Expected distribution RECORD digest must be SHA-256."
        )
    interpreter = tool_interpreter(target, identity.distribution)
    argv = [
        str(interpreter),
        "-I",
        str(probe_path),
        "--distribution",
        identity.distribution,
        "--app-id",
        identity.app_id,
        "--import-package",
        identity.import_package,
    ]
    for command in identity.commands:
        argv.extend(("--command", command))
    if identity.apprc_reference is not None:
        argv.extend(("--apprc-reference", identity.apprc_reference))
    if operation_context is not None:
        argv.extend(("--operation-context", str(operation_context)))
    result = subprocess.run(
        argv,
        env=backend_environment(target, environment),
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(result.stdout)
    expected_fields = {
        "distribution",
        "version",
        "prefix",
        "interpreter",
        "commands",
        "direct_url",
        "capabilities",
        "initialized",
        "distribution_record_digest",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise InstallationError(
            "Installed probe returned an incompatible observation."
        )
    record_digest = value["distribution_record_digest"]
    if record_digest is not None and (
        not isinstance(record_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", record_digest) is None
    ):
        raise InstallationError(
            "Installed distribution RECORD digest is invalid."
        )
    if (
        expected_record_digest is not None
        and record_digest != expected_record_digest
    ):
        raise InstallationError(
            "Installed distribution RECORD digest differs from the saved observation."
        )
    archive_requires_record = source.kind in {"release-sdist", "wheel"} or (
        source.kind == "index"
        and (
            source.digest is not None
            or acquisition_requirement is not None
            or acquisition_digest is not None
        )
        and re.fullmatch(
            r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
            source.requirement,
        )
        is not None
    )
    if archive_requires_record and record_digest is None:
        raise InstallationError(
            "Installed archive distribution has no verifiable RECORD fingerprint."
        )
    if (
        not isinstance(value["distribution"], str)
        or re.sub(r"[-_.]+", "-", value["distribution"]).lower()
        != identity.distribution
    ):
        raise InstallationError(
            "Installed distribution identity differs from intended package."
        )
    if not isinstance(value["version"], str) or not value["version"]:
        raise InstallationError("Installed package version is unavailable.")
    if source.version is not None and value["version"] != source.version:
        raise InstallationError(
            "Installed package version differs from the verified source."
        )
    if (
        source.digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", source.digest) is None
    ):
        raise InstallationError("Selected source digest must be SHA-256.")
    if source.kind == "editable" and source.digest is not None:
        raise InstallationError(
            "Editable sources do not carry archive digests."
        )
    if (
        source.digest is not None
        and acquisition_digest is not None
        and source.digest != acquisition_digest
    ):
        raise InstallationError(
            "Verified acquisition digest differs from the selected source."
        )
    prefix = target.tool_dir / identity.distribution
    if value["prefix"] != str(prefix) or value["interpreter"] != str(
        interpreter
    ):
        raise InstallationError(
            "Target interpreter reports a different environment; refusing adoption."
        )
    capabilities = value["capabilities"]
    if (
        not isinstance(capabilities, dict)
        or set(capabilities) != {"config", "appdata", "cache", "state"}
        or any(type(enabled) is not bool for enabled in capabilities.values())
        or frozenset(kind for kind, enabled in capabilities.items() if enabled)
        != placement.capabilities
    ):
        raise InstallationError(
            "Installed capabilities differ from the intended declaration."
        )
    commands = value["commands"]
    if not isinstance(commands, dict) or set(commands) != set(
        identity.commands
    ):
        raise InstallationError(
            "Installed console entry inventory differs from intended commands."
        )
    observed_digest: str | None = None
    direct = value["direct_url"]
    if source.kind == "editable":
        if (
            not isinstance(direct, dict)
            or not isinstance(direct.get("url"), str)
            or not isinstance(direct.get("dir_info"), dict)
            or direct["dir_info"].get("editable") is not True
        ):
            raise InstallationError(
                "Backend did not establish an editable application source."
            )
        url = urlsplit(direct["url"])
        if url.scheme != "file":
            raise InstallationError(
                "Editable metadata does not address a local project."
            )
        installed_source = Path(url2pathname(url.path))
        if url.netloc and url.netloc != "localhost":
            installed_source = Path("//" + url.netloc + str(installed_source))
        if os.path.normcase(
            str(installed_source.resolve())
        ) != os.path.normcase(str(Path(source.requirement).resolve())):
            raise InstallationError(
                "Editable metadata points to another checkout."
            )
    elif (
        source.kind == "index"
        and re.fullmatch(
            r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
            source.requirement,
        )
        and (
            source.digest is not None
            or acquisition_requirement is not None
            or acquisition_digest is not None
        )
    ):
        digest = acquisition_digest or source.digest
        direct_url = direct.get("url") if isinstance(direct, dict) else None
        dir_info = direct.get("dir_info") if isinstance(direct, dict) else None
        if (
            not isinstance(direct, dict)
            or set(direct) != {"url", "dir_info"}
            or not isinstance(direct_url, str)
            or not isinstance(dir_info, dict)
            or dir_info.get("editable") is True
            or digest is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise InstallationError(
                "Installed main source lacks verified local-directory metadata."
            )
        url = urlsplit(direct_url)
        if url.scheme != "file" or url.fragment or url.query:
            raise InstallationError(
                "Installed main source does not identify a local directory."
            )
        actual = Path(url2pathname(url.path))
        if url.netloc and url.netloc != "localhost":
            actual = Path("//" + url.netloc + str(actual))
        if acquisition_requirement is None:
            if expected_record_digest is None:
                raise InstallationError(
                    "Saved main source lacks its installed RECORD fingerprint."
                )
            _validate_content_addressed_origin(source, digest, actual)
            expected = actual
        else:
            expected = Path(acquisition_requirement)
            _validate_content_addressed_origin(source, digest, expected)
            assert_no_links(actual)
            if not actual.is_dir():
                raise InstallationError(
                    "Installed main source directory is unavailable."
                )
        if os.path.normcase(
            str(actual.resolve(strict=False))
        ) != os.path.normcase(str(expected.resolve(strict=False))):
            raise InstallationError(
                "Installed main source differs from its content-addressed project."
            )
        observed_digest = digest
    elif source.kind == "index" and source.requirement.startswith("git+"):
        durable_locator, _, project_fragment = source.requirement.partition("#")
        expected_repository, separator, expected_commit = durable_locator[
            4:
        ].rpartition("@")
        if (
            not separator
            or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None
        ):
            raise InstallationError(
                "Remote VCS source must retain one full immutable commit."
            )
        vcs = direct.get("vcs_info") if isinstance(direct, dict) else None
        remote = direct.get("url") if isinstance(direct, dict) else None
        expected_subdirectory = (
            unquote(project_fragment.partition("=")[2])
            if project_fragment.startswith("subdirectory=")
            else None
        )
        expected_fields = {"url", "vcs_info"}
        if expected_subdirectory is not None:
            expected_fields.add("subdirectory")
        actual_subdirectory = (
            direct.get("subdirectory") if isinstance(direct, dict) else None
        )
        if (
            not isinstance(direct, dict)
            or set(direct) != expected_fields
            or not isinstance(vcs, dict)
            or vcs.get("vcs") != "git"
            or vcs.get("commit_id") != expected_commit
            or not isinstance(remote, str)
            or _repository_identity(remote)
            != _repository_identity(expected_repository)
            or (
                expected_subdirectory is None
                and actual_subdirectory is not None
            )
            or (
                expected_subdirectory is not None
                and (
                    not isinstance(actual_subdirectory, str)
                    or actual_subdirectory != expected_subdirectory
                )
            )
        ):
            raise InstallationError(
                "Installed VCS source differs from the recorded repository commit or subdirectory."
            )
    elif source.kind == "wheel":
        direct_url = direct.get("url") if isinstance(direct, dict) else None
        digest = acquisition_digest or source.digest
        if (
            not isinstance(direct, dict)
            or not isinstance(direct_url, str)
            or digest is None
            or (
                acquisition_requirement is None
                and expected_record_digest is None
            )
        ):
            raise InstallationError("Installed wheel lacks saved source proof.")
        url = urlsplit(direct_url)
        if url.scheme != "file" or url.query or url.fragment:
            raise InstallationError("Installed wheel origin is not local.")
        actual = Path(url2pathname(url.path))
        if url.netloc and url.netloc != "localhost":
            actual = Path("//" + url.netloc + str(actual))
        _validate_content_addressed_origin(source, digest, actual)
        if acquisition_requirement is not None:
            if actual != Path(acquisition_requirement) or not actual.is_file():
                raise InstallationError(
                    "Installed wheel differs from acquired wheel."
                )
            assert_no_links(actual)
        observed_digest = digest
    elif source.kind == "release-sdist":
        direct_url = direct.get("url") if isinstance(direct, dict) else None
        dir_info = direct.get("dir_info") if isinstance(direct, dict) else None
        digest = acquisition_digest or source.digest
        if (
            not isinstance(direct, dict)
            or set(direct) != {"url", "dir_info"}
            or not isinstance(direct_url, str)
            or not isinstance(dir_info, dict)
            or dir_info.get("editable") is True
            or digest is None
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise InstallationError(
                "Installed release lacks verified local-directory metadata."
            )
        url = urlsplit(direct_url)
        if url.scheme != "file" or url.fragment or url.query:
            raise InstallationError(
                "Installed release does not identify a local directory."
            )
        actual = Path(url2pathname(url.path))
        if url.netloc and url.netloc != "localhost":
            actual = Path("//" + url.netloc + str(actual))
        if acquisition_requirement is None:
            if expected_record_digest is None:
                raise InstallationError(
                    "Saved release source lacks its installed RECORD fingerprint."
                )
            _validate_content_addressed_origin(source, digest, actual)
            expected = actual
        else:
            expected = Path(acquisition_requirement)
            _validate_content_addressed_origin(source, digest, expected)
            assert_no_links(actual)
            if not actual.is_dir():
                raise InstallationError(
                    "Installed release source directory is unavailable."
                )
        if os.path.normcase(
            str(actual.resolve(strict=False))
        ) != os.path.normcase(str(expected.resolve(strict=False))):
            raise InstallationError(
                "Installed release differs from its content-addressed project."
            )
        observed_digest = digest
    elif source.kind == "index" and source.digest is not None:
        if _archive_sha256(direct) != source.digest:
            raise InstallationError(
                "Installed direct-source digest does not match the selected source."
            )
        observed_digest = source.digest
    elif source.digest is not None:
        raise InstallationError(
            "Selected archive source lacks a verifiable materialized project."
        )
    observed_source = (
        replace(source, digest=observed_digest)
        if observed_digest is not None and source.digest is None
        else source
    )
    observed_commands = []
    for command in identity.commands:
        suffix = ".exe" if os.name == "nt" else ""
        entry = target.bin_dir / (command + suffix)
        owned = (
            prefix
            / ("Scripts" if os.name == "nt" else "bin")
            / (command + suffix)
        )
        if not entry.is_file() or not owned.is_file():
            raise InstallationError("Installed console command is missing.")
        if entry.is_symlink():
            if entry.resolve() != owned.resolve():
                raise InstallationError(
                    "Console command points outside the recorded tool environment."
                )
        elif file_revision(entry) != file_revision(owned):
            raise InstallationError(
                "Console command differs from its installed package executable."
            )
        observed_commands.append(entry)
    return InstalledSnapshot(
        identity,
        value["version"],
        observed_source,
        placement,
        target,
        prefix,
        interpreter,
        tuple(observed_commands),
        distribution_record_digest=record_digest,
    )
