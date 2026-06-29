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

    figure = gg.diagram("apprc_abstract_layer_cake", direction="LR")
    figure.graph.attr(nodesep="0.20", ranksep="0.28")

    with figure.group(
        "precedence",
        "Dotenv and environment precedence",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
    ) as layers:
        layers.text(
            "layer_stack",
            "Layer stack",
            "lower: .env.shared",
            ".env.apprc-app",
            ".env.apprc-storage",
            "--env-file",
            "higher: os.environ",
            border_color=gg.GREEN,
        )

    with figure.group(
        "storage_selection",
        "Storage selector",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
    ) as selector:
        selector.text(
            "selector_inputs",
            "Selector inputs",
            "--storage",
            "MYAPP_STORAGE",
            "named index",
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
            "typed EnvConfig",
            "doctor + editor",
            stereotype="runtime",
            kind="interface",
            border_color=gg.PURPLE,
        )

    figure.edge(
        "layer_stack",
        "effective_config",
        ("merge", "higher wins"),
        color=gg.GREEN,
    )
    figure.edge(
        "selector_inputs",
        "effective_config",
        "select storage",
        color=gg.ORANGE,
    )
    figure.edge(
        "layer_stack",
        "selector_inputs",
        "lower precedence",
        color=gg.NEUTRAL_STROKE,
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
