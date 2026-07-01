"""Human-facing provenance display helpers."""

from __future__ import annotations

# == Internal ================================
from apprc.runtime.provenance.model import ConfigProvenanceOrigin


def provenance_origin_label(origin: ConfigProvenanceOrigin) -> str:
    """Return a display label derived from a provenance origin literal.

    :param origin: Exact provenance origin literal.
    :return: Human-readable label derived without storing duplicate state.
    """
    return origin.replace("_", " ").capitalize()
