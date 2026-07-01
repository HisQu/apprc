from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

import pytest

from apprc.user_files.storage_roots.archive import (
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


def test_archive_directory_rejects_symlinks_before_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    temp_archive = tmp_path / f".source{ARCHIVE_SUFFIX}.tmp"
    temp_archive.write_text("stale", encoding="utf-8")
    (source / "payload.txt").write_text("demo", encoding="utf-8")
    try:
        (source / "linked-payload.txt").symlink_to("payload.txt")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")

    with pytest.raises(ValueError, match="may not contain links"):
        archive_directory(source_root=source, archive_path=archive)

    assert not archive.exists()
    assert not temp_archive.exists()


def test_archive_directory_rejects_hardlinks_before_writing(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "link"):
        pytest.skip("hardlinks are unavailable on this platform")
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    payload = source / "payload.txt"
    payload.write_text("demo", encoding="utf-8")
    try:
        os.link(payload, source / "linked-payload.txt")
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable on this filesystem: {exc}")

    with pytest.raises(ValueError, match="may not contain links"):
        archive_directory(source_root=source, archive_path=archive)

    assert not archive.exists()
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


def test_extract_archive_validates_all_members_before_writing(
    tmp_path: Path,
) -> None:
    archive = tmp_path / f"mixed{ARCHIVE_SUFFIX}"
    good = tarfile.TarInfo("good.txt")
    good_payload = b"ok"
    good.size = len(good_payload)
    evil = tarfile.TarInfo("../evil.txt")
    evil_payload = b"nope"
    evil.size = len(evil_payload)
    with tarfile.open(archive, "w:xz", preset=9) as tar:
        tar.addfile(good, io.BytesIO(good_payload))
        tar.addfile(evil, io.BytesIO(evil_payload))

    with pytest.raises(ValueError, match="escapes destination"):
        extract_archive(
            archive_path=archive,
            destination_root=tmp_path / "restored",
        )

    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "evil.txt").exists()
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))


def test_extract_archive_rejects_non_empty_destination_by_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="not empty"):
        extract_archive(
            archive_path=archive,
            destination_root=destination,
        )

    assert (destination / "payload.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))


def test_extract_archive_replace_existing_swaps_after_staged_extract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("old", encoding="utf-8")
    (destination / "old-only.txt").write_text("remove", encoding="utf-8")

    restored = extract_archive(
        archive_path=archive,
        destination_root=destination,
        replace_existing=True,
    )

    assert restored == destination.resolve()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not (destination / "old-only.txt").exists()
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))
    assert not list(tmp_path.glob(".restored.apprc-backup-*"))
