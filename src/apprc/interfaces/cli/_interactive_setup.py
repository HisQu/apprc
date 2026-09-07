"""Interactive AppRC setup prompts with filesystem completion."""

from __future__ import annotations

# == Standard Library ===========================================
from pathlib import Path
from typing import Literal

# == 3rd Party ==================================================
import typer
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter, WordCompleter

type SetupDirectoryChoice = Literal["default", "custom", "cancel"]


def prompt_apprc_setup_dir(*, suggested: Path) -> Path | None:
    """Ask for the directory that will contain AppRC-managed files.

    :param suggested: Directory resolved from environment, declaration, or the
        cross-platform AppRC default.
    :return: Chosen path, or ``None`` when canceled.
    """
    return _prompt_setup_directory(subject="AppRC", suggested=suggested)


def prompt_storage_setup_root(*, suggested: Path) -> Path | None:
    """Ask whether to use the suggested root, enter another, or cancel.

    Empty input cancels. Custom path input completes directories on every
    supported platform through prompt-toolkit.

    :param suggested: Predictable default storage root.
    :return: Chosen path, or ``None`` when canceled.
    """
    return _prompt_setup_directory(subject="Storage", suggested=suggested)


def _prompt_setup_directory(
    *,
    subject: str,
    suggested: Path,
) -> Path | None:
    """Prompt for one directory using the shared three-way choice.

    :param subject: Human-facing directory owner.
    :param suggested: Predictable path accepted by the default choice.
    :return: Selected path, or ``None`` when canceled.
    """
    typer.echo(f"Suggested {subject} directory: {suggested}")
    typer.echo("Choose [d]efault, [p]ath, or [c]ancel.")
    try:
        raw_choice = prompt(
            f"{subject} setup [c]: ",
            completer=WordCompleter(
                ["default", "path", "cancel"],
                ignore_case=True,
            ),
        )
    except (EOFError, KeyboardInterrupt):
        return None
    choice = _parse_setup_directory_choice(raw_choice)
    if choice == "cancel":
        return None
    if choice == "default":
        return suggested
    try:
        raw_path = prompt(
            f"{subject} path: ",
            completer=PathCompleter(
                only_directories=True,
                expanduser=True,
            ),
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return Path(raw_path).expanduser() if raw_path else None


def prompt_storage_registration_name(*, suggested: str) -> str | None:
    """Prompt for the registry name assigned to a direct storage path.

    :param suggested: Name shown as the default.
    :return: Entered name, the suggestion on empty input, or ``None`` when
        prompt-toolkit reports an interruption.
    """
    try:
        return prompt("Storage name: ", default=suggested).strip() or suggested
    except (EOFError, KeyboardInterrupt):
        return None


def _parse_setup_directory_choice(value: str) -> SetupDirectoryChoice:
    """Normalize one short or full setup choice.

    :param value: Interactive input.
    :return: Supported choice, defaulting to cancellation.
    """
    normalized = value.strip().lower()
    if normalized in {"d", "default"}:
        return "default"
    if normalized in {"p", "path"}:
        return "custom"
    return "cancel"
