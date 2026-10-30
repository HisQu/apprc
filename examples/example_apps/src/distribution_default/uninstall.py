"""Default package-only removal through the independent saved controller."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NoReturn

from apprc.definition.installation import InstallationError
from apprc.distribution.runtime.controllers import (
    UninstallPreparation,
    parse_uninstall_handoff_args,
    prepare_uninstall,
    start_uninstall_handoff,
)


def uninstall_default(
    directory: Path,
    *,
    original_pid: int | None = None,
    preparation: UninstallPreparation | None = None,
) -> NoReturn:
    """Preview program-only removal, then hand off immediately before process exit."""
    preparation = preparation or prepare_uninstall(directory)
    if not preparation.can_execute or preparation.plan is None:
        detail = "; ".join(item.message for item in preparation.diagnostics)
        raise InstallationError(
            detail or "Saved installation cannot be removed safely."
        )
    handoff = start_uninstall_handoff(
        preparation.plan, original_pid=original_pid
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)


def main(argv: list[str] | None = None) -> NoReturn:
    """Parse private routing metadata before invoking this authored entry."""
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
    uninstall_default(
        args.directory,
        original_pid=original_pid,
        preparation=preparation,
    )


if __name__ == "__main__":
    main()
