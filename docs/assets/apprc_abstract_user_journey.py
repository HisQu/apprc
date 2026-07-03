"""Render the AppRC developer/operator journey abstract."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg
import graphigs.graphviz as gv
from graphigs.figure_contract import FigureBounds
from graphigs.figure_contract import SvgDisplayBounds
from graphigs.graphviz.labels import edge_label

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-abstract-user-journey"
README_HERO_BOUNDS = FigureBounds(
    page_width_mm=360.0,
    page_height_mm=170.0,
    page_margin_mm=16.0,
    max_height_fraction=0.86,
)
README_HERO_SVG_BOUNDS = SvgDisplayBounds(
    display_width_px=1180,
    max_display_height_px=420,
)


def build_graph() -> Digraph:
    """Build the user journey graphical abstract.

    :return: Configured Graphviz diagram.
    """

    figure = gg.fixed_diagram("apprc_abstract_user_journey", direction="LR")

    developer = gv.add_fixed_panel_cluster(
        "developer",
        "",
        color=gg.BLUE,
        fill=gg.BLUE_GROUP_FILL,
        margin="16",
    )
    gv.add_fixed_text_box(
        developer,
        "config_contract",
        "Config contract",
        ("rc.Config", "@MyRC.config", "rc.field"),
        pos=gv.fixed_position(0.40, 0.0),
        border_color=gg.BLUE,
    )
    gv.add_fixed_text_box(
        developer,
        "shipped_app",
        "Shipped config UX",
        ("rc.AppRC", "bootstrap", "config CLI"),
        pos=gv.fixed_position(2.35, 0.0),
        border_color=gg.BLUE,
    )
    figure.graph.subgraph(developer)

    operator = gv.add_fixed_panel_cluster(
        "operator",
        "",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        operator,
        "setup_and_doctor",
        "Setup + diagnose",
        ("config paths", "config setup", "config doctor"),
        pos=gv.fixed_position(4.65, 0.0),
        border_color=gg.ORANGE,
    )
    gv.add_fixed_text_box(
        operator,
        "edit_values",
        "Configure values",
        ("config set", "config edit", "dotenv writes"),
        pos=gv.fixed_position(7.05, 0.0),
        border_color=gg.ORANGE,
    )
    gv.add_fixed_text_box(
        operator,
        "runtime_app",
        "Run app",
        ("typed config", "zero-write reads"),
        pos=gv.fixed_position(9.30, 0.0),
        border_color=gg.GREEN,
    )
    gv.add_fixed_text_box(
        operator,
        "inspect_loop",
        "Inspect loop",
        ("config doctor", "provenance"),
        pos=gv.fixed_position(7.05, -1.45),
        border_color=gg.PURPLE,
    )
    figure.graph.subgraph(operator)

    gv.add_fixed_label(
        figure.graph,
        "developer_label",
        "App developer",
        pos=gv.fixed_position(1.38, 0.78),
        color=gg.BLUE,
    )
    gv.add_fixed_label(
        figure.graph,
        "operator_label",
        "App user / operator",
        pos=gv.fixed_position(7.00, 0.78),
        color=gg.ORANGE,
    )
    gv.connect_fixed_arrow(
        figure.graph, "config_contract", "shipped_app", color=gg.BLUE
    )
    gv.add_fixed_html_node(
        figure.graph,
        "declare_label",
        edge_label("declare", color=gg.BLUE),
        pos=gv.fixed_position(1.38, 0.24),
    )
    gv.connect_fixed_arrow(
        figure.graph,
        "shipped_app",
        "setup_and_doctor",
        color=gg.ORANGE,
    )
    gv.add_fixed_html_node(
        figure.graph,
        "ship_label",
        edge_label("ship", color=gg.ORANGE),
        pos=gv.fixed_position(3.50, 0.24),
    )
    gv.connect_fixed_arrow(
        figure.graph,
        "setup_and_doctor",
        "edit_values",
        color=gg.ORANGE,
    )
    gv.add_fixed_html_node(
        figure.graph,
        "configure_label",
        edge_label("configure", color=gg.ORANGE),
        pos=gv.fixed_position(5.85, 0.24),
    )
    gv.connect_fixed_arrow(
        figure.graph,
        "edit_values",
        "runtime_app",
        color=gg.GREEN,
    )
    gv.add_fixed_html_node(
        figure.graph,
        "run_label",
        edge_label("run", color=gg.GREEN),
        pos=gv.fixed_position(8.18, 0.24),
    )
    gv.connect_fixed_arrow(
        figure.graph,
        "runtime_app",
        "inspect_loop",
        color=gg.PURPLE,
        dashed=True,
    )
    gv.connect_fixed_arrow(
        figure.graph,
        "inspect_loop",
        "setup_and_doctor",
        color=gg.PURPLE,
        dashed=True,
    )
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
        bounds=README_HERO_BOUNDS,
        svg_bounds=README_HERO_SVG_BOUNDS,
    )


def main() -> int:
    """Run the command-line exporter.

    :return: Process exit code.
    """

    return gg.run_single_graph_cli(
        export_figure,
        description="Render the AppRC user journey graphical abstract.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
