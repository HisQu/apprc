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
        "AppRC Runtime Binding",
        2.10,
        3.25,
        border_color=gg.NEUTRAL_STROKE,
        fill_color=gg.NODE_SURFACE_FILL,
    )
    figure.fixed_text_box(
        "files",
        "Managed Files",
        0.25,
        1.65,
        "package apprc.defaults.env",
        "user apprc.user.env",
        "storage apprc.storage.env",
        "explicit --env-file",
        border_color=gg.GREEN,
    )
    figure.fixed_text_box(
        "bootstrap",
        "Bootstrap",
        3.10,
        1.65,
        "select storage",
        "merge values",
        "record provenance",
        border_color=gg.ORANGE,
    )
    figure.fixed_text_box(
        "environment",
        "Process Environment",
        5.55,
        1.65,
        "os.environ",
        border_color=gg.GREEN,
    )
    figure.fixed_text_box(
        "contract",
        "Config Contract",
        0.25,
        -0.60,
        "field types",
        "Python fallbacks",
        border_color=gg.BLUE,
    )
    figure.fixed_text_box(
        "construction",
        "Config()",
        3.10,
        -0.60,
        "bind current values",
        border_color=gg.GREEN,
    )
    figure.fixed_text_box(
        "runtime",
        "Runtime Config",
        5.55,
        -0.60,
        "typed and mutable",
        "value provenance",
        border_color=gg.PURPLE,
    )

    figure.fixed_arrow("files", "bootstrap")
    figure.fixed_arrow("bootstrap", "environment")
    figure.fixed_arrow("environment", "construction")
    figure.fixed_arrow("contract", "construction")
    figure.fixed_arrow("construction", "runtime")
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
