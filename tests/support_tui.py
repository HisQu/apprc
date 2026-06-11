"""Shared assertions for Textual/Rich rendering tests."""

from __future__ import annotations

# == 3rd Party ===============================
from rich.text import Text


def text_has_span(text: Text, literal: str, style: str) -> bool:
    """Return whether a literal has the expected style span.

    :param text: Rich text to inspect.
    :param literal: Plain substring expected inside ``text``.
    :param style: Rich style name expected for the substring.
    :return: Whether any span covers the whole literal.
    """
    start = text.plain.index(literal)
    end = start + len(literal)
    return any(
        span.start <= start and end <= span.end and span.style == style
        for span in text.spans
    )
