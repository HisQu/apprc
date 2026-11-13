"""Portable installer selection, verified acquisition, and clean-child dispatch.

This module is also serialized unchanged into Python and native frontends. Keep
its imports independent of AppRC and load uv only when dispatching an installer.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

_METADATA_LIMIT = 4 * 1024 * 1024
_DOWNLOAD_LIMIT = 256 * 1024 * 1024
RUNTIME_PAYLOAD_FILENAME = "installer-payload.zip"
_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_SHA = r"[0-9a-f]{40}"


@dataclass(frozen=True, slots=True)
class FrontendConfig:
    """Portable source identity, without the author's checkout location."""

    app_id: str
    distribution: str
    repository_url: str | None
    distribution_path: str
    project_path: str
    payload_format: str
    source_mode: str
    version: str | None
    commit: str | None


def github_repository_identity(value: str) -> tuple[str, str] | None:
    """Return a normalized credential-free GitHub owner/repository pair.

    :param value: HTTPS repository URL, optionally ending in ``.git``.
    :return: Case-insensitive identity, or ``None`` for an invalid URL.
    """
    try:
        address = urllib.parse.urlsplit(value)
        path = address.path.rstrip("/")
        parts = path[1:].split("/") if path.startswith("/") else []
        if (
            address.scheme != "https"
            or address.hostname != "github.com"
            or address.username is not None
            or address.password is not None
            or address.query
            or address.fragment
            or len(parts) != 2
        ):
            return None
        repository = parts[1].removesuffix(".git")
        if not parts[0] or not repository:
            return None
        return parts[0].casefold(), repository.casefold()
    except ValueError:
        return None


def _repository(config: FrontendConfig) -> tuple[str, str]:
    identity = github_repository_identity(config.repository_url or "")
    if identity is None:
        raise RuntimeError(
            "Source selection requires a credential-free GitHub repository URL."
        )
    return identity


def _relative_path(value: str, *, allow_dot: bool = False) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
        or (not path.parts and not (allow_dot and value == "."))
        or any(":" in part for part in path.parts)
    ):
        raise RuntimeError(
            "Installer source path is not portable and relative."
        )
    return path


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("Source metadata contains duplicate JSON keys.")
        result[key] = value
    return result


def _json_loads(value: bytes) -> Any:
    return json.loads(value, object_pairs_hook=_json_object)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _gh_api(address: str) -> list[str]:
    parsed = urllib.parse.urlsplit(address)
    if parsed.hostname == "raw.githubusercontent.com":
        owner, repository, reference, *parts = parsed.path.strip("/").split("/")
        endpoint = (
            f"repos/{owner}/{repository}/contents/"
            + "/".join(
                urllib.parse.quote(urllib.parse.unquote(part), safe="")
                for part in parts
            )
            + "?ref="
            + urllib.parse.quote(reference, safe="")
        )
        return [
            "gh",
            "api",
            endpoint,
            "-H",
            "Accept: application/vnd.github.raw",
        ]
    if parsed.hostname != "api.github.com":
        raise RuntimeError(
            "Authenticated API transport requires a GitHub API endpoint."
        )
    endpoint = parsed.path.lstrip("/") + (
        ("?" + parsed.query) if parsed.query else ""
    )
    return ["gh", "api", endpoint]


