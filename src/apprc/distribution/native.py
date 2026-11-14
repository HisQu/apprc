"""Explicit authoring-time compilation of pinned upstream PyApp frontends.

Importing this module or generating ordinary Python artifacts never invokes Rust.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tarfile
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Literal, NotRequired, TypedDict
from urllib.parse import urlsplit, urlunsplit

from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    set_windows_private_acl,
    windows_acl_is_private,
)

UV_VERSION = "0.13.6"
PYAPP_VERSION = "0.31.0"
PYAPP_SOURCE_SHA256 = (
    "16bc883dd936584eef8d0d838feef3e839c340f201f36cc05eb810f29df92c22"
)
PYAPP_SOURCE_URL = f"https://github.com/ofek/pyapp/releases/download/v{PYAPP_VERSION}/source.tar.gz"
NativeTarget = Literal["x86_64-unknown-linux-gnu", "x86_64-pc-windows-msvc"]
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+")
_SECRET_KEY = re.compile(
    r"TOKEN|PASSWORD|SECRET|CREDENTIAL|CERT|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|AUTH",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NativeArtifact:
    """A finished executable and its workspace-owned compilation evidence."""

    path: Path
    target: NativeTarget
    size: int
    sha256: str
    report: Path


class _ArtifactInfo(TypedDict):
    path: str
    size: int
    sha256: str
    machine: int
    format: str
    optional_header_magic: NotRequired[int]
    characteristics: NotRequired[int]
    subsystem: NotRequired[int]


def _create_file(path: Path, *, mode: int = 0o600) -> BinaryIO:
    """Create private bytes exclusively without following a destination link."""
    assert_no_links(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if os.name == "nt":
        flags |= os.O_BINARY
        if not windows_acl_is_private(path.parent):
            raise PermissionError(
                "Native output requires a private parent directory."
            )
    descriptor = os.open(path, flags, mode)
    try:
        return os.fdopen(descriptor, "wb")
    except BaseException:
        os.close(descriptor)
        raise


def _validate_pip_args(value: str) -> None:
    """Keep static upstream pip settings free of URL credentials and tokens."""
    for token in shlex.split(value):
        option = token.split("=", 1)[0]
        if option.startswith("-") and _SECRET_KEY.search(option):
            raise ValueError(
                "Credentials must not be included in static pip arguments."
            )
    for match in _URL.finditer(value):
        url = urlsplit(match.group())
        if (
            url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Static pip URLs must not include user information, queries or fragments."
            )


def _diagnostics(text: str, environment: Mapping[str, str]) -> str:
    """Retain compiler output without copying ambient credentials into reports."""
    for key, value in environment.items():
        if value and _SECRET_KEY.search(key):
            text = text.replace(value, "[redacted]")

    def redact_url(match: re.Match[str]) -> str:
        try:
            url = urlsplit(match.group())
            return urlunsplit(
                (url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", "")
            )
        except ValueError:
            return "[redacted URL]"

    return _URL.sub(redact_url, text)


def _artifact_info(path: Path, target: NativeTarget) -> _ArtifactInfo:
    """Inspect final ELF or PE bytes without executing either target."""
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = stream.read(64)
        if target == "x86_64-pc-windows-msvc":
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError(
                    "Native Windows artifact has no complete DOS header."
                )
            offset = struct.unpack_from("<I", header, 0x3C)[0]
            if offset < 64 or offset + 24 > size:
                raise ValueError(
                    "Native Windows artifact has an invalid PE offset."
                )
            stream.seek(offset)
            pe = stream.read(24)
            machine = struct.unpack_from("<H", pe, 4)[0]
            optional_size, characteristics = struct.unpack_from("<HH", pe, 20)
            if (
                pe[:4] != b"PE\0\0"
                or optional_size < 70
                or offset + 24 + optional_size > size
            ):
                raise ValueError(
                    "Native Windows artifact has an invalid PE header."
                )
            optional = stream.read(optional_size)
            magic = struct.unpack_from("<H", optional)[0]
            subsystem = struct.unpack_from("<H", optional, 68)[0]
            if (
                machine != 0x8664
                or magic != 0x20B
                or not characteristics & 0x0002
                or characteristics & 0x2000
                or subsystem != 3
            ):
                raise ValueError(
                    "Expected a PE64 AMD64 console executable, not a DLL."
                )
            info: _ArtifactInfo = {
                "path": str(path),
                "size": size,
                "sha256": "",
                "machine": machine,
                "format": "PE",
                "optional_header_magic": magic,
                "characteristics": characteristics,
                "subsystem": subsystem,
            }
        else:
            if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01":
                raise ValueError("Expected a little-endian ELF64 artifact.")
            elf_type, machine = struct.unpack_from("<HH", header, 16)
            if elf_type not in (2, 3) or machine != 62:
                raise ValueError("Expected an x86_64 ELF executable.")
            info = {
                "path": str(path),
                "size": size,
                "sha256": "",
                "machine": machine,
                "format": "ELF",
            }
        stream.seek(0)
        info["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    return info


class NativeFrontendBuilder:
    """Compile sequential frontend roles in one exclusively owned workspace.

    The workspace must not exist. Source acquisition is lazy and authenticated;
    upstream source and Cargo artifacts are reused across calls to :meth:`build`.
    The caller owns serialization of this builder and of any explicitly shared
    ``CARGO_TARGET_DIR``. No cross-process cache or runtime cleanup is introduced.

    :param workspace: New private operation directory, not a release asset directory.
    :param bootstrap_name: Stable app-specific Python project/bootstrap namespace.
    :param python_version: Upstream Python major/minor selection.
    :param pip_extra_args: Credential-free static upstream pip flags.
    :param environment: Authoring environment; copied at construction, never reported
        wholesale. When omitted, the current environment is copied. Relative tool
        and Cargo paths are interpreted from the construction directory.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        bootstrap_name: str = "apprc-native-manager",
        python_version: str = "3.14",
        pip_extra_args: str = "",
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", bootstrap_name
        ):
            raise ValueError("bootstrap_name must be a Python project name.")
        if not re.fullmatch(r"[0-9]+\.[0-9]+", python_version):
            raise ValueError(
                "python_version must contain a major and minor version."
            )
        _validate_pip_args(pip_extra_args)
        self.workspace = workspace.expanduser().absolute()
        self._authoring_directory = Path.cwd()
        self._environment = dict(
            os.environ if environment is None else environment
        )
        self._environment = {
            key: value
            for key, value in self._environment.items()
            if not key.startswith("PYAPP_")
        }
        self._environment["RUSTUP_AUTO_INSTALL"] = "0"
        self._bootstrap_name = re.sub(r"[-_.]+", "-", bootstrap_name).lower()
        self._python_version = python_version
        self._pip_extra_args = pip_extra_args
        bootstrap_inputs = {
            "pyapp_version": PYAPP_VERSION,
            "pyapp_source_sha256": PYAPP_SOURCE_SHA256,
            "python_version": python_version,
            "management_requirements": (),
            "uv_version": UV_VERSION,
            "pip_extra_args": pip_extra_args,
        }
        digest = hashlib.sha256(
            json.dumps(
                bootstrap_inputs, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self._bootstrap_version = f"{PYAPP_VERSION}+{digest}"
        self._source: Path | None = None
        self._cargo_lock: bytes | None = None
        self._build_count = 0
        assert_no_links(self.workspace)
        self.workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
        if os.name == "nt":
            set_windows_private_acl(self.workspace)

    @property
    def bootstrap_version(self) -> str:
        """Return the stable identity of bootstrap dependencies, not dispatcher bytes."""
        return self._bootstrap_version

    def _acquire_source(self) -> Path:
        if self._source is not None:
            return self._source
        asset = self.workspace / "source.tar.gz"
        request = urllib.request.Request(
            PYAPP_SOURCE_URL,
            headers={"User-Agent": "AppRC native frontend builder"},
        )
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            _create_file(asset) as output,
        ):
            shutil.copyfileobj(response, output)
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != PYAPP_SOURCE_SHA256:
            raise ValueError("Pinned PyApp source SHA256 mismatch.")
        extracted = self.workspace / "source"
        extracted.mkdir(mode=0o700)
        with tarfile.open(asset, "r:gz") as archive:
            seen: set[PurePosixPath] = set()
            for member in archive:
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or PureWindowsPath(member.name).drive
                    or ".." in relative.parts
                    or "\\" in member.name
                    or relative in seen
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError(
                        f"Unsafe PyApp source member: {member.name}"
                    )
                seen.add(relative)
                if not relative.parts and member.isdir():
                    continue
                output_path = extracted.joinpath(*relative.parts)
                if member.isdir():
                    output_path.mkdir(parents=True, mode=0o700, exist_ok=True)
                else:
                    output_path.parent.mkdir(
                        parents=True, mode=0o700, exist_ok=True
                    )
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError(
                            "PyApp source member has no regular file content."
                        )
                    with stream, _create_file(output_path) as output:
                        shutil.copyfileobj(stream, output)
        roots = [
            path.parent
            for path in extracted.rglob("Cargo.toml")
            if (path.parent / "build.rs").is_file()
        ]
        if len(roots) != 1 or not (roots[0] / "Cargo.lock").is_file():
            raise ValueError(
                "Expected one upstream PyApp project retaining Cargo.lock."
            )
        self._cargo_lock = (roots[0] / "Cargo.lock").read_bytes()
        proof = {
            "version": PYAPP_VERSION,
            "source_url": PYAPP_SOURCE_URL,
            "sha256": digest,
            "cargo_lock_sha256": hashlib.sha256(self._cargo_lock).hexdigest(),
        }
        with _create_file(self.workspace / "source-proof.json") as output:
            output.write(json.dumps(proof, indent=2).encode())
        self._source = roots[0]
        return self._source

    def _run(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
        observations: list[dict[str, object]],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        observation: dict[str, object] = {
            "command": [
                _diagnostics(argument, environment) for argument in command
            ],
        }
        observations.append(observation)
        try:
            result = subprocess.run(
                command,
                env=environment,
                cwd=cwd,
                text=True,
                errors="replace",
                capture_output=True,
                check=False,
                timeout=1800,
            )
        except subprocess.TimeoutExpired as exc:
            observation["timed_out"] = True
            observation["stdout"] = _diagnostics(
                (exc.stdout or b"").decode(errors="replace"), environment
            )
            observation["stderr"] = _diagnostics(
                (exc.stderr or b"").decode(errors="replace"), environment
            )
            raise RuntimeError(
                "Native compiler command exceeded 1800 seconds."
            ) from exc
        observation.update(
            returncode=result.returncode,
            stdout=_diagnostics(result.stdout, environment),
            stderr=_diagnostics(result.stderr, environment),
        )
        if check and result.returncode:
            raise RuntimeError(
                "Native compiler command failed; see the workspace build report."
            )
        return result

    def build(
        self,
        *,
        target: NativeTarget,
        destination: Path,
        runtime_archive: Path,
        entrypoint: str,
    ) -> NativeArtifact:
        """Compile PyApp with one fixed loader for a verified SDK ZIP.

        :param target: Supported GNU Linux or MSVC Windows x86_64 target.
        :param destination: New operation-cache executable path.
        :param runtime_archive: Ordinary ZIP containing the SDK, binding, and snapshot.
        :param entrypoint: Python module executed by the fixed loader.
        :return: Finished artifact metadata and a report inside the workspace.
        """
        if target not in ("x86_64-unknown-linux-gnu", "x86_64-pc-windows-msvc"):
            raise ValueError(f"Unsupported native target: {target}")
        if not all(part.isidentifier() for part in entrypoint.split(".")):
            raise ValueError("Native entrypoint must be a Python module name.")
        destination = destination.expanduser().absolute()
        runtime_archive = runtime_archive.expanduser().absolute()
        assert_no_links(destination)
        assert_no_links(runtime_archive)
        if destination.exists():
            raise FileExistsError(destination)
        archive_bytes = runtime_archive.read_bytes()
        archive_digest = hashlib.sha256(archive_bytes).hexdigest()
        from zipfile import ZipFile

        with ZipFile(runtime_archive) as archive:
            requirements = archive.read("bootstrap-requirements.txt")
        requirements_text = requirements.decode("utf-8")
        requirement_lines = tuple(
            line.strip()
            for line in requirements_text.splitlines()
            if line.strip()
        )
        uv_lines = [
            line
            for line in requirement_lines
            if re.match(r"(?i)^uv(?:\[|[<=>!~; ]|$)", line)
        ]
        if uv_lines != [f"uv=={UV_VERSION}"]:
            raise ValueError(
                "Native SDK archive must contain exactly one pinned uv requirement."
            )
        bootstrap_inputs = {
            "pyapp_version": PYAPP_VERSION,
            "pyapp_source_sha256": PYAPP_SOURCE_SHA256,
            "python_version": self._python_version,
            "requirements": requirement_lines,
            "uv_version": UV_VERSION,
            "pip_extra_args": self._pip_extra_args,
        }
        digest = hashlib.sha256(
            json.dumps(
                bootstrap_inputs, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self._bootstrap_version = f"{PYAPP_VERSION}+{digest}"
        self._build_count += 1
        attempt = self.workspace / f"build-{self._build_count:04d}"
        assert_no_links(attempt)
        attempt.mkdir(mode=0o700)
        report_path = attempt / "report.json"
        observations: list[dict[str, object]] = []
        report: dict[str, object] = {
            "target": target,
            "bootstrap_name": self._bootstrap_name,
            "bootstrap_version": self.bootstrap_version,
            "runtime_archive_size": len(archive_bytes),
            "runtime_archive_sha256": archive_digest,
            "commands": observations,
        }
        environment = self._environment.copy()
        try:
            source = self._acquire_source()
            inputs = source / "apprc-inputs" / attempt.name
            inputs.mkdir(parents=True, mode=0o700)
            stub = (
                "import hashlib\n"
                "import os\n"
                "import runpy\n"
                "import sys\n"
                "from pathlib import Path\n"
                "executable = Path(os.environ['PYAPP']).resolve()\n"
                "with executable.open('rb') as stream:\n"
                f"    stream.seek(-{len(archive_bytes)}, os.SEEK_END)\n"
                "    payload = stream.read()\n"
                f"if len(payload) != {len(archive_bytes)}:\n"
                "    raise RuntimeError('AppRC runtime archive size mismatch')\n"
                f"if hashlib.sha256(payload).hexdigest() != {archive_digest!r}:\n"
                "    raise RuntimeError('AppRC runtime archive SHA256 mismatch')\n"
                "sys.path.insert(0, str(executable))\n"
                f"runpy.run_module({entrypoint!r}, init_globals={{'_APPRC_ARCHIVE_SHA256': {archive_digest!r}, '_APPRC_ARCHIVE_SIZE': {len(archive_bytes)}}}, run_name='__main__', alter_sys=True)\n"
            )
            with _create_file(inputs / "loader.py") as output:
                output.write(stub.encode())
            with _create_file(inputs / "requirements.txt") as output:
                output.write(requirements)
            search_path = environment.get("PATH", os.defpath)
            cargo = shutil.which("cargo", path=search_path)
            rustc = shutil.which("rustc", path=search_path)
            if cargo is None or rustc is None:
                raise FileNotFoundError(
                    "Provision the Rust authoring toolchain before native builds."
                )
            cargo = str(Path(cargo).absolute())
            rustc = str(Path(rustc).absolute())
            if (
                "RUSTUP_TOOLCHAIN" not in environment
                and Path(cargo).resolve().stem == "rustup"
            ):
                rustup = str(
                    Path(cargo).with_name(
                        "rustup.exe" if os.name == "nt" else "rustup"
                    )
                )
                selected = self._run(
                    [rustup, "show", "active-toolchain"],
                    environment=environment,
                    cwd=self._authoring_directory,
                    observations=observations,
                ).stdout.split()
                if not selected:
                    raise RuntimeError(
                        "Rustup did not report the selected authoring toolchain."
                    )
                environment["RUSTUP_TOOLCHAIN"] = selected[0]
            configured_target_directory = environment.get("CARGO_TARGET_DIR")
            if configured_target_directory is None:
                target_directory = self.workspace / "cargo-target"
                environment["CARGO_TARGET_DIR"] = str(target_directory)
            else:
                target_directory = Path(configured_target_directory)
                if not target_directory.is_absolute():
                    target_directory = (
                        self._authoring_directory / target_directory
                    )
                target_directory = target_directory.absolute()
            settings = {
                "PYAPP_PROJECT_NAME": self._bootstrap_name,
                "PYAPP_PROJECT_VERSION": self.bootstrap_version,
                "PYAPP_PYTHON_VERSION": self._python_version,
                "PYAPP_PROJECT_DEPENDENCY_FILE": str(
                    (inputs / "requirements.txt").relative_to(source)
                ),
                "PYAPP_EXEC_SCRIPT": str(
                    (inputs / "loader.py").relative_to(source)
                ),
                "PYAPP_PASS_LOCATION": "1",
                "PYAPP_SELF_COMMAND": "none",
                "PYAPP_IS_GUI": "0",
                "PYAPP_UV_ENABLED": "0",
                "PYAPP_PIP_EXTRA_ARGS": self._pip_extra_args,
            }
            environment.update(settings)
            environment["CARGO_TARGET_DIR"] = str(target_directory)
            environment["XWIN_ARCH"] = "x86_64"
            report["settings"] = settings
            report["cargo_target_directory"] = str(target_directory)
            self._run(
                [rustc, "-vV"],
                environment=environment,
                cwd=source,
                observations=observations,
            )
            self._run(
                [cargo, "--version"],
                environment=environment,
                cwd=source,
                observations=observations,
            )
            windows = target == "x86_64-pc-windows-msvc"
            if windows:
                self._run(
                    [cargo, "xwin", "--version"],
                    environment=environment,
                    cwd=source,
                    observations=observations,
                )
            command = [
                cargo,
                *(["xwin"] if windows else []),
                "build",
                "--release",
                "--locked",
                "--target",
                target,
            ]
            self._run(
                command,
                environment=environment,
                cwd=source,
                observations=observations,
            )
            if (source / "Cargo.lock").read_bytes() != self._cargo_lock:
                raise ValueError(
                    "Native compilation changed the pinned upstream Cargo.lock."
                )
            if windows:
                self._observe_windows_tools(
                    environment, source, observations, report
                )
            compiled = (
                target_directory
                / target
                / "release"
                / ("pyapp.exe" if windows else "pyapp")
            )
            assert_no_links(destination)
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with (
                compiled.open("rb") as input_stream,
                _create_file(destination, mode=0o700) as output,
            ):
                try:
                    shutil.copyfileobj(input_stream, output)
                    output.write(archive_bytes)
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
            try:
                info = _artifact_info(destination, target)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
            report["artifact"] = info
            return NativeArtifact(
                destination, target, info["size"], info["sha256"], report_path
            )
        except BaseException as exc:
            report["error"] = _diagnostics(str(exc), environment)
            raise
        finally:
            with _create_file(report_path) as output:
                output.write(json.dumps(report, indent=2).encode())

    def _observe_windows_tools(
        self,
        environment: Mapping[str, str],
        source: Path,
        observations: list[dict[str, object]],
        report: dict[str, object],
    ) -> None:
        cache_setting = environment.get("XWIN_CACHE_DIR")
        cache = (
            Path(cache_setting)
            if cache_setting
            else Path(
                environment.get(
                    "XDG_CACHE_HOME",
                    str(
                        Path(environment.get("HOME", str(Path.home())))
                        / ".cache"
                    ),
                )
            )
            / "cargo-xwin"
        )
        if not cache.is_absolute():
            cache = source / cache
        report["xwin_cache"] = {
            "location": str(cache),
            "location_basis": "XWIN_CACHE_DIR"
            if cache_setting
            else "inferred from authoring cache home",
            "exists": cache.is_dir(),
            "observed_directories": sorted(
                str(path.relative_to(cache))
                for path in cache.rglob("*")
                if path.is_dir()
            )
            if cache.is_dir()
            else [],
        }
        search_path = os.pathsep.join(
            (environment.get("PATH", os.defpath), str(cache))
        )
        tools: dict[str, str | None] = {}
        for name in ("clang-cl", "llvm-lib", "llvm-ar", "lld-link"):
            tool = shutil.which(name, path=search_path)
            tools[name] = tool
            if tool is not None:
                self._run(
                    [tool, "--version"],
                    environment=environment,
                    cwd=source,
                    observations=observations,
                    check=False,
                )
        report["llvm_tools"] = tools
