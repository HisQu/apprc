"""Windows executable version conversion."""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from _win32typing import PyResourceId

_STAGE_SUFFIXES = (
    (".dev", ("dev",)),
    ("a", ("a", "alpha")),
    ("b", ("b", "beta")),
    ("rc", ("rc", "c", "pre", "preview")),
    ("", ()),
    (".post", ("post", "rev", "r")),
)
_STAGES = {
    alias: stage
    for stage, (_, aliases) in enumerate(_STAGE_SUFFIXES)
    for alias in aliases
}
_FINAL_STAGE = 4
_STAGE_WIDTH = 100
_SHORT_VERSION = re.compile(
    r"\s*v?(?P<release>[0-9]+(?:\.[0-9]+){0,2})"
    r"(?:(?:[-_.]?(?P<stage>"
    + "|".join(_STAGES)
    + r")[-_.]?(?P<serial>[0-9]*))|-(?P<post>[0-9]+))?\s*",
    re.IGNORECASE,
)
_FOUR_PART_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){3}")
_PRERELEASE = 0x02
_VERSION_TYPE = 16
_VERSION_NAME = 1
_NEUTRAL_LANGUAGE = 0
_STRING_LANG = 0x0409
_UNICODE_CODEPAGE = 1200
_STRING_TABLE = f"{_STRING_LANG:04x}{_UNICODE_CODEPAGE:04x}"

type _VersionNumbers = tuple[int, int, int, int]


def numeric_product_version(version: str) -> _VersionNumbers | None:
    """Project a supported PEP 440 version to the Windows numeric fields.

    Short release tuples use a fourth field for the stage and serial. Plain
    four-part releases keep their existing fourth component.

    :param version: Distribution version reported by the validated runtime.
    :return: Four numeric fields, or ``None`` when not exactly representable.
    """
    projection = _project_version(version)
    return projection[0] if projection is not None else None


def _project_version(version: str) -> tuple[_VersionNumbers, bool] | None:
    """Return the bounded numeric projection and native prerelease status."""
    short = _SHORT_VERSION.fullmatch(version)
    if short is None and not _FOUR_PART_VERSION.fullmatch(version):
        return None
    try:
        parts = tuple(
            map(int, (short["release"] if short else version).split("."))
        )
        serial = int(
            (short["serial"] or short["post"] or "0") if short else "0"
        )
    except ValueError:
        return None
    if any(part > 65535 for part in parts) or serial >= _STAGE_WIDTH:
        return None
    if short is None:
        major, minor, patch, revision = parts
        return (major, minor, patch, revision), False
    suffix = short["stage"]
    stage = (
        _STAGES[suffix.lower()]
        if suffix
        else _STAGES["post"]
        if short["post"]
        else _FINAL_STAGE
    )
    major, minor, patch = parts + (0,) * (3 - len(parts))
    return (
        major,
        minor,
        patch,
        stage * _STAGE_WIDTH + serial,
    ), stage < _FINAL_STAGE


def package_version_from_windows_number(parts: tuple[int, ...]) -> str | None:
    """Decode the stage form of a Windows version for release lookup.

    :param parts: Numeric components of the requested Windows version.
    :return: Package spelling if the stage form round-trips through the encoder.
    """
    if len(parts) != 4:
        return None
    major, minor, patch, revision = parts
    stage, serial = divmod(revision, _STAGE_WIDTH)
    if not 0 <= stage < len(_STAGE_SUFFIXES):
        return None
    suffix = _STAGE_SUFFIXES[stage][0]
    version = f"{major}.{minor}.{patch}"
    if suffix:
        version += f"{suffix}{serial}"
    return version if numeric_product_version(version) == parts else None


def _version_block(
    key: str,
    value: bytes = b"",
    *,
    text: bool = False,
    children: tuple[bytes, ...] = (),
) -> bytes:
    """Encode one DWORD-aligned Windows version-resource block."""
    key_bytes = (key + "\0").encode("utf-16le")
    body = key_bytes + b"\0" * (-(6 + len(key_bytes)) % 4) + value
    for child in children:
        body += b"\0" * (-(6 + len(body)) % 4) + child
    length = len(value) // 2 if text else len(value)
    return struct.pack("<HHH", 6 + len(body), length, int(text)) + body


def _version_resource(ms: int, ls: int, version: str, flags: int) -> bytes:
    """Build fixed numeric fields, PEP 440 strings, and their translation."""
    fixed = struct.pack(
        "<13I",
        0xFEEF04BD,
        0x10000,
        ms,
        ls,
        ms,
        ls,
        0x3F,
        flags,
        0x40004,
        1,
        0,
        0,
        0,
    )
    text = (version + "\0").encode("utf-16le")
    strings = _version_block(
        "StringFileInfo",
        text=True,
        children=(
            _version_block(
                _STRING_TABLE,
                text=True,
                children=(
                    _version_block("FileVersion", text, text=True),
                    _version_block("ProductVersion", text, text=True),
                ),
            ),
        ),
    )
    translation = _version_block(
        "VarFileInfo",
        text=True,
        children=(
            _version_block(
                "Translation",
                struct.pack("<HH", _STRING_LANG, _UNICODE_CODEPAGE),
            ),
        ),
    )
    return _version_block(
        "VS_VERSION_INFO", fixed, children=(strings, translation)
    )


