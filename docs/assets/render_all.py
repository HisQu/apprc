"""Render every generated AppRC documentation figure."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path

import apprc_abstract_contract_workflows
import apprc_abstract_layer_cake
import apprc_abstract_user_journey
import apprc_runtime_layers
import docs_reading_map

ExportFigure = Callable[
    [Path | None], tuple[tuple[Path, ...], tuple[Path, ...]]
]

FIGURE_EXPORTS: tuple[ExportFigure, ...] = (
    docs_reading_map.export_figure,
    apprc_runtime_layers.export_figure,
    apprc_abstract_contract_workflows.export_figure,
    apprc_abstract_user_journey.export_figure,
    apprc_abstract_layer_cake.export_figure,
)


def render_all_figures(
    output_dir: str | Path | None = None,
) -> tuple[Path, ...]:
    """Render all AppRC docs figures as SVG assets.

    :param output_dir: Optional directory override for generated SVG files.
    :return: Generated SVG paths.
    """

    resolved_output_dir = None if output_dir is None else Path(output_dir)
    generated_paths: list[Path] = []
    for export_figure in FIGURE_EXPORTS:
        svg_paths, _png_paths = export_figure(resolved_output_dir)
        generated_paths.extend(svg_paths)
    return tuple(generated_paths)


def build_parser() -> argparse.ArgumentParser:
    """Create the renderer command-line parser.

    :return: Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description="Render every AppRC documentation figure.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated SVG files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Render all figures and print their generated paths.

    :param argv: Optional argument vector.
    :return: Process exit code.
    """

    args = build_parser().parse_args(argv)
    for path in render_all_figures(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