def _read_url(
    address: str, *, client: str, limit: int = _METADATA_LIMIT
) -> bytes:
    """Read bounded metadata without capturing an unlimited gh response."""
    if client == "gh":
        with subprocess.Popen(
            _gh_api(address), stdout=subprocess.PIPE
        ) as process:
            assert process.stdout is not None
            data = process.stdout.read(limit + 1)
            if len(data) > limit:
                process.kill()
            status = process.wait()
        if len(data) > limit:
            raise RuntimeError(
                "Source metadata exceeds the supported size limit."
            )
        if status:
            raise subprocess.CalledProcessError(status, _gh_api(address))
    else:
        request = urllib.request.Request(
            address,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "AppRC distribution",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError(
                "Source metadata exceeds the supported size limit."
            )
    return data


def _copy_download(stream: Any, destination: Path, limit: int) -> None:
    size = 0
    with destination.open("xb") as output:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise RuntimeError(
                    "Source download exceeds the supported size limit."
                )
            output.write(chunk)


def _download(
    address: str,
    destination: Path,
    client: str,
    *,
    limit: int = _DOWNLOAD_LIMIT,
    release: tuple[str, str] | None = None,
    allow_empty: bool = False,
) -> None:
    """Stream public/API bytes, or download an explicitly selected gh release."""
    try:
        if client == "gh" and release is not None:
            repository, tag = release
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    tag,
                    "--repo",
                    repository,
                    "--dir",
                    str(destination.parent),
                    "--pattern",
                    destination.name,
                ],
                check=True,
            )
        elif client == "gh":
            command = _gh_api(address)
            with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
                assert process.stdout is not None
                try:
                    _copy_download(process.stdout, destination, limit)
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                status = process.wait()
                if status:
                    raise subprocess.CalledProcessError(status, command)
        else:
            request = urllib.request.Request(
                address, headers={"User-Agent": "AppRC distribution"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                _copy_download(response, destination, limit)
        if (
            not destination.is_file()
            or destination.is_symlink()
            or destination.stat().st_size > limit
            or (not allow_empty and destination.stat().st_size == 0)
        ):
            raise RuntimeError(
                "Source download is empty, unsafe, or oversized."
            )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


@dataclass(frozen=True, slots=True)
class _Selection:
    mode: str
    version: str
    client: str
    forwarded: tuple[str, ...]
    package: Path | None
    explicit: bool


def _arguments(config: FrontendConfig, arguments: Sequence[str]) -> _Selection:
    mode = (
        "main"
        if config.source_mode == "main"
        else "release"
        if config.source_mode == "release"
        else "local"
    )
    version = config.version or "latest"
    client = "public"
    forwarded: list[str] = []
    package: Path | None = None
    selected = False
    client_selected = False
    values = iter(arguments)
    for argument in values:
        if argument == "--":
            forwarded.extend((argument, *values))
            break
        if argument in {"--main", "--version"}:
            if selected:
                raise RuntimeError("Specify exactly one source selector.")
            selected = True
            mode = "main" if argument == "--main" else "release"
            if argument == "--version":
                version = next(values, "")
                if re.fullmatch(_VERSION, version) is None:
                    raise RuntimeError(
                        "--version requires an exact X.Y.Z version."
                    )
        elif argument == "--github-client":
            if client_selected or next(values, "") != "gh":
                raise RuntimeError("Specify --github-client gh only once.")
            client_selected = True
            client = "gh"
        elif argument == "--source-package":
            value = next(values, "")
            if package is not None or not value or value.startswith("--"):
                raise RuntimeError("Specify one explicit source package path.")
            package = Path(value).absolute()
        elif argument in {
            "--main-ref",
            "--main-commit",
            "--release-version",
            "--source-mode",
            "--source-repository",
            "--source-commit",
        }:
            raise RuntimeError(
                "This source identity argument is reserved or unsupported."
            )
        else:
            forwarded.append(argument)
    if mode == "main" and package is not None:
        raise RuntimeError(
            "Remote main selects its package from the resolved commit."
        )
    if (
        mode == "release"
        and version != "latest"
        and re.fullmatch(_VERSION, version) is None
    ):
        raise RuntimeError(
            "Release selection requires latest or an exact X.Y.Z version."
        )
    return _Selection(
        mode, version, client, tuple(forwarded), package, selected
    )


def validate_manifest(
    document: object,
    *,
    expected_identity: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Validate a schema-1 release identity and its flat asset records.

    :param document: Decoded release manifest.
    :param expected_identity: Required ``app_id``, ``distribution``,
        ``version``, ``commit``, and ``payload_format`` values.
    :return: Asset records indexed by their safe flat filename.
    """
    required = {
        "schema_version",
        "app_id",
        "distribution",
        "version",
        "commit",
        "payload_format",
        "assets",
    }
    if (
        not isinstance(document, dict)
        or set(document) != required
        or set(expected_identity)
        != {"app_id", "distribution", "version", "commit", "payload_format"}
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or any(
            document.get(key) != value
            for key, value in expected_identity.items()
        )
        or not isinstance(document["version"], str)
        or re.fullmatch(_VERSION, document["version"]) is None
        or not isinstance(document["commit"], str)
        or re.fullmatch(_SHA, document["commit"]) is None
        or document["payload_format"] not in {"script", "zipapp"}
        or not isinstance(document["assets"], list)
    ):
        raise RuntimeError("Release manifest identity or schema is invalid.")
    result: dict[str, dict[str, object]] = {}
    for item in document["assets"]:
        if not isinstance(item, dict) or set(item) != {
            "filename",
            "size",
            "sha256",
        }:
            raise RuntimeError("Release manifest contains an invalid asset.")
        name = _asset_name(item["filename"])
        size, digest = item["size"], item["sha256"]
        if (
            name in result
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError(
                "Release manifest contains an invalid or duplicate asset."
            )
        result[name] = item
    return result


def _manifest(
    config: FrontendConfig,
    value: Any,
    selector: str,
    *,
    require_wheel: bool = True,
) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise RuntimeError(
            "Release manifest does not match the supported schema."
        )
    identity = {
        "app_id": config.app_id,
        "distribution": config.distribution,
        "version": value.get("version"),
        "commit": value.get("commit"),
        "payload_format": value.get("payload_format"),
    }
    if selector != "latest":
        identity["version"] = selector
    assets = validate_manifest(value, expected_identity=identity)
    if (
        config.version == value["version"]
        and config.commit is not None
        and config.commit != value["commit"]
    ):
        raise RuntimeError(
            "Release manifest commit differs from the authored version identity."
        )
    name = (
        "main-installer.py"
        if value["payload_format"] == "script"
        else "main-installer.pyz"
    )
    if (
        name not in assets
        or (
            value["payload_format"] == "zipapp"
            and "main-installer-requirements.txt" not in assets
        )
        or sum(item.endswith(".tar.gz") for item in assets) != 1
        or (
            sum(item.endswith(".whl") for item in assets) != 1
            if require_wheel
            else sum(item.endswith(".whl") for item in assets) > 1
        )
    ):
        raise RuntimeError(
            "Release manifest has no unique matching installer, source and wheel inventory."
        )
    return name, assets


def _execute(
    payload: Path,
    payload_format: str,
    transport: Sequence[str],
    forwarded: Sequence[str],
    *,
    uv_executable: Path | None = None,
) -> int:
    """Execute the selected authored installer using its own dependencies."""
    uv = (
        uv_executable.absolute()
        if uv_executable is not None
        else Path(importlib.import_module("uv").find_uv_bin()).absolute()
    )
    if not uv.is_file():
        raise RuntimeError("The selected uv executable is unavailable.")
    command = [
        str(uv),
        "run",
        "--no-config",
        "--no-project",
        "--python",
        ">=3.12",
    ]
    if payload_format == "script":
        command.extend(("--script", str(payload)))
    else:
        requirements = payload.with_name("main-installer-requirements.txt")
        if not requirements.is_file():
            raise RuntimeError(
                "The selected zipapp has no matched requirements file."
            )
        command.extend(
            ("--with-requirements", str(requirements), "python", str(payload))
        )
    command.extend((*transport, *forwarded))
    return subprocess.run(command, check=False).returncode


def _run_main(
    config: FrontendConfig,
    selection: _Selection,
    root: Path,
    *,
    uv_executable: Path | None = None,
) -> int:
    owner, repository = _repository(config)
    api = f"https://api.github.com/repos/{owner}/{repository}"
    resolved = _json_loads(
        _read_url(api + "/commits/main", client=selection.client)
    )
    commit = resolved.get("sha") if isinstance(resolved, dict) else None
    if not isinstance(commit, str) or re.fullmatch(_SHA, commit) is None:
        raise RuntimeError(
            "Main did not resolve to one full immutable Git commit."
        )
    installer_directory = (
        _relative_path(config.distribution_path) / "artifacts" / "installer"
    )
    name = (
        "main-installer.pyz"
        if config.payload_format == "zipapp"
        else "main-installer.py"
    )
    raw = f"https://raw.githubusercontent.com/{owner}/{repository}/{commit}/"

    def download_relative(relative: PurePosixPath) -> None:
        address = raw + "/".join(
            urllib.parse.quote(part, safe="") for part in relative.parts
        )
        _download(address, root / relative.name, selection.client)

    download_relative(installer_directory / name)
    package = root / "source.tar.gz"
    _download(api + "/tarball/" + commit, package, selection.client)
    if config.payload_format == "zipapp":
        download_relative(
            installer_directory / "main-installer-requirements.txt"
        )
    transport = [
        "--source-mode",
        "main",
        "--source-repository",
        config.repository_url or "",
        "--source-commit",
        commit,
        "--source-package",
        str(package),
    ]
    if selection.client == "gh":
        transport.extend(("--github-client", "gh"))
    return _execute(
        root / name,
        config.payload_format,
        transport,
        selection.forwarded,
        uv_executable=uv_executable,
    )


def _asset_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or any(character in value for character in ("/", "\\", "\x00", ":"))
    ):
        raise RuntimeError("Release inventory contains an unsafe asset name.")
    return value


def _verify(path: Path, expected: dict[str, Any]) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != expected["size"]
        or _sha256_file(path) != expected["sha256"]
    ):
        raise RuntimeError(
            "Selected release asset differs from its manifest size or SHA-256."
        )


def _asset_url(
    address: object, repository: tuple[str, str], tag: str, name: str
) -> str:
    if not isinstance(address, str):
        raise RuntimeError("Release asset has no download URL.")
    parsed = urllib.parse.urlsplit(address)
    expected = (
        f"/{repository[0]}/{repository[1]}/releases/download/{tag}/{name}"
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "github.com"
        or parsed.query
        or parsed.fragment
        or urllib.parse.unquote(parsed.path) != expected
    ):
        raise RuntimeError(
            "Release asset URL differs from the selected repository, tag or filename."
        )
    return address


def _release_payload(
    config: FrontendConfig, selection: _Selection, root: Path
) -> tuple[Path, str, Path]:
    repository = _repository(config)
    identity = "/".join(repository)
    api = f"https://api.github.com/repos/{identity}"
    suffix = (
        "/releases/latest"
        if selection.version == "latest"
        else "/releases/tags/v" + selection.version
    )
    release = _json_loads(_read_url(api + suffix, client=selection.client))
    if not isinstance(release, dict) or release.get("draft") is not False:
        raise RuntimeError("Selected release is unavailable or unpublished.")
    tag = release.get("tag_name")
    if (
        not isinstance(tag, str)
        or not tag.startswith("v")
        or re.fullmatch(_VERSION, tag[1:]) is None
        or (selection.version != "latest" and tag != "v" + selection.version)
    ):
        raise RuntimeError(
            "Selected release tag differs from the requested version."
        )
    if not isinstance(release.get("assets"), list):
        raise RuntimeError("Selected release has no asset inventory.")
    assets: dict[str, Any] = {}
    for asset in release["assets"]:
        if not isinstance(asset, dict):
            raise RuntimeError(
                "Selected release contains an invalid asset entry."
            )
        name = _asset_name(asset.get("name"))
        if (
            name in assets
            or type(asset.get("size")) is not int
            or asset["size"] < 0
        ):
            raise RuntimeError(
                "Selected release contains a duplicate or invalid asset."
            )
        address = _asset_url(
            asset.get("browser_download_url"), repository, tag, name
        )
        assets[name] = {**asset, "browser_download_url": address}
    manifest_asset = assets.get("release-manifest.json")
    if manifest_asset is None or manifest_asset["size"] > _METADATA_LIMIT:
        raise RuntimeError("Selected release has no bounded release manifest.")
    manifest_path = root / "release-manifest.json"
    _download(
        manifest_asset["browser_download_url"],
        manifest_path,
        selection.client,
        limit=_METADATA_LIMIT,
        release=(identity, tag),
    )
    if manifest_path.stat().st_size != manifest_asset["size"]:
        raise RuntimeError(
            "Release manifest size differs from the selected asset."
        )
    manifest = _json_loads(manifest_path.read_bytes())
    payload_name, expected = _manifest(config, manifest, tag[1:])
    if set(expected) != set(assets) - {"release-manifest.json"}:
        raise RuntimeError("Release manifest and GitHub inventories differ.")
    if any(
        assets[name]["size"] != entry["size"]
        for name, entry in expected.items()
    ):
        raise RuntimeError("Release inventory sizes differ from the manifest.")
    package_name = next(name for name in expected if name.endswith(".tar.gz"))
    names = [payload_name, package_name]
    if manifest["payload_format"] == "zipapp":
        names.append("main-installer-requirements.txt")
    if RUNTIME_PAYLOAD_FILENAME in expected:
        names.append(RUNTIME_PAYLOAD_FILENAME)
    for name in names:
        destination = root / name
        if name == package_name and selection.package is not None:
            _stage_package(selection.package, destination, expected[name])
        else:
            _download(
                assets[name]["browser_download_url"],
                destination,
                selection.client,
                release=(identity, tag),
                limit=expected[name]["size"],
                allow_empty=True,
            )
            _verify(destination, expected[name])
    return root / payload_name, manifest["payload_format"], root / package_name


def _stage_package(
    source: Path, destination: Path, expected: dict[str, Any]
) -> None:
    _verify(source, expected)
    with source.open("rb") as stream:
        _copy_download(stream, destination, expected["size"])
    _verify(destination, expected)


def _embedded_payload(
    config: FrontendConfig, selection: _Selection, payload: bytes, root: Path
) -> tuple[Path, str, Path]:
    with ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) != len({item.filename for item in entries}):
            raise RuntimeError("Embedded release contains duplicate members.")
        by_name = {_asset_name(item.filename): item for item in entries}
        if any(item.is_dir() for item in entries):
            raise RuntimeError("Embedded release contains directory members.")
        manifest_entry = by_name.get("release-manifest.json")
        if manifest_entry is None or manifest_entry.file_size > _METADATA_LIMIT:
            raise RuntimeError(
                "Embedded release has no bounded inner manifest."
            )
        manifest_bytes = archive.read(manifest_entry)
        manifest = _json_loads(manifest_bytes)
        if (
            config.commit is None
            or not isinstance(manifest, dict)
            or not isinstance(manifest.get("version"), str)
        ):
            raise RuntimeError(
                "Embedded release manifest lacks an exact authored identity."
            )
        if manifest.get("commit") != config.commit:
            raise RuntimeError(
                "Embedded release commit differs from the authored identity."
            )
        if config.version not in {None, "latest", manifest["version"]}:
            raise RuntimeError(
                "Embedded release version differs from the authored identity."
            )
        name, expected = _manifest(
            config, manifest, manifest["version"], require_wheel=False
        )
        if manifest["payload_format"] != config.payload_format:
            raise RuntimeError(
                "Embedded payload format differs from its authored identity."
            )
        package_name = next(
            item for item in expected if item.endswith(".tar.gz")
        )
        required = {name, package_name, "release-manifest.json"}
        if manifest["payload_format"] == "zipapp":
            required.add("main-installer-requirements.txt")
        if RUNTIME_PAYLOAD_FILENAME in expected:
            required.add(RUNTIME_PAYLOAD_FILENAME)
        if set(by_name) != required:
            raise RuntimeError(
                "Embedded release members differ from the original installer/source inventory."
            )
        (root / "release-manifest.json").write_bytes(manifest_bytes)
        for asset_name in required - {"release-manifest.json"}:
            destination = root / asset_name
            with archive.open(by_name[asset_name]) as stream:
                _copy_download(
                    stream, destination, expected[asset_name]["size"]
                )
            _verify(destination, expected[asset_name])
        if selection.package is not None:
            # > An explicit local package may replace only the identical release source.
            destination = root / package_name
            destination.unlink()
            _stage_package(
                selection.package, destination, expected[package_name]
            )
    return root / name, manifest["payload_format"], root / package_name


def run_installer(
    config: FrontendConfig,
    arguments: Sequence[str],
    *,
    embedded_payload: bytes | None = None,
    local_installer: Path | None = None,
    uv_executable: Path | None = None,
) -> int:
    """Select and verify an authored installer before running its clean child.

    :param config: Portable application and default-source identity.
    :param arguments: Installer arguments, including public source selectors.
    :param embedded_payload: Flat ZIP of original release inputs and inner manifest.
    :param local_installer: Actual adjacent developer installer; never an author root.
    :param uv_executable: Explicit ordinary-entry uv executable; native use resolves
        uv lazily through its public Python API.
    :return: Child exit status, or 2 for a refused selection/acquisition.
    """
    try:
        if config.payload_format not in {"script", "zipapp"}:
            raise RuntimeError("Unsupported installer payload format.")
        _relative_path(config.distribution_path)
        _relative_path(config.project_path, allow_dot=True)
        selection = _arguments(config, arguments)
        if (
            not selection.explicit
            and embedded_payload is None
            and local_installer is not None
        ):
            payload = local_installer.absolute()
            if not payload.is_file():
                raise RuntimeError(
                    "The generated local installer is missing; generate repository artifacts first."
                )
            transport: list[str] = []
            if selection.package is not None:
                transport.extend(("--source-package", str(selection.package)))
            if selection.client == "gh":
                transport.extend(("--github-client", "gh"))
            return _execute(
                payload,
                config.payload_format,
                transport,
                selection.forwarded,
                uv_executable=uv_executable,
            )
        with tempfile.TemporaryDirectory(prefix="apprc-source-") as temporary:
            root = Path(temporary).resolve(strict=True)
            os.chmod(root, 0o700)
            if not selection.explicit and embedded_payload is not None:
                payload, payload_format, package = _embedded_payload(
                    config, selection, embedded_payload, root
                )
            elif selection.mode == "main":
                return _run_main(
                    config, selection, root, uv_executable=uv_executable
                )
            elif selection.mode == "release":
                payload, payload_format, package = _release_payload(
                    config, selection, root
                )
            else:
                raise RuntimeError(
                    "No adjacent authored installer was supplied for this developer entry."
                )
            transport = ["--source-package", str(package)]
            if selection.client == "gh":
                transport.extend(("--github-client", "gh"))
            return _execute(
                payload,
                payload_format,
                transport,
                selection.forwarded,
                uv_executable=uv_executable,
            )
    except (
        OSError,
        ValueError,
        RuntimeError,
        ImportError,
        BadZipFile,
        urllib.error.URLError,
        subprocess.SubprocessError,
    ) as error:
        print(f"AppRC installer frontend failed: {error}", file=sys.stderr)
        return 2
