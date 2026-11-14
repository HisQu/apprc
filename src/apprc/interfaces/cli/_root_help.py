"""Opt-in root help presentation without changing Typer command behavior."""

from __future__ import annotations

from io import StringIO
import os
from typing import Protocol

import typer
from typer.core import TyperArgument, TyperCommand, TyperGroup, TyperOption


class _HelpWriter(Protocol):
    """Public formatter surface shared across supported Typer versions."""

    width: int

    def write(self, text: str, /) -> None: ...


class AppRCRootGroup(TyperGroup):
    """Separate host, AppRC, and common help panels on an application's root group.

    Opt in with ``typer.Typer(cls=AppRCRootGroup)``. Nested contexts retain
    Typer's normal help rendering, parsing, and completion behavior.
    """

    def format_help(self, ctx: typer.Context, formatter: _HelpWriter) -> None:
        """Write root help using the formatter supplied by Typer.

        :param ctx: Active Click context, including color and terminal settings.
        :param formatter: Public Click help formatter supplied by Typer.
        """
        output_formatter = formatter
        formatter = ctx.make_formatter()
        formatter.width = output_formatter.width
        if ctx.parent is not None:
            super().format_help(ctx, formatter)
            output_formatter.write(formatter.getvalue())
            return
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        panels: dict[str, list[tuple[str, str]]] = {
            "Commands": [],
            "Options": [],
            "AppRC: Commands": [],
            "AppRC: Runtime Options": [],
            "Help & Completion": [],
        }
        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record is None:
                continue
            panel = "Options"
            if any(
                option
                in {"--help", "--install-completion", "--show-completion"}
                for option in param.opts
            ):
                panel = "Help & Completion"
            elif (
                isinstance(param, (TyperOption, TyperArgument))
                and param.rich_help_panel == "AppRC: Runtime Options"
            ):
                panel = "AppRC: Runtime Options"
            panels[panel].append(record)

        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is None or command.hidden:
                continue
            panel = "Commands"
            if (
                isinstance(command, (TyperCommand, TyperGroup))
                and command.rich_help_panel == "AppRC: Commands"
            ):
                panel = "AppRC: Commands"
            limit = max(
                45, len(command.help or ""), len(command.short_help or "")
            )
            panels[panel].append(
                (name, command.get_short_help_str(limit=limit))
            )

        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)

        # > Capture panels locally while detecting the actual output terminal.
        # > Rich honors NO_COLOR; explicit Click color settings override detection.
        output = StringIO()
        use_color = (
            ctx.color
            if ctx.color is not None
            else typer.get_text_stream("stdout").isatty()
        ) and "NO_COLOR" not in os.environ
        console = Console(
            file=output,
            width=formatter.width,
            force_terminal=use_color,
            color_system="standard" if use_color else None,
            markup=False,
            highlight=False,
        )
        for title, rows in panels.items():
            if not rows:
                continue
            style = (
                "magenta"
                if title.startswith("AppRC:")
                else "dim"
                if title == "Help & Completion"
                else "cyan"
            )
            table = Table.grid(padding=(0, 2), expand=True)
            table.add_column(
                max_width=max(12, formatter.width // 3), overflow="fold"
            )
            table.add_column(ratio=1)
            for name, help_text in rows:
                table.add_row(Text(name), Text(help_text))
            console.print(
                Panel(
                    table,
                    title=Text(title, style=style),
                    title_align="left",
                    border_style=style,
                )
            )
        if output.tell():
            formatter.write_paragraph()
            formatter.write(output.getvalue())
        self.format_epilog(ctx, formatter)
        output_formatter.write(formatter.getvalue())


class _AppRCMaintenanceGroup(TyperGroup):
    """Describe only the immediate maintenance commands actually compiled."""

    def get_short_help_str(self, limit: int = 45) -> str:
        """Return the full registration-order summary for root-table wrapping.

        :param limit: Click's shortening hint, intentionally unused so available
            maintenance commands are never omitted from the summary.
        :return: The maintenance purpose and its visible immediate commands.
        """
        names = ", ".join(
            name
            for name, command in self.commands.items()
            if not command.hidden
        )
        return f"Inspect and maintain the application ({names})."
