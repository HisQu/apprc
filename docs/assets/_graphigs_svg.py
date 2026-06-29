"""Shared Graphigs export helpers for AppRC docs figures."""

from __future__ import annotations

from pathlib import Path

from graphviz.graphs import Digraph

import graphigs as gg


def export_svg_only(
    graph: Digraph,
    figure_name: str,
    *,
    default_output_dir: Path,
    output_dir: Path | None = None,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Render one Graphigs figure while keeping AppRC assets SVG-only.

    Graphigs writes SVG and PNG as a pair. AppRC docs reference SVG files only,
    so this helper removes the temporary PNG after the normalized SVG has been
    written.

    :param graph: Diagram to render.
    :param figure_name: Base filename without extension.
    :param default_output_dir: Owning docs asset directory.
    :param output_dir: Optional output directory override.
    :return: Generated SVG paths and an empty PNG path tuple.
    """

    svg_paths, png_paths = gg.export_single_graph_figure(
        graph,
        figure_name,
        default_output_dir=default_output_dir,
        output_dir=output_dir,
    )
    for png_path in png_paths:
        png_path.unlink(missing_ok=True)
    return svg_paths, ()
