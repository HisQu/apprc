"""Render the AppRC runtime layers figure."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-runtime-layers"


def build_graph() -> Digraph:
    """Build the runtime layers diagram.

    :return: Configured Graphviz diagram.
    """

    figure = gg.fixed_diagram("apprc_runtime_layers")
    figure.graph.attr(nodesep="0.24", ranksep="0.28")

    figure.fixed_text_box(
        "title",
        "AppRC Runtime Layers",
        1.75,
        2.75,
        border_color=gg.NEUTRAL_STROKE,
        fill_color=gg.NODE_SURFACE_FILL,
    )
    figure.fixed_text_box(
        "contract",
        "Config Contract",
        0.40,
        1.35,
        "rc.Config classes",
        "@MyRC.config metadata",
        "rc.field metadata",
        border_color=gg.BLUE,
    )
    figure.fixed_text_box(
        "layers",
        "Dotenv Layers",
        3.05,
        1.35,
        "package .env.shared",
        "app .env.apprc-app",
        "storage .env.apprc-storage",
        "explicit --env-file",
        "existing os.environ",
        border_color=gg.GREEN,
    )
    figure.fixed_text_box(
        "bootstrap",
        "Bootstrap",
        5.95,
        1.35,
        "select storage",
        "merge values",
        "record provenance",
        border_color=gg.ORANGE,
    )

    figure.fixed_text_box(
        "runtime",
        "Runtime",
        0.70,
        -0.65,
        "typed config",
        border_color=gg.PURPLE,
    )
    figure.fixed_text_box(
        "diagnostics",
        "Diagnostics",
        2.55,
        -0.65,
        "paths, doctor",
        border_color=gg.PURPLE,
    )
    figure.fixed_text_box(
        "cli",
        "Config CLI",
        4.40,
        -0.65,
        "setup, set, storage",
        border_color=gg.PURPLE,
    )
    figure.fixed_text_box(
        "tui",
        "Textual TUI",
        6.25,
        -0.65,
        "inspect and edit",
        border_color=gg.PURPLE,
    )

    figure.fixed_arrow("contract", "layers")
    figure.fixed_arrow("layers", "bootstrap")
    figure.fixed_arrow("bootstrap", "runtime")
    figure.fixed_arrow("bootstrap", "diagnostics")
    figure.fixed_arrow("bootstrap", "cli")
    figure.fixed_arrow("bootstrap", "tui")
    return figure.graph


def export_figure(
    output_dir: Path | None = None,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Render the figure as an SVG asset.

    :param output_dir: Optional output directory override.
    :return: SVG paths and an empty PNG path tuple.
    """

    return export_svg_only(
        build_graph(),
        FIGURE_NAME,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        output_dir=output_dir,
    )


def main() -> int:
    """Run the command-line exporter.

    :return: Process exit code.
    """

    return gg.run_single_graph_cli(
        export_figure,
        description="Render the AppRC runtime layers figure.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
