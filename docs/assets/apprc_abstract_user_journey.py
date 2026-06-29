"""Render the AppRC developer/operator journey abstract."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-abstract-user-journey"


def build_graph() -> Digraph:
    """Build the user journey graphical abstract.

    :return: Configured Graphviz diagram.
    """

    figure = gg.diagram("apprc_abstract_user_journey", direction="LR")
    figure.graph.attr(nodesep="0.18", ranksep="0.24")

    with figure.group(
        "developer",
        "App developer",
        color=gg.BLUE,
        fill=gg.BLUE_GROUP_FILL,
    ) as developer:
        developer.classifier(
            "config_contract",
            "Config contract",
            "EnvConfig",
            "@env_owner",
            "env_field",
            stereotype="declare",
            kind="class",
            border_color=gg.BLUE,
        )
        developer.classifier(
            "shipped_app",
            "Shipped config UX",
            "AppConfigKit",
            "bootstrap",
            "config CLI",
            stereotype="ship",
            kind="interface",
            border_color=gg.BLUE,
        )

    with figure.group(
        "operator",
        "App user / operator",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
    ) as operator:
        operator.text(
            "setup_and_doctor",
            "Setup + diagnose",
            "config paths",
            "config setup",
            "config doctor",
            border_color=gg.ORANGE,
        )
        operator.classifier(
            "runtime_app",
            "Runnable app",
            "config set",
            "config edit",
            "typed EnvConfig",
            stereotype="runtime",
            kind="interface",
            border_color=gg.GREEN,
        )

    figure.edge("config_contract", "shipped_app", "declare", color=gg.BLUE)
    figure.edge("shipped_app", "setup_and_doctor", "ship", color=gg.ORANGE)
    figure.edge(
        "setup_and_doctor",
        "runtime_app",
        ("configure", "run"),
        color=gg.GREEN,
    )
    figure.edge(
        "runtime_app",
        "setup_and_doctor",
        "inspect",
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
        description="Render the AppRC user journey graphical abstract.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
