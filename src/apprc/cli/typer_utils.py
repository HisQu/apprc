"""Reusable Typer command helpers."""

from __future__ import annotations

# == Standard Library ========================
import json
import sys
from collections.abc import Collection, Sequence
from importlib import import_module
from typing import Any, NoReturn, TypeVar

import typer

try:
    click: Any = import_module("typer._click")
except ModuleNotFoundError:
    click = import_module("click")

MISSING_ACTION_MESSAGE = "error: no action specified"
StateT = TypeVar("StateT")


def dump_json(payload: Any) -> None:
    """Write a JSON payload to stdout using stable formatting.

    :param payload: JSON-serializable object, with ``str()`` fallback for paths
        and other display-only values.
    """
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


def exit_missing_action(ctx: typer.Context) -> NoReturn:
    """Print the active command group's help after a missing subcommand.

    :param ctx: Typer context whose local help text should be shown.
    :return: This helper exits the current CLI command.
    """
    typer.echo(MISSING_ACTION_MESSAGE, err=True)
    typer.echo(ctx.get_help())
    raise typer.Exit(code=2)


def state_from(ctx: typer.Context, expected_type: type[StateT]) -> StateT:
    """Return the typed state object stored on the active context.

    :param ctx: Active Typer context.
    :param expected_type: Runtime type expected on ``ctx.obj``.
    :return: Typed state object.
    :raises RuntimeError: If the state has not been initialized.
    """
    state = ctx.obj
    if not isinstance(state, expected_type):
        raise RuntimeError("CLI state is not initialized.")
    return state


def strip_leading_options(
    tokens: Sequence[str],
    *,
    flag_options: Collection[str],
    value_options: Collection[str],
) -> list[str]:
    """Remove known leading options from a command token sequence.

    :param tokens: Raw child command tokens.
    :param flag_options: Option names that consume no value.
    :param value_options: Option names that consume one following value unless
        the value is supplied through ``--option=value``.
    :return: Tokens beginning with the first positional command/action.
    """
    remaining = list(tokens)
    i = 0
    while i < len(remaining):
        token = remaining[i]
        if token == "--":
            return remaining[i + 1 :]
        if not token.startswith("-"):
            return remaining[i:]

        option_name = token.split("=", maxsplit=1)[0]
        if option_name in value_options:
            i += 1 if "=" in token else 2
            continue
        if option_name in flag_options:
            i += 1
            continue
        return remaining[i:]
    return []


def args_after_command(
    command_name: str,
    *,
    tokens: Sequence[str] | None = None,
    root_value_options: Collection[str] = (),
) -> list[str] | None:
    """Return tokens after one top-level command group.

    Click's root callback does not expose child command arguments, so callers
    can inspect ``sys.argv`` before bootstrap produces runtime side effects for
    help-only usage errors.

    :param command_name: Top-level command name to locate.
    :param tokens: Optional command tokens without the program name.
    :param root_value_options: Root options that consume a following value when
        passed before the command.
    :return: Child tokens after the command, or ``None`` for another command.
    """
    args = list(sys.argv[1:] if tokens is None else tokens)
    i = 0
    while i < len(args):
        token = args[i]
        if token == command_name:
            return args[i + 1 :]
        if token == "--":
            return None
        if token.startswith("-"):
            option_name = token.split("=", maxsplit=1)[0]
            if option_name in root_value_options and "=" not in token:
                i += 2
            else:
                i += 1
            continue
        return None
    return None


def run_typer_app(
    target_app: typer.Typer,
    *,
    args: list[str],
    prog_name: str,
) -> None:
    """Run another Typer application from a forwarding command.

    :param target_app: Typer app to execute.
    :param args: Argument tokens for the target app.
    :param prog_name: Display program name for help and errors.
    """
    command = typer.main.get_command(target_app)
    try:
        exit_code = command.main(
            args=args,
            prog_name=prog_name,
            standalone_mode=False,
        )
        if isinstance(exit_code, int) and exit_code != 0:
            raise typer.Exit(code=exit_code)
    except click.exceptions.Exit as exc:
        raise typer.Exit(code=exc.exit_code) from exc
    except click.ClickException as exc:
        exc.show()
        raise typer.Exit(code=exc.exit_code) from exc
