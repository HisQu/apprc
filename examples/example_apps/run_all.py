"""Run every executable AppRC example app."""

from __future__ import annotations

# == Standard Library ========================
import json
import sys
import tempfile
from pathlib import Path

EXAMPLES_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (EXAMPLES_ROOT, REPO_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# == Internal ================================
from example_apps import (  # noqa: E402
    app_wide_config_app,
    app_wide_storage_app,
    env_only_app,
    explicit_env_precedence_app,
    storage_only_app,
)


EXAMPLES = (
    env_only_app.run,
    storage_only_app.run,
    app_wide_config_app.run,
    app_wide_storage_app.run,
    explicit_env_precedence_app.run,
)


def main() -> None:
    """Execute all AppRC examples and print a compact JSON summary."""
    with tempfile.TemporaryDirectory(prefix="apprc-example-apps-") as tmp:
        root = Path(tmp)
        results = [
            run(root / f"{index:02d}-{run.__module__.rsplit('.', 1)[-1]}")
            for index, run in enumerate(EXAMPLES, start=1)
        ]
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
