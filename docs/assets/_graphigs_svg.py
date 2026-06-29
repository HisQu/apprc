"""Shared Graphigs export helpers for AppRC docs figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from graphviz.graphs import Digraph

import graphigs as gg
from graphigs.figure_contract import FigureBounds
from graphigs.figure_contract import FigureSizePolicy
from graphigs.figure_contract import SvgDisplayBounds


def export_svg_only(
    graph: Digraph,
    figure_name: str,
    *,
    default_output_dir: Path,
    output_dir: Path | None = None,
    bounds: FigureBounds | None = None,
    svg_bounds: SvgDisplayBounds | None = None,
    size_policy: FigureSizePolicy | None = None,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Render one Graphigs figure while keeping AppRC assets SVG-only.

    Graphigs writes SVG and PNG as a pair. AppRC docs reference SVG files only,
    so this helper removes the temporary PNG after the normalized SVG has been
    written.

    :param graph: Diagram to render.
    :param figure_name: Base filename without extension.
    :param default_output_dir: Owning docs asset directory.
    :param output_dir: Optional output directory override.
    :param bounds: Optional physical output contract override.
    :param svg_bounds: Optional browser display contract override.
    :param size_policy: Optional Graphigs figure size policy override.
    :return: Generated SVG paths and an empty PNG path tuple.
    """

    resolved_output_dir = (
        default_output_dir if output_dir is None else output_dir
    )
    if bounds is None and svg_bounds is None and size_policy is None:
        svg_paths, png_paths = gg.export_single_graph_figure(
            graph,
            figure_name,
            default_output_dir=default_output_dir,
            output_dir=output_dir,
        )
    else:
        render_kwargs: dict[str, Any] = {}
        if bounds is not None:
            graph.attr(size=bounds.graphviz_size)
            render_kwargs["bounds"] = bounds
        if svg_bounds is not None:
            render_kwargs["svg_bounds"] = svg_bounds
        if size_policy is not None:
            render_kwargs["size_policy"] = size_policy
        svg_path, png_path = gg.render_figure(
            graph,
            figure_name,
            output_dir=resolved_output_dir,
            **render_kwargs,
        )
        svg_paths = (svg_path,)
        png_paths = (png_path,)
    for png_path in png_paths:
        png_path.unlink(missing_ok=True)
    return svg_paths, ()
