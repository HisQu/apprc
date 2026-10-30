"""Default package-only and custom provider cleanup with saved removal."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from apprc.definition.installation import InstallationError, OperationContext
from apprc.distribution.runtime.controllers import (
    UninstallPreparation,
    parse_uninstall_handoff_args,
    prepare_uninstall,
    start_uninstall_handoff,
)


def uninstall_package_only(
    directory: Path, *, original_pid: int | None = None
) -> NoReturn:
    """Remove the installed tool while retaining application data and configuration."""
    preparation = prepare_uninstall(directory)
    if preparation.plan is None or not preparation.can_execute:
        raise InstallationError("Removal preview is not safe to execute.")
    handoff = start_uninstall_handoff(
        preparation.plan, original_pid=original_pid
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)


def uninstall_with_project_cleanup(
    preparation: UninstallPreparation,
    *,
    cleanup_project: Callable[[OperationContext], None] | None,
    original_pid: int | None = None,
) -> NoReturn:
    """Run cleanup while installed or independent completion after removal.

    :param preparation: Exact removal preview accepted by the caller.
    :param cleanup_project: App cleanup while installed, or None after removal.
    :param original_pid: Initiating CLI or launcher PID from private routing metadata.
    """
    if preparation.plan is None or not preparation.can_execute:
        raise InstallationError("Removal preview is not safe to execute.")
    handoff = start_uninstall_handoff(
        preparation.plan,
        provider_cleanup=cleanup_project,
        original_pid=original_pid,
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)


def main(
    argv: list[str] | None = None,
    *,
    cleanup_project: Callable[[OperationContext], None],
) -> NoReturn:
    """Parse saved routing metadata and run this application's cleanup."""
    original_pid, expected_revision, forwarded = parse_uninstall_handoff_args(
        argv
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument(
        "--category",
        action="append",
        choices=("config", "appdata", "cache", "state"),
    )
    parser.add_argument("--forget-retained", action="store_true")
    args = parser.parse_args(forwarded)
    if args.forget_retained and not args.complete:
        parser.error("--forget-retained requires --complete")
    preparation = prepare_uninstall(
        args.directory,
        categories=frozenset(args.category or ()),
        complete=args.complete,
        forget_retained=args.forget_retained,
    )
    if expected_revision is not None and (
        preparation.plan is None
        or preparation.plan.expected_revision != expected_revision
    ):
        raise InstallationError("Installation changed after uninstall preview.")
    record = preparation.inspection.record
    uninstall_with_project_cleanup(
        preparation,
        cleanup_project=(
            cleanup_project
            if record is not None and record.current is not None
            else None
        ),
        original_pid=original_pid,
    )
