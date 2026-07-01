"""Render the AppRC storage and config location map."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg
import graphigs.graphviz as gv
from graphigs.figure_contract import FigureBounds
from graphigs.figure_contract import SvgDisplayBounds
from graphigs.graphviz.labels import classifier_label
from graphigs.graphviz.labels import edge_label
from graphigs.graphviz.models import ClassifierNode

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-storage-config-locations"
LOCATION_MAP_BOUNDS = FigureBounds(
    page_width_mm=390.0,
    page_height_mm=230.0,
    page_margin_mm=16.0,
    max_height_fraction=0.88,
)
LOCATION_MAP_SVG_BOUNDS = SvgDisplayBounds(
    display_width_px=1280,
    max_display_height_px=680,
)


def build_graph() -> Digraph:
    """Build the dotenv location and capability-shape figure.

    :return: Configured Graphviz diagram.
    """

    figure = gg.fixed_diagram("apprc_storage_config_locations", direction="LR")

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
        "external dotenv",
        ("--env-file", "one or more files", "all kits"),
        pos=gv.fixed_position(4.65, 2.65),
        border_color=gg.PURPLE,
    )
    gv.add_fixed_text_box(
        startup,
        "shell_env",
        "process env",
        ("os.environ", "parent process", "runtime-only input"),
        pos=gv.fixed_position(6.55, 2.65),
        border_color=gg.PURPLE,
    )
    gv.add_fixed_text_box(
        startup,
        "storage_choice",
        "storage choice",
        (
            "--storage / <APP>_STORAGE",
            "name: project-a",
            "path: /data/project-b",
        ),
        pos=gv.fixed_position(8.95, 2.65),
        border_color=gg.PURPLE,
    )
    figure.graph.subgraph(startup)

    runtime_read = gv.add_fixed_panel_cluster(
        "runtime_read",
        "",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
        margin="18",
    )
    gv.add_fixed_text_box(
        runtime_read,
        "read_stack",
        "read at startup",
        (
            "defaults: .env.shared",
            "app-wide: .env.apprc-app",
            "storage: chosen folder",
            "explicit: --env-file",
            "process: os.environ",
        ),
        pos=gv.fixed_position(11.45, 0.80),
        border_color=gg.GREEN,
        penwidth="2",
    )
    _runtime_card(
        runtime_read,
        "runtime_output",
        pos=gv.fixed_position(11.45, -0.95),
    )
    figure.graph.subgraph(runtime_read)

    installed = gv.add_fixed_panel_cluster(
        "installed",
        "",
        color=gg.BLUE,
        fill=gg.BLUE_GROUP_FILL,
        margin="18",
    )
    _dotenv_card(
        installed,
        "shared_env",
        ".env.shared",
        ("packaged defaults", "used by: all kits"),
        pos=gv.fixed_position(1.25, 0.65),
        color=gg.BLUE,
    )
    gv.add_fixed_text_box(
        installed,
        "package",
        "myapp package",
        ("installed code", "read-only package"),
        pos=gv.fixed_position(1.25, -0.95),
        border_color=gg.BLUE,
    )
    figure.graph.subgraph(installed)

    user_config = gv.add_fixed_panel_cluster(
        "user_config",
        "",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
        margin="18",
    )
    _dotenv_card(
        user_config,
        "app_wide_env",
        ".env.apprc-app",
        ("app-wide settings", "app-wide kits", "optional: storage_only"),
        pos=gv.fixed_position(8.95, 0.65),
        color=gg.ORANGE,
    )
    _toml_card(
        user_config,
        "address_book",
        "<app>.apprc.toml",
        ("storage address book", "example name -> folder"),
        pos=gv.fixed_position(8.95, -0.95),
    )
    figure.graph.subgraph(user_config)

    storages = gv.add_fixed_panel_cluster(
        "storages",
        "",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
        margin="18",
    )
    project_a = gv.add_fixed_panel_cluster(
        "project_a",
        "example: project-a",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
        margin="12",
    )
    _storage_env_card(
        project_a,
        "project_a_env",
        "inside /data/project-a",
        pos=gv.fixed_position(4.65, 0.65),
    )
    gv.add_fixed_text_box(
        project_a,
        "project_a_data",
        "storage data",
        ("/data/project-a", "app data"),
        pos=gv.fixed_position(4.65, -0.85),
        border_color=gg.GREEN,
    )
    storages.subgraph(project_a)

    project_b = gv.add_fixed_panel_cluster(
        "project_b",
        "example: project-b",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
        margin="12",
    )
    _storage_env_card(
        project_b,
        "project_b_env",
        "inside /data/project-b",
        pos=gv.fixed_position(6.75, 0.65),
    )
    gv.add_fixed_text_box(
        project_b,
        "project_b_data",
        "storage data",
        ("/data/project-b", "app data"),
        pos=gv.fixed_position(6.75, -0.85),
        border_color=gg.GREEN,
    )
    storages.subgraph(project_b)
    figure.graph.subgraph(storages)

    gv.add_fixed_label(
        figure.graph,
        "startup_label",
        "Startup inputs",
        pos=gv.fixed_position(6.55, 3.60),
        color=gg.PURPLE,
    )
    gv.add_fixed_label(
        figure.graph,
        "runtime_read_label",
        "Runtime read",
        pos=gv.fixed_position(11.45, 1.95),
        color=gg.GREEN,
    )
    gv.add_fixed_label(
        figure.graph,
        "installed_label",
        "Installed app package",
        pos=gv.fixed_position(1.25, 1.88),
        color=gg.BLUE,
    )
    gv.add_fixed_label(
        figure.graph,
        "user_config_label",
        "User config folder",
        pos=gv.fixed_position(8.95, 1.88),
        color=gg.ORANGE,
    )
    gv.add_fixed_label(
        figure.graph,
        "storages_label",
        "Storage folders",
        pos=gv.fixed_position(5.70, 1.88),
        color=gg.GREEN,
    )

    _arrow(
        figure.graph,
        "package",
        "shared_env",
        "ships",
        gg.BLUE,
        1.28,
        -0.22,
        tail_port="n",
        head_port="s",
    )
    _routed_arrow(
        figure.graph,
        "storage_choice",
        "address_book",
        "name lookup",
        gg.PURPLE,
        9.38,
        1.20,
        route_points=((9.45, 1.45),),
        tail_port="s",
        head_port="n",
    )
    _routed_arrow(
        figure.graph,
        "address_book",
        "project_a_data",
        ("saved", "name"),
        gg.GREEN,
        7.00,
        -1.55,
        route_points=((8.95, -1.62), (4.65, -1.62)),
        tail_port="s",
        head_port="s",
    )
    _routed_arrow(
        figure.graph,
        "storage_choice",
        "project_b_env",
        ("direct", "path"),
        gg.GREEN,
        7.92,
        1.55,
        route_points=((6.75, 1.52),),
        tail_port="s",
        head_port="n",
    )
    _arrow(
        figure.graph,
        "read_stack",
        "runtime_output",
        "builds",
        gg.GREEN,
        11.48,
        -0.08,
        tail_port="s",
        head_port="n",
    )
    return figure.graph


def _dotenv_card(
    graph: Digraph,
    node_id: str,
    title: str,
    members: tuple[str, ...],
    *,
    pos: str,
    color: str,
) -> None:
    """Add one fixed Graphigs classifier card for a dotenv file.

    :param graph: Graph or cluster receiving the card.
    :param node_id: DOT identifier for the card.
    :param title: Dotenv filename.
    :param members: Body rows describing role and kit use.
    :param pos: Fixed Graphviz position.
    :param color: Border color matching the owning location group.
    :return: None.
    """

    _classifier_card(
        graph,
        node_id,
        ClassifierNode(
            title=title,
            stereotype="dotenv",
            members=members,
            kind="class",
            border_color=color,
            border_width=2,
        ),
        pos=pos,
    )


def _storage_env_card(
    graph: Digraph,
    node_id: str,
    location: str,
    *,
    pos: str,
) -> None:
    """Add one storage-local dotenv classifier card.

    :param graph: Graph or cluster receiving the card.
    :param node_id: DOT identifier for the card.
    :param location: Short text naming the storage folder.
    :param pos: Fixed Graphviz position.
    :return: None.
    """

    _dotenv_card(
        graph,
        node_id,
        ".env.apprc-storage",
        ("storage-local settings", location, "storage kits"),
        pos=pos,
        color=gg.GREEN,
    )


def _toml_card(
    graph: Digraph,
    node_id: str,
    title: str,
    members: tuple[str, ...],
    *,
    pos: str,
) -> None:
    """Add one fixed Graphigs classifier card for the TOML address book.

    :param graph: Graph or cluster receiving the card.
    :param node_id: DOT identifier for the card.
    :param title: TOML filename.
    :param members: Body rows describing role and kit use.
    :param pos: Fixed Graphviz position.
    :return: None.
    """

    _classifier_card(
        graph,
        node_id,
        ClassifierNode(
            title=title,
            stereotype="toml config",
            members=members,
            kind="interface",
            border_color=gg.NEUTRAL_STROKE,
            border_width=2,
        ),
        pos=pos,
    )


def _runtime_card(graph: Digraph, node_id: str, *, pos: str) -> None:
    """Add the runtime config output classifier card.

    :param graph: Graph or cluster receiving the card.
    :param node_id: DOT identifier for the card.
    :param pos: Fixed Graphviz position.
    :return: None.
    """

    _classifier_card(
        graph,
        node_id,
        ClassifierNode(
            title="runtime config",
            stereotype="output",
            members=("EnvConfig", "merged at startup"),
            kind="interface",
            border_color=gg.GREEN,
            border_width=2,
        ),
        pos=pos,
    )


def _classifier_card(
    graph: Digraph,
    node_id: str,
    spec: ClassifierNode,
    *,
    pos: str,
) -> None:
    """Place one Graphigs classifier label at a fixed coordinate.

    :param graph: Graph or cluster receiving the card.
    :param node_id: DOT identifier for the card.
    :param spec: Graphigs classifier node specification.
    :param pos: Fixed Graphviz position.
    :return: None.
    """

    gv.add_fixed_html_node(graph, node_id, classifier_label(spec), pos=pos)


def _arrow(
    graph: Digraph,
    tail: str,
    head: str,
    label: str | tuple[str, ...] | None,
    color: str,
    label_x: float,
    label_y: float,
    *,
    dashed: bool = False,
    tail_port: str | None = None,
    head_port: str | None = None,
) -> None:
    """Draw one fixed Graphigs arrow with a standard edge-label badge.

    :param graph: Graph receiving the edge and badge.
    :param tail: Source node id.
    :param head: Target node id.
    :param label: Edge label text, or ``None`` for an unlabeled arrow.
    :param color: Edge and badge color.
    :param label_x: Label x coordinate.
    :param label_y: Label y coordinate.
    :param dashed: Whether the arrow should use a dashed stroke.
    :param tail_port: Optional Graphviz compass port for the tail.
    :param head_port: Optional Graphviz compass port for the head.
    :return: None.
    """

    _edge_segment(
        graph,
        tail,
        head,
        color=color,
        dashed=dashed,
        direction="forward",
        tail_port=tail_port,
        head_port=head_port,
    )
    if label is None:
        return
    gv.add_fixed_html_node(
        graph,
        f"{tail}_{head}_label",
        edge_label(label, color=color),
        pos=gv.fixed_position(label_x, label_y),
    )


def _routed_arrow(
    graph: Digraph,
    tail: str,
    head: str,
    label: str | tuple[str, ...] | None,
    color: str,
    label_x: float,
    label_y: float,
    *,
    route_points: tuple[tuple[float, float], ...],
    dashed: bool = False,
    tail_port: str | None = None,
    head_port: str | None = None,
) -> None:
    """Draw one arrow through invisible fixed points.

    :param graph: Graph receiving route points, edge segments, and badge.
    :param tail: Source node id.
    :param head: Target node id.
    :param label: Edge label text, or ``None`` for an unlabeled arrow.
    :param color: Edge and badge color.
    :param label_x: Label x coordinate.
    :param label_y: Label y coordinate.
    :param route_points: Fixed bend points between tail and head.
    :param dashed: Whether the arrow should use a dashed stroke.
    :param tail_port: Optional Graphviz compass port for the tail.
    :param head_port: Optional Graphviz compass port for the head.
    :return: None.
    """

    route_node_ids = tuple(
        f"{tail}_{head}_route_{index}"
        for index, _point in enumerate(route_points)
    )
    for node_id, (x, y) in zip(route_node_ids, route_points, strict=True):
        _route_point(graph, node_id, x, y)

    path = (tail, *route_node_ids, head)
    for index, (segment_tail, segment_head) in enumerate(zip(path, path[1:])):
        is_first_segment = index == 0
        is_last_segment = index == len(path) - 2
        _edge_segment(
            graph,
            segment_tail,
            segment_head,
            color=color,
            dashed=dashed,
            direction="forward" if is_last_segment else "none",
            tail_port=tail_port if is_first_segment else None,
            head_port=head_port if is_last_segment else None,
        )

    if label is None:
        return
    gv.add_fixed_html_node(
        graph,
        f"{tail}_{head}_label",
        edge_label(label, color=color),
        pos=gv.fixed_position(label_x, label_y),
    )


def _route_point(graph: Digraph, node_id: str, x: float, y: float) -> None:
    """Place one invisible bend point for a fixed routed edge.

    :param graph: Graph receiving the point.
    :param node_id: DOT identifier for the point.
    :param x: Fixed x coordinate.
    :param y: Fixed y coordinate.
    :return: None.
    """

    graph.node(
        node_id,
        label="",
        fixedsize="true",
        height="0.01",
        pin="true",
        pos=gv.fixed_position(x, y),
        shape="point",
        style="invis",
        width="0.01",
    )


def _edge_segment(
    graph: Digraph,
    tail: str,
    head: str,
    *,
    color: str,
    dashed: bool,
    direction: str,
    tail_port: str | None = None,
    head_port: str | None = None,
) -> None:
    """Connect two nodes or route points with a fixed edge segment.

    :param graph: Graph receiving the edge.
    :param tail: Source node id.
    :param head: Target node id.
    :param color: Segment color.
    :param dashed: Whether the segment should use a dashed stroke.
    :param direction: Graphviz edge direction.
    :param tail_port: Optional Graphviz compass port for the tail.
    :param head_port: Optional Graphviz compass port for the head.
    :return: None.
    """

    graph.edge(
        _endpoint(tail, tail_port),
        _endpoint(head, head_port),
        arrowsize="0.70",
        color=color,
        constraint="false",
        dir=direction,
        penwidth="2.3",
        style="dashed" if dashed else "solid",
    )


def _endpoint(node_id: str, port: str | None) -> str:
    """Build a Graphviz node endpoint with an optional compass port.

    :param node_id: DOT node identifier.
    :param port: Optional Graphviz compass port.
    :return: Endpoint string for ``graph.edge``.
    """

    if port is None:
        return node_id
    return f"{node_id}:{port}"


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
