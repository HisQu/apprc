"""Read-only saved installation inspection without backend or app imports."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from apprc.user_files.installation.discovery import inspect_installation


def inspect_saved_directory(
    directory: Path, *, app_id: str
) -> dict[str, object]:
    """Read the adjacent authority and serialize its status without mutation.

    :param directory: Explicit saved installation address.
    :param app_id: Host identity supplied by the saved caller.
    :return: JSON-compatible inspection status, record and diagnostics.
    """
    inspection = inspect_installation(directory, app_id=app_id)
    return {
        "app_id": inspection.app_id,
        "directory": str(inspection.directory),
        "revision": inspection.revision,
        "status": inspection.status,
        "record": asdict(inspection.record)
        if inspection.record is not None
        else None,
        "diagnostics": [asdict(item) for item in inspection.diagnostics],
    }


def main() -> int:
    """Expose an explicit adjacent-record JSON read with no side effects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--app-id", required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            inspect_saved_directory(
                arguments.directory, app_id=arguments.app_id
            ),
            default=str,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
