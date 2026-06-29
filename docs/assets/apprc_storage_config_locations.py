"""Render the AppRC storage and config location map."""

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
FIGURE_NAME = "apprc-storage-config-locations"
LOCATION_MAP_BOUNDS = FigureBounds(
    page_width_mm=360.0,
    page_height_mm=210.0,
    page_margin_mm=16.0,
    max_height_fraction=0.86,
)
LOCATION_MAP_SVG_BOUNDS = SvgDisplayBounds(
    display_width_px=1180,
    max_display_height_px=560,
)


def build_graph() -> Digraph:
    """Build the dotenv location and capability-shape figure.

    :return: Configured Graphviz diagram.
    """

    figure = gg.fixed_diagram("apprc_storage_config_locations", direction="LR")

    install = gv.add_fixed_panel_cluster(
        "install",
        "",
        color=gg.BLUE,
        fill=gg.BLUE_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        install,
        "shared_env",
        ".env.shared",
        ("packaged defaults", "read-only after install", "used by: all kits"),
        pos=gv.fixed_position(1.05, 0.70),
        border_color=gg.BLUE,
    )
    gv.add_fixed_text_box(
        install,
        "package",
        "myapp package",
        ("installed code", "ships .env.shared"),
        pos=gv.fixed_position(1.05, -0.65),
        border_color=gg.BLUE,
    )
    figure.graph.subgraph(install)

    config_home = gv.add_fixed_panel_cluster(
        "config_home",
        "",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        config_home,
        "config_home_root",
        "~/.config/myapp",
        ("platform folder", "per user"),
        pos=gv.fixed_position(3.95, 1.00),
        border_color=gg.ORANGE,
    )
    gv.add_fixed_text_box(
        config_home,
        "app_wide_env",
        ".env.apprc-app",
        (
            "app-wide settings",
            "used by: app-wide kits",
            "optional: storage_only",
        ),
        pos=gv.fixed_position(3.95, -0.45),
        border_color=gg.ORANGE,
    )
    gv.add_fixed_text_box(
        config_home,
        "address_book",
        "Storage address book",
        ("<app>.apprc.toml", "example name -> folder", "not a dotenv file"),
        pos=gv.fixed_position(6.20, 0.25),
        border_color=gg.NEUTRAL_STROKE,
    )
    figure.graph.subgraph(config_home)

    storages = gv.add_fixed_panel_cluster(
        "storages",
        "",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        storages,
        "project_a_folder",
        "example: project-a",
        (
            "/data/project-a",
            ".env.apprc-storage",
            "app data",
            "used by: storage kits",
        ),
        pos=gv.fixed_position(9.80, 0.85),
        border_color=gg.GREEN,
    )
    gv.add_fixed_text_box(
        storages,
        "project_b_folder",
        "example: project-b",
        (
            "/data/project-b",
            ".env.apprc-storage",
            "app data",
            "used by: storage kits",
        ),
        pos=gv.fixed_position(9.80, -0.90),
        border_color=gg.GREEN,
    )
    figure.graph.subgraph(storages)

    startup = gv.add_fixed_panel_cluster(
        "startup",
        "",
        color=gg.PURPLE,
        fill=gg.PURPLE_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        startup,
        "explicit_env_file",
        "Explicit dotenv",
        ("--env-file", "runtime input", "used by: all kits"),
        pos=gv.fixed_position(1.20, -2.55),
        border_color=gg.PURPLE,
    )
    gv.add_fixed_text_box(
        startup,
        "shell_env",
        "Shell environment",
        ("os.environ", "runtime input", "used by: all kits"),
        pos=gv.fixed_position(3.70, -2.55),
        border_color=gg.PURPLE,
    )
    gv.add_fixed_text_box(
        startup,
        "storage_choice",
        "Storage choice examples",
        (
            "--storage / <APP>_STORAGE",
            "name: project-a",
            "path: /data/project-b",
        ),
        pos=gv.fixed_position(6.20, -2.55),
        border_color=gg.PURPLE,
    )
    gv.add_fixed_text_box(
        startup,
        "kit_key",
        "Kit shape key",
        (
            "all kits",
            "shared + runtime",
            "app-wide: app file",
            "storage: storage file",
        ),
        pos=gv.fixed_position(9.30, -2.55),
        border_color=gg.NEUTRAL_STROKE,
    )
    figure.graph.subgraph(startup)
    gv.add_fixed_label(
        figure.graph,
        "install_label",
        "Installed app package",
        pos=gv.fixed_position(1.05, 1.75),
        color=gg.BLUE,
    )
    gv.add_fixed_label(
        figure.graph,
        "config_home_label",
        "User config folder",
        pos=gv.fixed_position(5.05, 1.75),
        color=gg.ORANGE,
    )
    gv.add_fixed_label(
        figure.graph,
        "storages_label",
        "Storage folders",
        pos=gv.fixed_position(9.80, 1.75),
        color=gg.GREEN,
    )
    gv.add_fixed_label(
        figure.graph,
        "startup_label",
        "Startup inputs",
        pos=gv.fixed_position(3.70, -1.50),
        color=gg.PURPLE,
    )

    gv.connect_fixed_arrow(
        figure.graph, "address_book", "project_a_folder", color=gg.GREEN
    )
    _badge(
        figure.graph,
        "saved_name_badge",
        ("saved name", "points here"),
        7.75,
        0.65,
        gg.GREEN,
    )
    gv.connect_fixed_arrow(
        figure.graph, "storage_choice", "address_book", color=gg.PURPLE
    )
    _badge(
        figure.graph,
        "name_choice_badge",
        ("name", "choice"),
        6.68,
        -1.10,
        gg.PURPLE,
    )
    gv.connect_fixed_arrow(
        figure.graph, "storage_choice", "project_b_folder", color=gg.GREEN
    )
    _badge(
        figure.graph,
        "path_choice_badge",
        ("path", "choice"),
        7.62,
        -1.78,
        gg.GREEN,
    )
    return figure.graph


def _badge(
    graph: Digraph,
    node_id: str,
    label: str | tuple[str, ...],
    x: float,
    y: float,
    color: str,
) -> None:
    """Place one fixed Graphigs edge-label badge.

    :param graph: Graph receiving the fixed badge node.
    :param node_id: DOT identifier for the badge node.
    :param label: Badge text.
    :param x: Horizontal coordinate.
    :param y: Vertical coordinate.
    :param color: Badge fill and border color.
    :return: None.
    """

    gv.add_fixed_html_node(
        graph,
        node_id,
        edge_label(label, color=color),
        pos=gv.fixed_position(x, y),
    )


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
        bounds=LOCATION_MAP_BOUNDS,
        svg_bounds=LOCATION_MAP_SVG_BOUNDS,
    )


def main() -> int:
    """Run the command-line exporter.

    :return: Process exit code.
    """

    return gg.run_single_graph_cli(
        export_figure,
        description="Render the AppRC storage and config location map.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
