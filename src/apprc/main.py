"""Placeholder module entrypoint for the AppRC library package.

AppRC is primarily imported by applications such as Haiu. The package keeps a
minimal ``python -m apprc`` entrypoint so editable installs have a harmless
smoke-test command, but real user-facing command trees should be built by the
application through :class:`apprc.AppConfigKit`.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Create the no-op parser used for module-entry smoke tests."""
    return argparse.ArgumentParser(
        prog="apprc",
        description="Starter entry point for the scaffolded project.",
    )


def main() -> None:
    """Accept ``--help`` and otherwise perform no application action."""
    build_parser().parse_args()


if __name__ == "__main__":
    main()
