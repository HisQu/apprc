"""Explicit native release assembly; ordinary artifact generation stays Rust-free."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from packaging.utils import parse_wheel_filename


from apprc.definition.installation import InstallationSource
from apprc.distribution._frontend import RUNTIME_PAYLOAD_FILENAME
from apprc.distribution.bundles import _target_tags, compile_wheel_bundle
from apprc.distribution.models import (
    CompiledWheelBundle,
    DistributionSpec,
    PayloadTree,
)
from apprc.distribution.native import (
    NativeArtifact,
    NativeFrontendBuilder,
    NativeTarget,
)
from apprc.distribution.rendering import (
    build_main_installer,
    render_installer_dispatcher,
)
from apprc.distribution.runtime.acquisition import installation_source
from apprc.distribution.runtime.bundles import (
    _root_entry,
    _validate_entries,
    _validate_graph,
)
from apprc.distribution.runtime.payloads import (
    _PayloadSources,
    _payload_identity,
)
from apprc.distribution.standalone import (
    MANAGEMENT_REQUIREMENTS,
    _deterministic_zip,
)
from apprc.user_files.app_home.locations import assert_no_links


@dataclass(frozen=True, slots=True)
class NativeDistribution:
    """Finished native files and matching standalone payload assets for publication."""

    frontends: tuple[NativeArtifact, ...]
    payload_files: tuple[Path, ...]


def _release_source(spec: DistributionSpec) -> InstallationSource:
    """Require portable immutable release provenance before native authoring."""
    if (
        spec.source_mode != "release"
        or spec.release_version != spec.metadata.version
        or spec.release_commit is None
        or spec.release_digest is None
    ):
        raise ValueError(
            "Bundled native release assembly requires its exact release-sdist identity."
        )
    source = installation_source(spec)
    address = urlsplit(source.requirement)
    if (
        address.scheme != "https"
        or address.hostname is None
        or address.username is not None
        or address.password is not None
    ):
        raise ValueError(
            "Bundled release sources require credential-free HTTPS."
        )
    return source


def _compatible_bundle(
    bundle: CompiledWheelBundle,
    targets: tuple[NativeTarget, ...],
    *,
    python_version: str,
) -> None:
    """Require one portable locked bundle to support every advertised native target."""
    for target in targets:
        allowed = _target_tags(target, python_version)
        for wheel in bundle.wheels:
            if not parse_wheel_filename(wheel.filename)[3] & allowed:
                raise ValueError(
                    f"Bundled wheel {wheel.filename} does not support {target}; "
                    "build a compatible declared-backend wheel before publication."
                )


def build_runtime_payload(
    spec: DistributionSpec,
    bundle: CompiledWheelBundle,
    *,
    targets: tuple[NativeTarget, ...],
    linux_launcher: bytes | None = None,
) -> bytes:
    """Create the single retained archive, without another installation authority.

    Its whole digest is embedded in the authored installer and covered by the
    native inner manifest. Wheel digests/provenance stay in the generated inventory.

    :param spec: Immutable original release source and application identity.
    :param bundle: Compiled locked root/dependency wheels.
    :param targets: Exact platforms supported by this payload's wheels.
    :param linux_launcher: Optional finished owned Linux launch executable.
    :return: Deterministic portable ZIP bytes, reused unchanged by saved repair.
    """
    origin = _release_source(spec)
    runtime_python = spec.metadata.runtime_python
    if runtime_python is None:
        raise ValueError(
            "Native runtime payload requires an explicit "
            "tool.apprc.distribution.runtime-python minor, such as '3.13'."
        )
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("Runtime payload requires unique native targets.")
    if linux_launcher is not None and "x86_64-unknown-linux-gnu" not in targets:
        raise ValueError("A Linux launcher requires a Linux payload target.")
    _validate_entries(bundle.wheels)
    _validate_graph(bundle.source, bundle.wheels)
    _root_entry(
        bundle.source, spec.metadata.identity.distribution, bundle.wheels
    )
    _compatible_bundle(bundle, targets, python_version=runtime_python)
    sources = _PayloadSources(origin, bundle.source, targets)
    entries = {
        "sources.json": (
            json.dumps(asdict(sources), sort_keys=True) + "\n"
        ).encode(),
        "inventory.json": (
            json.dumps(
                [asdict(wheel) for wheel in bundle.wheels], sort_keys=True
            )
            + "\n"
        ).encode(),
        "runtime-requirements.txt": "".join(
            value + "\n" for value in bundle.source.runtime_requirements
        ).encode(),
    }
    for wheel in bundle.wheels:
        path = bundle.directory / wheel.filename
        assert_no_links(path)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != wheel.digest:
            raise ValueError(
                f"Compiled wheel changed before payload assembly: {wheel.filename}."
            )
        entries[wheel.filename] = content
    if linux_launcher is not None:
        entries["launch"] = linux_launcher
    return _deterministic_zip(entries.items())


def render_native_launcher(spec: DistributionSpec) -> bytes:
    """Render identity-only dispatch through the unchanged saved-management program.

    The executable contains no installer, wheel payload or removal implementation
    of its own. It uses the canonical program and its existing authority/locator.

    :param spec: Application identity and selected registered launch command.
    :return: Python input for the explicit native builder.
    """
    program = (
        files("apprc.distribution")
        .joinpath("runtime", "saved_management.py")
        .read_bytes()
    )
    binding = json.dumps(
        {
            "app_id": spec.metadata.identity.app_id,
            "command": spec.metadata.launcher_command
            or spec.metadata.identity.commands[0],
            "base_python": None,
        },
        sort_keys=True,
    )
    encoded = base64.b64encode(program).decode("ascii")
    return (
        '"""Native identity-only saved launch dispatch."""\n'
        "import base64, os, subprocess, sys, tempfile\nfrom pathlib import Path\n"
        "with tempfile.TemporaryDirectory(prefix='apprc-launch-') as temporary:\n"
        "    root = Path(temporary)\n"
        "    program = root / 'management.py'\n"
        f"    program.write_bytes(base64.b64decode({encoded!r}, validate=True))\n"
        f"    program.with_name('management.json').write_text({binding!r}, encoding='utf-8')\n"
        "    arguments = list(sys.argv[1:])\n"
        "    adjacent = Path(os.environ['PYAPP']).absolute().parent\n"
        "    if '--directory' not in arguments and not any(arg.startswith('--directory=') for arg in arguments) and (adjacent / 'installation.json').is_file():\n"
        "        arguments = ['--directory', str(adjacent), *arguments]\n"
        "    raise SystemExit(subprocess.run([sys.executable, '-I', str(program), 'launch', *arguments], check=False).returncode)\n"
    ).encode("utf-8")


def build_native_installers(
    spec: DistributionSpec,
    payload: PayloadTree,
    *,
    source_package: Path,
    uv: Path,
    workspace: Path,
    targets: tuple[NativeTarget, ...] = (
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    ),
    extras: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
) -> NativeDistribution:
    """Build an immutable bundled release: launchers, inner payload, then installers.

    Only this explicit API invokes repository builds and Rust. The returned
    standalone assets use the inner manifest contract, while the caller's existing
    release staging creates the outer manifest after all native files are finished.
    Windows launch bytes are compiled but never published as owned saved launchers.

    :param spec: Release-sdist identity matching the exact application version.
    :param payload: Ordinary authored lifecycle modules/resources, without wheels.
    :param source_package: Original release SDIST whose digest is in ``spec``.
    :param uv: Explicit authoring uv executable for locked exports and wheel builds.
    :param workspace: New private ignored build workspace, never a source directory.
    :param targets: Requested pinned native targets, built serially.
    :param extras: Intended application runtime extras, never development groups.
    :param environment: Existing authenticated authoring/toolchain environment.
    :return: Native executables and standalone assets for the existing release route.
    """
    runtime_python = spec.metadata.runtime_python
    if runtime_python is None:
        raise ValueError(
            "Native release assembly requires an explicit "
            "tool.apprc.distribution.runtime-python minor, such as '3.13'."
        )
    _release_source(spec)
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("Native release assembly requires unique targets.")
    source_package = source_package.expanduser().absolute()
    root = workspace.expanduser().absolute()
    assert_no_links(root)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    builder = NativeFrontendBuilder(
        root / "compiler",
        bootstrap_name=f"{spec.metadata.identity.app_id}-bootstrap",
        environment=environment,
    )
    launcher_script = root / "launcher.py"
    launcher_script.write_bytes(render_native_launcher(spec))
    launchers: dict[NativeTarget, NativeArtifact] = {}
    for target in targets:
        suffix = (
            "windows-x86_64.exe"
            if target == "x86_64-pc-windows-msvc"
            else "linux-x86_64"
        )
        launchers[target] = builder.build(
            launcher_script,
            target=target,
            destination=root
            / f"{spec.metadata.identity.app_id}-launch-{suffix}",
        )
    bundle = compile_wheel_bundle(
        spec,
        root / "bundle",
        uv=uv,
        application_source=source_package,
        extras=extras,
        target=targets[0],
        python_version=runtime_python,
        environment=environment,
    )
    linux = launchers.get("x86_64-unknown-linux-gnu")
    retained = build_runtime_payload(
        spec,
        bundle,
        targets=targets,
        linux_launcher=linux.path.read_bytes() if linux is not None else None,
    )
    main = build_main_installer(spec, payload, installer_payload=retained)
    envelope = root / "payload"
    envelope.mkdir(mode=0o700)
    entries = {
        main.destination.name: main.content,
        source_package.name: source_package.read_bytes(),
        RUNTIME_PAYLOAD_FILENAME: retained,
    }
    if spec.payload_format == "zipapp":
        entries["main-installer-requirements.txt"] = (
            "\n".join(MANAGEMENT_REQUIREMENTS) + "\n"
        ).encode()
    manifest = {
        "schema_version": 1,
        **_payload_identity(spec),
        "assets": [
            {
                "filename": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in sorted(entries.items())
        ],
    }
    entries["release-manifest.json"] = (
        json.dumps(manifest, sort_keys=True) + "\n"
    ).encode()
    for name, content in entries.items():
        (envelope / name).write_bytes(content)
    installer_script = root / "installer.py"
    installer_script.write_bytes(
        render_installer_dispatcher(
            spec, embedded_payload=_deterministic_zip(entries.items())
        )
    )
    installers = []
    for target in targets:
        suffix = (
            "windows-x86_64.exe"
            if target == "x86_64-pc-windows-msvc"
            else "linux-x86_64"
        )
        installers.append(
            builder.build(
                installer_script,
                target=target,
                destination=root
                / f"{spec.metadata.identity.app_id}-install-{suffix}",
            )
        )
    public = tuple(
        envelope / name
        for name in entries
        if name not in {"release-manifest.json", source_package.name}
    )
    return NativeDistribution((*launchers.values(), *installers), public)
