"""Mount distribution authoring for explicitly opted-in editable checkouts."""

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
from typing import TYPE_CHECKING, Annotated, Protocol, cast

import typer
from typer._click import ClickException

from apprc.definition.resolution import resolve_editable_environment
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
        self, root: Path, *, revision: str, targets: tuple[NativeTarget, ...]
    ) -> None: ...

    def check(
        self, root: Path, *, revision: str, targets: tuple[NativeTarget, ...]
    ) -> tuple[Path, ...]: ...


@dataclass(frozen=True, slots=True)
class CheckoutAuthoring:
    root: Path
    module: str

    def backend(self) -> _Backend:
        """Load the app-author's build tooling only for an actual command."""
        try:
            backend = import_module(self.module)
        except ImportError as exc:
            raise ClickException(
                f"Cannot load distribution backend {self.module!r}: {exc}.\n"
                "Set up this checkout with `uv sync --locked --all-groups`."
            ) from exc
        if not all(
            callable(getattr(backend, name, None))
            for name in ("build", "check")
        ):
            raise ClickException(
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
            cli_line,
            color_environment,
        )

        backend = self.backend()
        try:
            targets = _targets(current=True)
            revision = _revision(self.root)
            try:
                (setup,) = _check(
                    backend, self.root, revision=revision, targets=targets
                )
            except (MissingNativeArtifact, StaleNativeArtifact) as exc:
                if not any(arg in {"--yes", "-y"} for arg in arguments):
                    if not sys.stdin.isatty():
                        raise ClickException(
                            f"{exc} Run `dist build -t` first or pass "
                            "`app install --yes` to authorize the local build."
                        ) from exc
                    if not typer.confirm(
                        f"{exc} Build the setup for this platform?"
                    ):
                        raise typer.Exit(1) from exc
                _build(backend, self.root, revision, targets)
                (setup,) = _check(
                    backend, self.root, revision=revision, targets=targets
                )
            cli_line(None, "Running native setup", path=setup)
            return subprocess.run(
                [str(setup), *root_arguments, *arguments],
                env=color_environment(os.environ, installation_color.get()),
                check=False,
            ).returncode
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise ClickException(str(exc)) from exc


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
    except (KeyError, OSError, TypeError, ValueError, AttributeError):
        return None

    if not isinstance(authoring, dict) or set(authoring) != {"backend"}:
        return None
    module = authoring["backend"]
    if not isinstance(module, str) or not all(
        component.isidentifier() for component in module.split(".")
    ):
        return None
    return CheckoutAuthoring(root, module)


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
        raise ClickException(
            f"{exc}\nInspect the setup files and SHA256SUMS in dist/.\n"
            "Restore a matching output set or move the old set before rebuilding."
        ) from exc


def _build(
    backend: _Backend,
    root: Path,
    revision: str,
    targets: tuple[NativeTarget, ...],
) -> None:
    from apprc.distribution.project import _git
    from apprc.interfaces._terminal_console import cli_line

    if _git(root, "status", "--porcelain"):
        cli_line(
            None,
            "The setup uses the committed revision. Uncommitted edits are excluded.",
            error=True,
        )
    backend.build(root, revision=revision, targets=targets)


def distribution_group() -> None:
    """Build and verify native setups from the development checkout."""


def build_authoring_group(authoring: CheckoutAuthoring) -> typer.Typer:
    """Create shared build and check commands without importing the backend."""
    app = typer.Typer(no_args_is_help=True)
    app.callback()(distribution_group)

    @app.command()
    def build(
        ctx: typer.Context,
        target_current: Annotated[
            bool,
            typer.Option(
                "--target-current", "-t", help="Build only for this platform."
            ),
        ] = False,
    ) -> None:
        """Build verified setup executables from the committed checkout."""
        from apprc.distribution import (
            MissingNativeArtifact,
            StaleNativeArtifact,
        )
        from apprc.interfaces._terminal_console import cli_line

        backend = authoring.backend()
        try:
            targets = _targets(current=target_current)
            revision = _revision(authoring.root)
            try:
                _check(
                    backend, authoring.root, revision=revision, targets=targets
                )
            except (MissingNativeArtifact, StaleNativeArtifact):
                pass
            _build(backend, authoring.root, revision, targets)
            for path in _check(
                backend, authoring.root, revision=revision, targets=targets
            ):
                cli_line(ctx, "Built", path=path)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise ClickException(str(exc)) from exc

    @app.command()
    def check(
        ctx: typer.Context,
        target_current: Annotated[
            bool,
            typer.Option(
                "--target-current",
                "-t",
                help="Require a current setup only for this platform.",
            ),
        ] = False,
    ) -> None:
        """Check setup integrity and freshness without running the artifacts."""
        from apprc.interfaces._terminal_console import cli_line

        backend = authoring.backend()
        try:
            for path in _check(
                backend,
                authoring.root,
                revision=_revision(authoring.root),
                targets=_targets(current=target_current),
            ):
                cli_line(ctx, "Verified", path=path)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise ClickException(str(exc)) from exc

    return app
