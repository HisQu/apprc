"""Render the AppRC layer-cake precedence figure."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-abstract-layer-cake"


def build_graph() -> Digraph:
    """Build the dotenv precedence and bootstrap figure.

    :return: Configured Graphviz diagram.
    """

    figure = gg.diagram("apprc_abstract_layer_cake", direction="TB")
    figure.graph.attr(nodesep="0.18", ranksep="0.24")

    with figure.group(
        "precedence",
        "Dotenv and environment precedence",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
    ) as layers:
        layers.text(
            "base_layers",
            "Base layers",
            "apprc.defaults.env",
            "apprc.user.env",
            "lower precedence",
            border_color=gg.GREEN,
        )
        layers.text(
            "selected_layers",
            "Selected layers",
            "apprc.storage.env",
            "--env-file",
            "os.environ",
            "higher precedence",
            border_color=gg.GREEN,
        )

    with figure.group(
        "storage_selection",
        "Storage selector",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
    ) as selector:
        selector.text(
            "selector_sources",
            "Selector sources",
            "--storage",
            "MYAPP_STORAGE",
            "apprc.toml",
            border_color=gg.ORANGE,
        )
        selector.text(
            "selected_storage",
            "Selected storage",
            "registered name",
            "root from registry",
            "runtime owner",
            border_color=gg.ORANGE,
        )

    with figure.group(
        "runtime_output",
        "Runtime output",
        color=gg.PURPLE,
        fill=gg.PURPLE_GROUP_FILL,
    ) as output:
        output.classifier(
            "effective_config",
            "Effective config",
            "merged values",
            "typed config",
            "doctor + editor",
            stereotype="runtime",
            kind="interface",
            border_color=gg.PURPLE,
        )

    figure.edge(
        "base_layers",
        "selected_layers",
        "higher",
        color=gg.GREEN,
    )
    figure.edge(
        "selected_layers",
        "effective_config",
        "merge",
        color=gg.GREEN,
    )
    figure.edge(
        "selector_sources",
        "selected_storage",
        "select",
        color=gg.ORANGE,
    )
    figure.edge(
        "selected_storage",
        "selected_layers",
        "storage",
        color=gg.ORANGE,
    )
    figure.edge(
        "selected_storage",
        "effective_config",
        "path",
        color=gg.PURPLE,
        dashed=True,
        constraint=False,
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
    )


def main() -> int:
    """Run the command-line exporter.

    :return: Process exit code.
    """

    return gg.run_single_graph_cli(
        export_figure,
        description="Render the AppRC layer-cake precedence figure.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
