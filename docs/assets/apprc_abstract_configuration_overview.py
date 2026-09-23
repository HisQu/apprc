"""Render the AppRC configuration overview with Graphigs.

Run ``python docs/assets/apprc_abstract_configuration_overview.py`` from the
repository root. The shared docs exporter keeps the committed figure SVG-only.
"""

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg
import graphigs.graphviz as gv
from graphigs.figure_contract import FigureBounds, SvgDisplayBounds
from graphigs.graphviz.labels import edge_label

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-abstract-configuration-overview"
FEATURE_BOX_FILL = f"{gg.TEXT_BOX_SURFACE_FILL[:7]}66"
SMALL_TEXT_FONT_SIZE = f"{float(gg.NODE_FONT_SIZE) + 3:g}"
EDGE_BADGE_FONT_SIZE = f"{float(gg.EDGE_LABEL_FONT_SIZE) + 3:g}"
FIGURE_BOUNDS = FigureBounds(
    page_width_mm=370.0,
    page_height_mm=230.0,
    page_margin_mm=12.0,
    max_height_fraction=0.94,
    dpi=160,
)
SVG_BOUNDS = SvgDisplayBounds(
    display_width_px=1080,
    max_display_height_px=860,
)


def edge_badge(label: str, color: str) -> str:
    """Build a Graphigs edge badge with three-point larger text.

    :param label: Short text shown in the badge.
    :param color: Badge fill and border color.
    :return: HTML-like badge label with larger text.
    """
    badge = edge_label(label, color=color)
    return badge.replace(
        f'POINT-SIZE="{gg.EDGE_LABEL_FONT_SIZE}"',
        f'POINT-SIZE="{EDGE_BADGE_FONT_SIZE}"',
    )


