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
    """Connect settings resolution, optional capabilities, and reviewed edits.

    Paths and workspace selection remain separate. Source reads do not create
    directories; explicit settings management writes enabled preference files.

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
            <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">
              <TR><TD ALIGN="LEFT"><FONT COLOR="{gg.RED}"
                POINT-SIZE="{SMALL_TEXT_FONT_SIZE}">{audience}</FONT></TD></TR>
              <TR><TD ALIGN="LEFT"><FONT COLOR="{gg.RED}"
                POINT-SIZE="{gg.TITLE_FONT_SIZE}"><B>{benefit}</B></FONT></TD></TR>
            </TABLE>>''',
            pos=gv.fixed_position(x, 5.7),
        )

    # == Separate AppRC capabilities inside the application
    application = gv.add_fixed_panel_cluster(
        "application",
        "",
        color=gg.NEUTRAL_STROKE,
        fill=gg.NEUTRAL_GROUP_FILL,
        penwidth="2.6",
    )
    for node_id, x, y in (
        ("app_top_left", 4.2, 5.35),
        ("app_bottom_right", 13.15, -1.35),
    ):
        gv.add_fixed_frame_guard(
            application, node_id, pos=gv.fixed_position(x, y)
        )
    gv.add_fixed_html_node(
        application,
        "application_title",
        f'<<FONT COLOR="{gg.NEUTRAL_STROKE}" '
        f'POINT-SIZE="{gg.TITLE_FONT_SIZE}"><B>Your application</B></FONT>>',
        pos=gv.fixed_position(5.85, 4.95),
    )
    # > A pinned backdrop keeps the inner boundary visible in neato output.
    gv.add_fixed_node(
        application,
        "apprc_component",
        "",
        pos=gv.fixed_position(6.55, 1.65),
        shape="box",
        style="rounded,filled",
        width="3.7",
        height="5.6",
        border_color=gg.BLUE,
        fill_color=gg.BLUE_GROUP_FILL,
        penwidth="1.8",
    )
    gv.add_fixed_html_node(
        application,
        "apprc_title",
        f'<<FONT COLOR="{gg.BLUE}" POINT-SIZE="22"><B>AppRC</B></FONT>>',
        pos=gv.fixed_position(6.55, 4.1),
    )
    for node_id, title, detail, y, color in (
        ("resolved", "ResolvedConfig", "Snapshot + provenance", 3.2, gg.BLUE),
        (
            "paths",
            "Paths + Layout",
            "Optional config · appdata<BR/>cache · state",
            2.0,
            gg.GREEN,
        ),
        (
            "workspaces",
            "WorkspaceManager",
            "Optional registry / direct<BR/>workspaces",
            0.8,
            gg.GREEN,
        ),
        (
            "management",
            "ConfigManager",
            "Reviewed settings operations",
            -0.4,
            gg.ORANGE,
        ),
    ):
        gv.add_fixed_html_node(
            application,
            node_id,
            f'''<
            <TABLE BORDER="1" COLOR="{color}" BGCOLOR="{FEATURE_BOX_FILL}"
              CELLBORDER="0" CELLSPACING="0" CELLPADDING="8" STYLE="rounded">
              <TR><TD><FONT COLOR="{color}" POINT-SIZE="14"
                ><B>{title}</B></FONT></TD></TR>
              <TR><TD><FONT COLOR="{color}" POINT-SIZE="{SMALL_TEXT_FONT_SIZE}"
                >{detail}</FONT></TD></TR>
            </TABLE>>''',
            pos=gv.fixed_position(6.55, y),
        )
    app_rows = "".join(
        f'<TR><TD PORT="{port}" ALIGN="LEFT"><FONT '
        f'COLOR="{gg.NEUTRAL_STROKE}" POINT-SIZE="{SMALL_TEXT_FONT_SIZE}"'
        f">• {label}</FONT></TD></TR>"
        for port, label in (
            ("settings", "Typed settings"),
            ("paths", "AppPaths: enabled locations or None"),
            ("workspace", "Workspace selection (optional)"),
        )
    )
    gv.add_fixed_html_node(
        application,
        "app_code",
        f'''<
        <TABLE BORDER="1" COLOR="{gg.NEUTRAL_STROKE}"
          BGCOLOR="{gg.NEUTRAL_GROUP_FILL}" CELLBORDER="0"
          CELLSPACING="0" CELLPADDING="8" STYLE="rounded">
          <TR><TD><FONT POINT-SIZE="{gg.TITLE_FONT_SIZE}"
            ><B>Your app code</B></FONT></TD></TR>
          {app_rows}
        </TABLE>>''',
        pos=gv.fixed_position(11.0, 1.65),
    )
    graph.subgraph(application)

    # == Source inputs and optional settings interfaces
    for node_id, label, x, y, color, fill in (
        (
            "sources",
            "Enabled setting sources\nPackaged defaults · dotenv\nEnvironment",
            1.7,
            3.2,
            gg.BLUE,
            gg.BLUE_GROUP_FILL,
        ),
        (
            "preferences",
            "Enabled preference files\nUser / workspace, opt-in",
            1.7,
            -2.1,
            gg.ORANGE,
            gg.ORANGE_GROUP_FILL,
        ),
        (
            "interfaces",
            "Optional settings interfaces\nCLI · Textual · Gradio",
            6.55,
            -2.1,
            gg.ORANGE,
            gg.ORANGE_GROUP_FILL,
        ),
    ):
        gv.add_fixed_node(
            graph,
            node_id,
            label,
            pos=gv.fixed_position(x, y),
            shape="box",
            style="rounded,filled",
            width="3.2",
            height="0.9",
            border_color=color,
            fill_color=fill,
            font_color=color,
            font_size=SMALL_TEXT_FONT_SIZE,
            penwidth="1.7",
        )

    # == Reads, independent outputs, and explicit writes
    for tail, head, label, x, y, color in (
        ("sources:e", "resolved:w", "resolve()", 4.0, 3.55, gg.BLUE),
        (
            "resolved:e",
            "app_code:settings:w",
            "build(Settings)",
            9.0,
            3.45,
            gg.BLUE,
        ),
        ("paths:e", "app_code:paths:w", "paths()", 9.0, 2.55, gg.GREEN),
        (
            "workspaces:e",
            "app_code:workspace:w",
            "select / inspect",
            9.0,
            0.55,
            gg.GREEN,
        ),
        (
            "interfaces:n",
            "management:s",
            "inspect / edit",
            7.5,
            -1.55,
            gg.ORANGE,
        ),
        ("preferences:n", "sources:s", "when enabled", 1.7, 0.3, gg.BLUE),
    ):
        gv.connect_fixed_arrow(graph, tail, head, color=color, penwidth="1.7")
        gv.add_fixed_html_node(
            graph,
            f"{tail.split(':')[0]}_edge_label",
            edge_badge(label, color=color),
            pos=gv.fixed_position(x, y),
        )
    # > Keep the write route outside the frame and away from the read outputs.
    for node_id, x, y in (
        ("save_exit", 4.05, -0.4),
        ("save_turn", 4.05, -2.1),
    ):
        gv.add_fixed_frame_guard(graph, node_id, pos=gv.fixed_position(x, y))
    for tail, head in (
        ("management:w", "save_exit"),
        ("save_exit", "save_turn"),
    ):
        gv.connect_fixed_line(
            graph, tail, head, color=gg.ORANGE, penwidth="1.7"
        )
    gv.connect_fixed_arrow(
        graph,
        "save_turn",
        "preferences:e",
        color=gg.ORANGE,
        penwidth="1.7",
    )
    gv.add_fixed_html_node(
        graph,
        "save_label",
        edge_badge("reviewed save", color=gg.ORANGE),
        pos=gv.fixed_position(3.5, -1.1),
    )
    gv.add_fixed_label(
        graph,
        "read_only_note",
        "resolve() / paths()\ndo not create directories.",
        pos=gv.fixed_position(11.0, -1.95),
        font_size=SMALL_TEXT_FONT_SIZE,
        color=gg.NEUTRAL_STROKE,
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
