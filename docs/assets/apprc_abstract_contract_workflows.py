"""Render the AppRC one-contract, many-workflows abstract."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg

from _graphigs_svg import export_svg_only

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
FIGURE_NAME = "apprc-abstract-contract-workflows"


def build_graph() -> Digraph:
    """Build the one-contract, many-workflows explanation figure.

    :return: Configured Graphviz diagram.
    """

    figure = gg.diagram("apprc_abstract_contract_workflows", direction="TB")
    figure.graph.attr(nodesep="0.26", ranksep="0.32")

    with figure.group(
        "declared_contract",
        "Declared contract",
        color=gg.BLUE,
        fill=gg.BLUE_GROUP_FILL,
    ) as contract:
        contract.classifier(
            "contract_schema",
            "Config classes",
            "EnvConfig",
            "env_owner",
            "env_field",
            stereotype="schema",
            kind="class",
            border_color=gg.BLUE,
        )
        contract.classifier(
            "kit",
            "AppConfigKit",
            "capabilities",
            stereotype="app spec",
            kind="interface",
            border_color=gg.BLUE,
        )

    with figure.group(
        "apprc_core",
        "AppRC metadata model",
        color=gg.NEUTRAL_STROKE,
        fill=gg.NEUTRAL_GROUP_FILL,
    ) as core:
        core.text(
            "owner_metadata",
            "Owner metadata",
            "env prefixes",
            "runtime paths",
            "storage roots",
            border_color=gg.NEUTRAL_STROKE,
        )
        core.text(
            "field_metadata",
            "Field metadata",
            "env keys",
            "defaults",
            "edit policy",
            border_color=gg.NEUTRAL_STROKE,
        )
        core.text(
            "capability_metadata",
            "Capability metadata",
            "app-wide",
            "storage",
            "named index",
            border_color=gg.NEUTRAL_STROKE,
        )

    with figure.group(
        "runtime_model",
        "Runtime model",
        color=gg.GREEN,
        fill=gg.GREEN_GROUP_FILL,
    ) as runtime:
        runtime.text(
            "resolution",
            "Layer resolution",
            "dotenv",
            "storage",
            "env",
            border_color=gg.GREEN,
        )
        runtime.classifier(
            "effective_config",
            "Runtime config",
            "typed EnvConfig",
            "zero-write reads",
            stereotype="runtime",
            kind="interface",
            border_color=gg.GREEN,
        )

    with figure.group(
        "generated_surfaces",
        "Generated surfaces",
        color=gg.ORANGE,
        fill=gg.ORANGE_GROUP_FILL,
    ) as surfaces:
        surfaces.text(
            "config_cli",
            "Config CLI",
            "setup",
            "set",
            border_color=gg.ORANGE,
        )
        surfaces.text(
            "diagnostics",
            "Doctor",
            "paths",
            "provenance",
            border_color=gg.PURPLE,
        )
        surfaces.text(
            "textual_editor",
            "Editor",
            "edit",
            "save",
            border_color=gg.PURPLE,
        )

    figure.edge("contract_schema", "owner_metadata", "derive", color=gg.BLUE)
    figure.edge("contract_schema", "field_metadata", "derive", color=gg.BLUE)
    figure.edge("kit", "capability_metadata", "select", color=gg.BLUE)
    figure.edge("owner_metadata", "resolution", "resolve", color=gg.GREEN)
    figure.edge("capability_metadata", "resolution", "layers", color=gg.GREEN)
    figure.edge("field_metadata", "effective_config", "bind", color=gg.GREEN)
    figure.edge("resolution", "effective_config", "merge", color=gg.GREEN)
    figure.edge(
        "capability_metadata", "config_cli", "generate", color=gg.ORANGE
    )
    figure.edge("owner_metadata", "diagnostics", "inspect", color=gg.PURPLE)
    figure.edge("field_metadata", "textual_editor", "edit", color=gg.PURPLE)
    figure.edge(
        "effective_config",
        "diagnostics",
        "explain",
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
        description="Render the AppRC contract-workflows explanation figure.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
