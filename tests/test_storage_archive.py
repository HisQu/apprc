from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from apprc.runtime_config.storage.archive import (
    ARCHIVE_SUFFIX,
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
    is_storage_archive_path,
    storage_archive_default_path,
    storage_root_name_from_archive,
)


def test_storage_archive_helpers_name_paths(tmp_path: Path) -> None:
    storage_root = tmp_path / "alpha"

    assert is_storage_archive_path(f"alpha{ARCHIVE_SUFFIX}")
    assert storage_archive_default_path(storage_root) == (
        tmp_path / f"alpha{ARCHIVE_SUFFIX}"
    )
    assert (
        storage_root_name_from_archive(tmp_path / f"alpha{ARCHIVE_SUFFIX}")
        == "alpha"
    )


def test_archive_directory_round_trips_with_progress(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "payload.txt").write_text("demo", encoding="utf-8")
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    progress: list[StorageArchiveProgress] = []

    written = archive_directory(
        source_root=source,
        archive_path=archive,
        progress=progress.append,
    )
    restored = extract_archive(
        archive_path=written,
        destination_root=tmp_path / "restored",
        progress=progress.append,
    )

    assert written == archive.resolve()
    assert (restored / "nested" / "payload.txt").read_text(
        encoding="utf-8"
    ) == "demo"
    assert progress
    assert progress[-1].completed == progress[-1].total


def test_archive_directory_atomically_replaces_existing_archive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    archive.write_text("old", encoding="utf-8")

    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive_directory(source_root=source, archive_path=archive)
    restored = extract_archive(
        archive_path=archive,
        destination_root=tmp_path / "restored",
    )

    assert (restored / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / f".source{ARCHIVE_SUFFIX}.tmp").exists()


def test_extract_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / f"evil{ARCHIVE_SUFFIX}"
    info = tarfile.TarInfo("../evil.txt")
    payload = b"nope"
    info.size = len(payload)
    with tarfile.open(archive, "w:xz", preset=9) as tar:
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="escapes destination"):
        extract_archive(
            archive_path=archive,
            destination_root=tmp_path / "restored",
        )

    assert not (tmp_path / "evil.txt").exists()
