"""Windows executable version conversion."""

from __future__ import annotations

import re


def numeric_product_version(version: str) -> tuple[int, int, int, int] | None:
    """Convert a plain release version to the four Windows numeric fields.

    Prereleases and other nonnumeric versions cannot be represented without
    losing information. Return ``None`` so the caller can warn and retain the
    original launcher.

    :param version: Distribution version reported by the validated runtime.
    :return: Four numeric fields, or ``None`` when not exactly representable.
    """
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", version):
        return None
    parts = tuple(int(part) for part in version.split("."))
    if any(part > 65535 for part in parts):
        return None
    padded = (*parts, *(0 for _ in range(4 - len(parts))))
    return padded[0], padded[1], padded[2], padded[3]