def _fixed_version_fields(
    projection: tuple[_VersionNumbers, bool],
) -> tuple[int, int, int]:
    """Pack the projected number and prerelease flag for the resource."""
    (major, minor, patch, revision), prerelease = projection
    return (
        major << 16 | minor,
        patch << 16 | revision,
        _PRERELEASE if prerelease else 0,
    )


def version_resource_file(version: str) -> bytes | None:
    """Encode a linker input for a supported Windows executable version."""
    projection = _project_version(version)
    if projection is None:
        return None
    ms, ls, flags = _fixed_version_fields(projection)
    data = _version_resource(ms, ls, version, flags)
    # > The Win32 .res format starts with an empty ordinal resource.
    header = struct.Struct("<IIHHHHIHHII")
    marker = header.pack(0, header.size, 0xFFFF, 0, 0xFFFF, 0, 0, 0, 0, 0, 0)
    entry = header.pack(
        len(data),
        header.size,
        0xFFFF,
        _VERSION_TYPE,
        0xFFFF,
        _VERSION_NAME,
        0,
        0,
        _NEUTRAL_LANGUAGE,
        0,
        0,
    )
    return marker + entry + data + b"\0" * (-len(data) % 4)


def _replace_version_resource(path: Path, resource: bytes) -> None:
    """Replace version entries from the setup or launcher while retaining other resources."""
    import win32api

    # > The Win32 wrapper accepts string names and integer resource IDs.
    version_type = cast("PyResourceId", _VERSION_TYPE)
    # > Map the executable as data so its code never runs.
    module = win32api.LoadLibraryEx(str(path), 0, 0x02)
    try:
        try:
            names = cast(
                "list[PyResourceId]",
                win32api.EnumResourceNames(module, version_type),
            )
        except win32api.error as error:
            if error.winerror not in {1812, 1813}:  # No resource data or type
                raise
            names = ()
        existing = [
            (name, language)
            for name in names
            for language in win32api.EnumResourceLanguages(
                module, version_type, name
            )
        ]
    finally:
        win32api.FreeLibrary(module)
    handle = win32api.BeginUpdateResource(str(path), False)
    try:
        for name, language in existing:
            if (name, language) != (_VERSION_NAME, _NEUTRAL_LANGUAGE):
                win32api.UpdateResource(
                    handle, version_type, name, None, language
                )
        win32api.UpdateResource(
            handle, _VERSION_TYPE, _VERSION_NAME, resource, _NEUTRAL_LANGUAGE
        )
    except Exception:
        win32api.EndUpdateResource(handle, True)
        raise
    win32api.EndUpdateResource(handle, False)


def versioned_executable(content: bytes, version: str) -> bytes:
    """Return a stamped Windows copy, warning and retaining bytes on failure.

    :param content: Original executable including its appended payload.
    :param version: Validated application distribution version.
    :return: Prepared executable bytes or the unchanged original.
    """
    import logging
    import os
    import tempfile

    if os.name != "nt":
        return content
    try:
        projection = _project_version(version)
        if projection is None:
            raise ValueError(
                f"unsupported automatic Windows version projection for {version!r}; "
                "use up to three numeric components and one optional stage "
                "suffix with serial 0–99, or a plain four-part release. "
                "Numeric components must be 0–65535."
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
        import win32api

        ms, ls, flags = _fixed_version_fields(projection)
        resource = _version_resource(ms, ls, version, flags)

        with tempfile.TemporaryDirectory(prefix="apprc-version-") as staging:
            path = Path(staging) / "command.exe"
            path.write_bytes(content[:end])
            _replace_version_resource(path, resource)
            result = path.read_bytes() + overlay
            path.write_bytes(result)
            observed = win32api.GetFileVersionInfo(str(path), "\\")
            # > pywin32 may return unsigned DWORDs as signed integers.
            fixed_versions = tuple(
                value & 0xFFFFFFFF
                for value in (
                    observed["FileVersionMS"],
                    observed["FileVersionLS"],
                    observed["ProductVersionMS"],
                    observed["ProductVersionLS"],
                )
            )
            if fixed_versions != (ms, ls, ms, ls):
                raise ValueError(
                    "numeric file or product version read-back failed"
                )
            for field in ("FileVersion", "ProductVersion"):
                if (
                    win32api.GetFileVersionInfo(
                        str(path), f"\\StringFileInfo\\{_STRING_TABLE}\\{field}"
                    )
                    != version
                ):
                    raise ValueError(f"{field} read-back failed")
            if observed["FileFlags"] & _PRERELEASE != flags:
                raise ValueError("prerelease flag read-back failed")
            return result
    except Exception as error:
        from apprc.distribution.runtime._install_progress import warn

        warn(
            logging.getLogger(__name__),
            "Windows executable version was not updated; installation continues",
            error,
        )
        return content