def build_graph() -> Digraph:
    """Place precedence on the left and connect managed files to directories.

    Upward arrows mean the upper source overrides the lower source. Dashed
    lines locate files on disk. Text and frames share Graphigs semantic colors;
    light group fills keep the labels readable.

    :return: Pinned diagram with transparent canvas and themed components.
    """
    graph = gg.fixed_diagram("apprc_abstract_configuration_overview").graph
    graph.attr(outputorder="nodesfirst", pad="0.16")
    graph.attr("node", fontcolor=gg.NEUTRAL_STROKE)

    # == Unboxed benefits above the application
    for node_id, audience, benefit, x in (
        (
            "developer_benefits",
            "FOR DEVELOPERS",
            "Declare and document once.",
            6.35,
        ),
        (
            "user_benefits",
            "FOR APP USERS",
            "Understand and edit settings.",
            10.95,
        ),
    ):
        gv.add_fixed_html_node(
            graph,
            node_id,
            f'''<
            <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"
              CELLPADDING="3">
              <TR><TD ALIGN="LEFT"><FONT COLOR="{gg.RED}"
                POINT-SIZE="{SMALL_TEXT_FONT_SIZE}">{audience}</FONT></TD></TR>
              <TR><TD ALIGN="LEFT"><FONT COLOR="{gg.RED}"
                POINT-SIZE="{gg.TITLE_FONT_SIZE}"
                ><B>{benefit}</B></FONT></TD></TR>
            </TABLE>>''',
            pos=gv.fixed_position(x, 5.25),
        )

    # == AppRC sits inside the application boundary
    application = gv.add_fixed_panel_cluster(
        "application",
        "",
        color=gg.NEUTRAL_STROKE,
        fill=gg.NEUTRAL_GROUP_FILL,
        penwidth="2.6",
    )
    for node_id, x, y in (
        ("app_top_left", 4.40, 4.60),
        ("app_bottom_right", 12.70, 0.10),
    ):
        gv.add_fixed_frame_guard(
            application, node_id, pos=gv.fixed_position(x, y)
        )
    gv.add_fixed_html_node(
        application,
        "application_title",
        f'<<FONT COLOR="{gg.NEUTRAL_STROKE}" '
        f'POINT-SIZE="{gg.TITLE_FONT_SIZE}">'
        "<B>Your application</B></FONT>>",
        pos=gv.fixed_position(5.72, 4.25),
    )

    # > A pinned group backdrop retains the inner boundary in neato renders.
    gv.add_fixed_node(
        application,
        "apprc_component",
        "",
        pos=gv.fixed_position(6.55, 2.23),
        shape="box",
        style="rounded,filled",
        width="3.55",
        height="3.60",
        border_color=gg.BLUE,
        fill_color=gg.BLUE_GROUP_FILL,
        penwidth="1.8",
    )
    gv.add_fixed_html_node(
        application,
        "apprc_title",
        f'<<FONT COLOR="{gg.BLUE}" POINT-SIZE="22"><B>AppRC</B></FONT>>',
        pos=gv.fixed_position(6.55, 3.66),
    )
    for node_id, title, y, color in (
        ("settings", "Layered settings", 2.68, gg.BLUE),
        ("storage_selection", "Named storage", 1.78, gg.GREEN),
        ("terminal", "CLI + terminal editor", 0.86, gg.ORANGE),
    ):
        application.attr("node", fontcolor=color)
        gv.add_fixed_text_box(
            application,
            node_id,
            title,
            pos=gv.fixed_position(6.55, y),
            border_color=color,
            fill_color=FEATURE_BOX_FILL,
            title_font_size="14",
        )
    application.attr("node", fontcolor=gg.NEUTRAL_STROKE)
    gv.add_fixed_html_node(
        application,
        "app_code",
        f'''<
        <TABLE BORDER="1" COLOR="{gg.NEUTRAL_STROKE}"
          BGCOLOR="{gg.NEUTRAL_GROUP_FILL}" CELLBORDER="0"
          CELLSPACING="0" CELLPADDING="8" STYLE="rounded">
          <TR><TD><FONT POINT-SIZE="{gg.TITLE_FONT_SIZE}"
            ><B>Your app code</B></FONT></TD></TR>
          <TR><TD PORT="settings" ALIGN="LEFT"><FONT COLOR="{gg.NEUTRAL_STROKE}"
            POINT-SIZE="{SMALL_TEXT_FONT_SIZE}"
            >• Typed settings</FONT></TD></TR>
          <TR><TD PORT="root" ALIGN="LEFT"><FONT COLOR="{gg.NEUTRAL_STROKE}"
            POINT-SIZE="{SMALL_TEXT_FONT_SIZE}"
            >• Persistent data</FONT></TD></TR>
        </TABLE>>''',
        pos=gv.fixed_position(10.95, 2.32),
    )
    graph.subgraph(application)

    gv.connect_fixed_arrow(
        graph,
        "storage_selection:n",
        "settings:s",
        color=gg.BLUE,
        penwidth="1.7",
    )
    for tail, head, label, x, y in (
        (
            "settings:e",
            "app_code:settings:w",
            "values + sources",
            9.20,
            2.92,
        ),
        (
            "storage_selection:e",
            "app_code:root:w",
            "data root",
            9.20,
            2.04,
        ),
    ):
        gv.connect_fixed_arrow(
            graph,
            tail,
            head,
            color=gg.NEUTRAL_STROKE,
            penwidth="1.7",
        )
        gv.add_fixed_html_node(
            graph,
            f"{tail.split(':')[0]}_output_label",
            edge_badge(label, color=gg.NEUTRAL_STROKE),
            pos=gv.fixed_position(x, y),
        )

    # == Settings sources ordered from lowest to highest priority
    gv.add_fixed_label(
        graph,
        "precedence_heading",
        "Settings precedence",
        pos=gv.fixed_position(1.50, 5.05),
        font_size=gg.TITLE_FONT_SIZE,
        color=gg.NEUTRAL_STROKE,
    )
    layers = (
        (
            "defaults_file",
            "apprc.defaults.env",
            0.25,
            gg.BLUE,
            gg.BLUE_GROUP_FILL,
            "note",
        ),
        (
            "user_file",
            "apprc.user.env",
            1.25,
            gg.ORANGE,
            gg.ORANGE_GROUP_FILL,
            "note",
        ),
        (
            "storage_file",
            "apprc.storage.env",
            2.25,
            gg.GREEN,
            gg.GREEN_GROUP_FILL,
            "note",
        ),
        (
            "explicit_files",
            "Extra .env files",
            3.25,
            gg.PURPLE,
            gg.PURPLE_GROUP_FILL,
            "note",
        ),
        (
            "environment",
            "Shell environment",
            4.25,
            gg.PURPLE,
            gg.PURPLE_GROUP_FILL,
            "box",
        ),
    )
    for node_id, label, y, color, fill, shape in layers:
        gv.add_fixed_node(
            graph,
            node_id,
            label,
            pos=gv.fixed_position(1.50, y),
            shape=shape,
            width="2.60",
            height="0.56",
            border_color=color,
            fill_color=fill,
            font_color=color,
            font_size=SMALL_TEXT_FONT_SIZE,
            penwidth="2" if node_id == "environment" else "1.3",
        )
    # > Precedence arrows and badges inherit the lower source's color.
    for lower, upper in zip(layers, layers[1:]):
        gv.connect_fixed_arrow(
            graph,
            f"{lower[0]}:n",
            f"{upper[0]}:s",
            color=lower[3],
            penwidth="1.7",
        )
        gv.add_fixed_html_node(
            graph,
            f"{lower[0]}_precedence_label",
            edge_badge("overridden by", color=lower[3]),
            pos=gv.fixed_position(2.24, (lower[2] + upper[2]) / 2),
        )
    gv.connect_fixed_arrow(
        graph,
        "environment:e",
        "settings:w",
        color=gg.BLUE,
        penwidth="1.7",
    )
    gv.add_fixed_html_node(
        graph,
        "resolution_label",
        edge_badge("resolve", color=gg.BLUE),
        pos=gv.fixed_position(4.07, 3.88),
    )

    # == Directories use the same semantic colors as their config files
    for node_id, label, x, color, fill in (
        (
            "app_package",
            "App package\nInstalled code",
            1.50,
            gg.BLUE,
            gg.BLUE_GROUP_FILL,
        ),
        (
            "apprc_directory",
            "AppRC directory\napprc.toml",
            5.40,
            gg.ORANGE,
            gg.ORANGE_GROUP_FILL,
        ),
        (
            "selected_storage",
            "Selected storage\nApp data",
            10.65,
            gg.GREEN,
            gg.GREEN_GROUP_FILL,
        ),
    ):
        gv.add_fixed_node(
            graph,
            node_id,
            label,
            pos=gv.fixed_position(x, -1.55),
            shape="folder",
            width="2.70",
            height="0.90",
            border_color=color,
            fill_color=fill,
            font_color=color,
            font_size=SMALL_TEXT_FONT_SIZE,
            penwidth="2",
        )

    # > Nested routes keep file-location links out of the application frame.
    routes = (
        (
            "defaults_file:s",
            "app_package:n",
            gg.BLUE,
            (),
        ),
        (
            "user_file:e",
            "apprc_directory:n",
            gg.ORANGE,
            ((3.30, 1.25), (3.30, -0.55), (5.40, -0.55)),
        ),
        (
            "storage_file:e",
            "selected_storage:w",
            gg.GREEN,
            ((3.85, 2.25), (3.85, -0.25), (9.05, -0.25), (9.05, -1.55)),
        ),
    )
    for source, target, color, bends in routes:
        route_nodes = []
        for i, (x, y) in enumerate(bends):
            node_id = f"{source.split(':')[0]}_location_{i}"
            gv.add_fixed_frame_guard(
                graph, node_id, pos=gv.fixed_position(x, y)
            )
            route_nodes.append(node_id)
        path = (source, *route_nodes, target)
        for tail, head in zip(path, path[1:]):
            gv.connect_fixed_line(
                graph,
                tail,
                head,
                color=color,
                penwidth="1.4",
                style="dashed",
            )
    gv.add_fixed_label(
        graph,
        "location_legend",
        "Dashed lines: stored in",
        pos=gv.fixed_position(5.50, -2.32),
        font_size=SMALL_TEXT_FONT_SIZE,
        color=gg.NEUTRAL_STROKE,
    )
    gv.connect_fixed_arrow(
        graph,
        "app_code:s",
        "selected_storage:n",
        color=gg.GREEN,
        direction="both",
        penwidth="1.7",
    )
    return graph


def export_figure(
    output_dir: Path | None = None,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Render the figure as a transparent SVG asset.

    :param output_dir: Optional output directory override.
    :return: SVG paths and an empty PNG path tuple.
    """
    return export_svg_only(
        build_graph(),
        FIGURE_NAME,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        output_dir=output_dir,
        bounds=FIGURE_BOUNDS,
        svg_bounds=SVG_BOUNDS,
    )


if __name__ == "__main__":
    raise SystemExit(
        gg.run_single_graph_cli(
            export_figure,
            description="Render the AppRC configuration overview.",
        )
    )
