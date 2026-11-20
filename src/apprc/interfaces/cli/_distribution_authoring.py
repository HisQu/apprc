"""Discover checkout authoring and run its build and verification operations."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import typer

from apprc.definition.resolution import resolve_editable_environment
from apprc.interfaces.cli._typer_utils import click
from apprc.interfaces.cli._editable_checkout import (
    _distribution_name,
    editable_entry_point,
)

if TYPE_CHECKING:
    from apprc.distribution.native import NativeTarget

_TARGETS: tuple[NativeTarget, ...] = (
    "x86_64-unknown-linux-gnu",
    "x86_64-pc-windows-msvc",
)


class _Backend(Protocol):
    """The build and check functions provided by one authoring module."""

    def build(
        self,
        root: Path,
        *,
        revision: str,
        targets: tuple[NativeTarget, ...],
        olis_repo: str | None = None,
    ) -> None: ...

    def check(
        self, root: Path, *, revision: str, targets: tuple[NativeTarget, ...]
    ) -> tuple[Path, ...]: ...


@dataclass(frozen=True, slots=True)
class CheckoutAuthoring:
    root: Path
    module: str
    preview: bool = False

    def backend(self) -> _Backend:
        """Load the app-author's build tooling only for an actual command."""
        try:
            backend = import_module(self.module)
        except ImportError as exc:
            raise click.ClickException(
                f"Cannot load distribution backend {self.module!r}: {exc}.\n"
                "Set up this checkout with `uv sync --locked --all-groups`."
            ) from exc
        if not all(
            callable(getattr(backend, name, None))
            for name in ("build", "check")
        ):
            raise click.ClickException(
                f"Distribution backend {self.module!r} must define build and check."
            )
        return cast(_Backend, backend)

    def install(
        self, arguments: Sequence[str], *, root_arguments: Sequence[str]
    ) -> int:
        """Select a verified local setup, then leave installation to it."""
        from apprc.distribution import (
            MissingNativeArtifact,
            StaleNativeArtifact,
        )
        from apprc.distribution.runtime._install_progress import (
            installation_color,
        )
        from apprc.interfaces._terminal_console import (
            color_environment,
            write_line,
        )

        backend = self.backend()
        try:
            targets = _targets(current=True)
            revision = _revision(self.root)
            stream = typer.get_text_stream("stdout")
            color = installation_color.get()
            write_line(
                stream, "1. Checking Local Setup", style="stage", color=color
            )
            try:
                (setup,) = _check(
                    backend, self.root, revision=revision, targets=targets
                )
            except (MissingNativeArtifact, StaleNativeArtifact) as exc:
                if not any(arg in {"--yes", "-y"} for arg in arguments):
                    if not sys.stdin.isatty():
                        raise click.ClickException(
                            f"{exc} Run `dist build -t` first or pass "
                            "`app install --yes` to authorize the local build."
                        ) from exc
                    if not typer.confirm(
                        f"{exc} Build the setup for this platform?"
                    ):
                        raise typer.Exit(1) from exc
                write_line(
                    stream,
                    "2. Building Local Setup",
                    style="stage",
                    color=color,
                )
                _build(backend, self.root, revision, targets)
                (setup,) = _check(
                    backend, self.root, revision=revision, targets=targets
                )
            write_line(
                stream,
                "Running native setup",
                prefix="   VERIFIED   ",
                path=setup,
                color=color,
            )
            setup_arguments = (*root_arguments, *arguments)
            if (
                self.preview
                and arguments
                and arguments[0] in {"--preview", "--smoke"}
            ):
                setup_arguments = (
                    arguments[0],
                    *root_arguments,
                    *arguments[1:],
                )
            return subprocess.run(
                [str(setup), *setup_arguments],
                env=color_environment(os.environ, color),
                check=False,
            ).returncode
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise click.ClickException(str(exc)) from exc


def discover_checkout_authoring(
    command: str | None, app_id: str
) -> CheckoutAuthoring | None:
    """Read only installed metadata and the editable project's declaration."""
    if command is None:
        return None
    try:
        entry, distribution, source = editable_entry_point(command)
        root = source.resolve(strict=True)
        if not resolve_editable_environment(root).samefile(sys.prefix):
            return None
        with (root / "pyproject.toml").open("rb") as stream:
            document = tomllib.load(stream)
        project = document["project"]
        settings = document["tool"]["apprc"]["distribution"]
        if (
            not isinstance(project["name"], str)
            or _distribution_name(project["name"])
            != _distribution_name(distribution.metadata["Name"])
            or project["version"] != distribution.version
            or project["scripts"][command] != entry.value
            or settings.get("app-id", app_id) != app_id
            or settings.get("command-name", command) != command
        ):
            return None
        authoring = settings.get("authoring")
        preview = isinstance(settings.get("preview"), dict)
    except (KeyError, OSError, TypeError, ValueError, AttributeError):
        return None

    if not isinstance(authoring, dict) or set(authoring) != {"backend"}:
        return None
    module = authoring["backend"]
    if not isinstance(module, str) or not all(
        component.isidentifier() for component in module.split(".")
    ):
        return None
    return CheckoutAuthoring(root, module, preview=preview)


def _targets(*, current: bool) -> tuple[NativeTarget, ...]:
    if not current:
        return _TARGETS
    if platform.machine().lower() in {"amd64", "x86_64"}:
        if sys.platform == "linux":
            return (_TARGETS[0],)
        if sys.platform == "win32":
            return (_TARGETS[1],)
    raise ValueError(
        "Current-target authoring requires x86-64 Linux or Windows."
    )


def _revision(root: Path) -> str:
    from apprc.distribution.project import _resolve_revision

    return _resolve_revision(root, "HEAD")


def _check(
    backend: _Backend,
    root: Path,
    *,
    revision: str,
    targets: tuple[NativeTarget, ...],
) -> tuple[Path, ...]:
    from apprc.distribution import MissingNativeArtifact, StaleNativeArtifact

    try:
        return backend.check(root, revision=revision, targets=targets)
    except (MissingNativeArtifact, StaleNativeArtifact):
        raise
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            f"{exc}\nInspect the setup files and SHA256SUMS in dist/.\n"
            "Restore a matching output set or move the old set before rebuilding."
        ) from exc


def _build(
    backend: _Backend,
    root: Path,
    revision: str,
    targets: tuple[NativeTarget, ...],
    *,
    olis_repo: str | None = None,
) -> None:
    from apprc.distribution.project import _git
    from apprc.distribution.runtime._install_progress import installation_color
    from apprc.interfaces._terminal_console import write_line

    if _git(root, "status", "--porcelain"):
        write_line(
            typer.get_text_stream("stderr"),
            "The setup uses the committed revision. Uncommitted edits are excluded.",
            style="warning",
            color=installation_color.get(),
        )
    if olis_repo is None:
        backend.build(root, revision=revision, targets=targets)
    else:
        backend.build(
            root, revision=revision, targets=targets, olis_repo=olis_repo
        )
