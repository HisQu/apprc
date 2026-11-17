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


def versioned_executable(content: bytes, version: str) -> bytes:
    """Return a stamped Windows copy, warning and retaining bytes on failure.

    :param content: Original executable including its appended payload.
    :param version: Validated application distribution version.
    :return: Prepared executable bytes or the unchanged original.
    """
    import logging
    import os
    import struct
    import tempfile
    from pathlib import Path

    if os.name != "nt":
        return content
    try:
        numbers = numeric_product_version(version)
        if numbers is None:
            raise ValueError(
                f"version {version!r} cannot be represented numerically"
            )
        pe = struct.unpack_from("<I", content, 60)[0]
        if content[:2] != b"MZ" or content[pe : pe + 4] != b"PE\0\0":
            raise ValueError("unsupported executable format")
        (sections,) = struct.unpack_from("<H", content, pe + 6)
        (optional_size,) = struct.unpack_from("<H", content, pe + 20)
        optional = pe + 24
        (magic,) = struct.unpack_from("<H", content, optional)
        directories = optional + {0x10B: 96, 0x20B: 112}[magic]
        if any(struct.unpack_from("<II", content, directories + 32)):
            raise ValueError("signed executables are left unchanged")
        table = optional + optional_size
        end = max(
            struct.unpack_from("<I", content, optional + 60)[0],
            *(
                sum(struct.unpack_from("<II", content, table + index * 40 + 16))
                for index in range(sections)
            ),
        )
        if end > len(content):
            raise ValueError("invalid executable section bounds")
        overlay = content[end:]
        major, minor, patch, revision = numbers
        fixed = struct.pack(
            "<13I",
            0xFEEF04BD,
            0x10000,
            major << 16 | minor,
            patch << 16 | revision,
            major << 16 | minor,
            patch << 16 | revision,
            0x3F,
            0,
            0x40004,
            1,
            0,
            0,
            0,
        )
        key = "VS_VERSION_INFO\0".encode("utf-16le")
        header = struct.pack(
            "<HHH", 6 + len(key) + 2 + len(fixed), len(fixed), 0
        )
        resource = header + key + b"\0\0" + fixed
        import win32api

        with tempfile.TemporaryDirectory(prefix="apprc-version-") as staging:
            path = Path(staging) / "command.exe"
            path.write_bytes(content[:end])
            handle = win32api.BeginUpdateResource(str(path), False)
            try:
                win32api.UpdateResource(handle, 16, 1, resource, 0)
            except Exception:
                win32api.EndUpdateResource(handle, True)
                raise
            win32api.EndUpdateResource(handle, False)
            result = path.read_bytes() + overlay
            path.write_bytes(result)
            observed = win32api.GetFileVersionInfo(str(path), "\\")
            if (observed["ProductVersionMS"], observed["ProductVersionLS"]) != (
                major << 16 | minor,
                patch << 16 | revision,
            ):
                raise ValueError("product version read-back failed")
            return result
    except Exception as error:
        logging.getLogger(__name__).warning(
            "Windows executable version was not updated; installation continues: %s",
            error,
        )
        return content
