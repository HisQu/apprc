"""Render the AppRC documentation reading map figure."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "docs-reading-map"


def build_graph() -> Digraph:
    """Build the documentation reading map diagram.

    :return: Configured Graphviz diagram.
    """

    figure = gg.fixed_diagram("docs_reading_map")
    figure.graph.attr(nodesep="0.20", ranksep="0.25")

    figure.fixed_text_box(
        "title",
        "AppRC Documentation Map",
        2.20,
        2.35,
        border_color=gg.NEUTRAL_STROKE,
        fill_color=gg.NODE_SURFACE_FILL,
    )
    figure.fixed_text_box(
        "readme",
        "Root README",
        0.55,
        1.30,
        "Adopter entry point",
        border_color=gg.BLUE,
    )
    figure.fixed_text_box(
        "docs",
        "docs/README",
        3.00,
        1.30,
        "Manual reading map",
        border_color=gg.ORANGE,
    )
    figure.fixed_text_box(
        "how_to",
        "How-To",
        -0.05,
        -0.10,
        "Task recipes",
        border_color=gg.BLUE,
    )
    figure.fixed_text_box(
        "development",
        "Development",
        1.80,
        -0.10,
        "Maintainer loop",
        border_color=gg.ORANGE,
    )
    figure.fixed_text_box(
        "references",
        "References",
        3.65,
        -0.10,
        "Exact names",
        border_color=gg.GREEN,
    )
    figure.fixed_text_box(
        "explanations",
        "Explanations",
        5.50,
        -0.10,
        "System model",
        border_color=gg.PURPLE,
    )

    figure.fixed_arrow("readme", "docs")
    figure.fixed_arrow("docs", "how_to")
    figure.fixed_arrow("docs", "development")
    figure.fixed_arrow("docs", "references")
    figure.fixed_arrow("docs", "explanations")
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
        description="Render the AppRC documentation reading map figure.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
