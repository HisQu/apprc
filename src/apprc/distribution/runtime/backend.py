"""uv-tool-specific acquisition and inventory against an explicit saved backend.

No function removes shared uv or a shared Python. Application prefix discovery
is verified by the installed interpreter probe, never by resolving its symlink
and mistaking a base Python for the tool environment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from apprc.definition.installation import (
    InstallationError,
    InstallationSource,
    UvToolTarget,
)


def backend_environment(
    target: UvToolTarget, environment: Mapping[str, str]
) -> dict[str, str]:
    """Use recorded tool/bin roots even when ambient uv inputs disagree.

    :param target: Explicit validated backend address.
    :param environment: Detached invocation inputs for other subprocess settings.
    :return: Independent subprocess environment.
    """
    result = dict(environment)
    result["UV_TOOL_DIR"] = str(target.tool_dir)
    result["UV_TOOL_BIN_DIR"] = str(target.bin_dir)
    return result


def external_base_python(
    target_prefix: Path,
    *,
    executable: Path | None = None,
    forbidden_roots: tuple[Path, ...] = (),
) -> Path:
    """Select and live-probe an external base Python outside the application target.

    :param target_prefix: Observed application tool environment to exclude.
    :param executable: Previously serialized management interpreter to revalidate.
    :param forbidden_roots: Additional exact removal roots to exclude.
    :return: Absolute interpreter whose live prefix is its own base prefix.
    """
    selected = executable or (
        Path(sys.base_prefix)
        / ("python.exe" if os.name == "nt" else "bin/python")
    )
    if not selected.is_absolute() or not selected.is_file():
        raise InstallationError(
            "A regular external base Python executable is unavailable."
        )
    lexical_target = Path(
        os.path.normpath(os.fspath(target_prefix.expanduser().absolute()))
    )
    roots = (
        lexical_target,
        target_prefix.resolve(),
        *(root.resolve() for root in forbidden_roots),
    )
    lexical = Path(os.path.normpath(os.fspath(selected)))
    resolved = selected.resolve(strict=True)
    if any(
        path == root or path.is_relative_to(root)
        for path in (lexical, resolved)
        for root in roots
    ):
        raise InstallationError(
            "The management Python lies inside an uninstall removal target."
        )
    result = subprocess.run(
        [
            str(selected),
            "-I",
            "-c",
            "import json,sys; print(json.dumps([sys.prefix, sys.base_prefix]))",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    try:
        prefix, base_prefix = json.loads(result.stdout)
        prefix_path, base_path = (
            Path(prefix).resolve(),
            Path(base_prefix).resolve(),
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise InstallationError(
            "Management Python returned invalid interpreter identity."
        ) from error
    if (
        not prefix_path.is_absolute()
        or prefix_path != base_path
        or any(prefix_path.is_relative_to(root) for root in roots)
    ):
        raise InstallationError(
            "Management Python is not an independent base interpreter."
        )
    return selected


def select_uv_target(
    executable: Path,
    *,
    environment: Mapping[str, str],
    invocation_cwd: Path,
) -> UvToolTarget:
    """Query uv after normalizing relative overrides once at invocation entry.

    :param executable: Selected explicit/PATH/bootstrap uv binary.
    :param environment: Captured process environment.
    :param invocation_cwd: CWD before staging; relative inputs are anchored here.
    :return: Actual absolute backend addresses used by every later subprocess.
    """
    selected = executable.expanduser()
    if not selected.is_absolute():
        selected = invocation_cwd / selected
    selected = selected.resolve(strict=True)
    captured = dict(environment)
    for key in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR"):
        value = captured.get(key)
        if value:
            candidate = Path(value).expanduser()
            captured[key] = str(
                (invocation_cwd / candidate).resolve()
                if not candidate.is_absolute()
                else candidate.resolve()
            )
    addresses = []
    for suffix in ((), ("--bin",)):
        result = subprocess.run(
            [str(selected), "tool", "dir", *suffix, "--no-config"],
            cwd=invocation_cwd,
            env=captured,
            text=True,
            capture_output=True,
            check=True,
        )
        address = Path(result.stdout.strip())
        if not address.is_absolute():
            raise InstallationError("uv reported a relative backend directory.")
        addresses.append(address.resolve())
    return UvToolTarget(selected, addresses[0], addresses[1])


def parse_inventory(
    stdout: str, stderr: str = "", returncode: int = 0
) -> frozenset[str]:
    """Parse Buildben's existing bounded uv inventory grammar, failing closed.

    :param stdout: Actual uv tool list output.
    :param stderr: Actual diagnostics; only documented empty-inventory text is accepted.
    :param returncode: uv process status.
    :return: Normalized distributions, not executable names.
    """
    if returncode != 0 or stderr not in (
        "",
        "No tools installed",
        "No tools installed\n",
    ):
        raise InstallationError(
            "uv tool inventory is unknown; refusing mutation."
        )
    inventory: set[str] = set()
    current: str | None = None
    for line in stdout.splitlines():
        if not line:
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*) v(\S+)(?: \([^\r\n]*\))?", line
        )
        if match:
            current = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            if current in inventory:
                raise InstallationError(
                    "uv tool inventory contains duplicate distributions."
                )
            inventory.add(current)
        elif re.fullmatch(r"- [^\r\n]+", line) and current is not None:
            continue
        else:
            raise InstallationError(
                "uv tool inventory format is unknown; refusing mutation."
            )
    return frozenset(inventory)


def inspect_uv_tools(
    target: UvToolTarget, *, environment: Mapping[str, str]
) -> frozenset[str]:
    """Inspect the recorded backend without network or configuration discovery.

    :param target: Explicit selected/saved backend.
    :param environment: Captured invocation environment.
    :return: Observed distribution inventory.
    """
    result = subprocess.run(
        [
            str(target.executable),
            "tool",
            "list",
            "--color",
            "never",
            "--offline",
            "--no-config",
        ],
        env=backend_environment(target, environment),
        text=True,
        capture_output=True,
        check=False,
    )
    return parse_inventory(result.stdout, result.stderr, result.returncode)


def install_uv_tool(
    target: UvToolTarget,
    source: InstallationSource,
    *,
    environment: Mapping[str, str],
    python_requirement: str = ">=3.12",
    constraints: Path | None = None,
) -> None:
    """Acquire the explicit source; lifecycle authorization belongs to the caller.

    :param target: Validated uv address.
    :param source: Exact editable/archive/wheel/index input.
    :param environment: Captured inputs, overridden with the recorded uv roots.
    :param python_requirement: Application's declared Python compatibility.
    :param constraints: Verified release runtime constraints, separate from management deps.
    """
    if not source.requirement or source.requirement.startswith("-"):
        raise InstallationError(
            "Package source must be an explicit requirement, not a backend option."
        )
    argv = [
        str(target.executable),
        "tool",
        "install",
        "--force",
        "--no-config",
        "--no-sources",
        "--python",
        python_requirement,
    ]
    if source.kind == "editable":
        project = Path(source.requirement)
        if (
            not project.is_absolute()
            or not (project / "pyproject.toml").is_file()
        ):
            raise InstallationError(
                "Editable acquisition requires the actual absolute application project."
            )
        argv.append("--editable")
    for requirement in source.runtime_overrides:
        argv.extend(("--with", requirement))
    if constraints is not None:
        # > uv splits constraint path arguments at spaces; file URIs preserve them.
        argv.extend(("--constraint", constraints.absolute().as_uri()))
    argv.append(source.requirement)
    subprocess.run(
        argv, env=backend_environment(target, environment), check=True
    )


def remove_uv_tool(
    target: UvToolTarget,
    distribution: str,
    *,
    environment: Mapping[str, str],
) -> None:
    """Remove only the named tool and establish observed backend absence.

    :param target: Recorded backend, never newly selected ambient uv.
    :param distribution: Exact normalized recorded package identity.
    :param environment: Captured inputs with recorded uv roots imposed.
    """
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", distribution) is None:
        raise InstallationError(
            "Removal requires a normalized distribution identity."
        )
    if distribution not in inspect_uv_tools(target, environment=environment):
        return
    subprocess.run(
        [
            str(target.executable),
            "tool",
            "uninstall",
            "--no-config",
            distribution,
        ],
        env=backend_environment(target, environment),
        check=True,
    )
    if distribution in inspect_uv_tools(target, environment=environment):
        raise InstallationError(
            "uv still reports the application installed; removal is incomplete."
        )


def tool_interpreter(target: UvToolTarget, distribution: str) -> Path:
    """Return uv's candidate environment interpreter without resolving its symlink.

    :param target: Recorded backend roots.
    :param distribution: Normalized uv environment name, later verified by probe.
    :return: Candidate absolute interpreter; its sys.prefix must still be checked.
    """
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", distribution) is None:
        raise InstallationError(
            "Tool environment requires a normalized distribution identity."
        )
    prefix = target.tool_dir / distribution
    return prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
