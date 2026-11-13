"""Deterministic archives shared by project snapshots and native products."""

from __future__ import annotations

import io
from collections.abc import Collection, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def _deterministic_zip(
    entries: Iterable[tuple[str, bytes]], *, executables: Collection[str] = ()
) -> bytes:
    """Serialize archive entries with stable ordering and file metadata.

    :param entries: Archive paths and exact file contents.
    :param executables: Regular-file addresses whose executable bits are retained.
    :return: Deterministic in-memory ZIP bytes.
    """
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for address, content in sorted(entries):
            info = ZipInfo(address, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if address in executables else 0o100644) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()
