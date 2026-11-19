"""Read the verified product embedded in a native setup executable."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from apprc.distribution.models import NativeBinding, read_native_bindings


def read_products(
    executable: Path,
    expected_size: object,
    expected_digest: object,
    *,
    include_project: bool = False,
) -> tuple[NativeBinding, NativeBinding | None, bytes | None]:
    """Verify the appended archive and optionally load its project snapshot."""
    if (
        type(expected_size) is not int
        or expected_size <= 0
        or not isinstance(expected_digest, str)
        or len(expected_digest) != 64
    ):
        raise RuntimeError(
            "Native manager archive verification metadata is unavailable."
        )
    size = executable.stat().st_size
    start = size - expected_size
    if start < 0:
        raise RuntimeError("Native manager archive is truncated.")
    digest = hashlib.sha256()
    with executable.open("rb") as stream:
        stream.seek(start)
        for chunk in iter(lambda: stream.read(131072), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise RuntimeError("Native manager archive changed after loading.")
    with zipfile.ZipFile(executable) as archive:
        binding, preview = read_native_bindings(archive)
        project = archive.read("project.zip") if include_project else None
    if (
        project is not None
        and hashlib.sha256(project).hexdigest() != binding.source.digest
    ):
        raise RuntimeError(
            "Embedded project snapshot differs from its binding."
        )
    return binding, preview, project
