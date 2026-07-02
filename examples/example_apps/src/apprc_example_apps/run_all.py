"""Run every repository-local AppRC example scenario."""

from __future__ import annotations

# == Standard Library ========================
import json
import tempfile
from pathlib import Path

# == Internal ================================
from apprc_app_wide_config_example import cli as app_wide_config
from apprc_app_wide_storage_example import cli as app_wide_storage
from apprc_cli_runtime_example import cli as cli_runtime
from apprc_env_only_example import cli as env_only
from apprc_explicit_env_precedence_example import cli as explicit_env_precedence
from apprc_storage_only_example import cli as storage_only

EXAMPLES = (
    env_only.run_demo,
    storage_only.run_demo,
    app_wide_config.run_demo,
    app_wide_storage.run_demo,
    explicit_env_precedence.run_demo,
    cli_runtime.run_demo,
)


def main() -> None:
    """Execute all examples and print a compact JSON summary."""
    with tempfile.TemporaryDirectory(prefix="apprc-example-apps-") as tmp:
        root = Path(tmp)
        results = [
            run(root / f"{index:02d}-{run.__module__.split('.', 1)[0]}")
            for index, run in enumerate(EXAMPLES, start=1)
        ]
    print(json.dumps(results, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
