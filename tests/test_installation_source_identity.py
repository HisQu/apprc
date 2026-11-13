"""Validate strict managed runtime snapshots and selections."""

from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)


def test_project_snapshot_requires_lowercase_digests_and_full_commit() -> None:
    valid = ProjectSnapshot("a" * 64, "b" * 64, "c" * 40)
    assert valid.project_path == "."

    for digest in ("A" * 64, "a" * 63, "z" * 64):
        with pytest.raises(InstallationError, match="SHA-256"):
            ProjectSnapshot(digest, "b" * 64, "c" * 40)
    with pytest.raises(InstallationError, match="commit ID"):
        ProjectSnapshot("a" * 64, "b" * 64, "A" * 40)


@pytest.mark.parametrize("project_path", ["../outside", "/absolute", "src\\app", "a/../b"])
def test_project_snapshot_rejects_non_normalized_project_paths(
    project_path: str,
) -> None:
    with pytest.raises(InstallationError, match="normalized and relative"):
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40, project_path)


def test_runtime_selection_rejects_duplicate_or_invalid_extras() -> None:
    assert RuntimeSelection("3.14", ("gui", "web")).extras == ("gui", "web")
    for extras in (("web", "web"), ("bad extra",), ("",)):
        with pytest.raises(InstallationError, match="valid and unique"):
            RuntimeSelection("3.14", extras)


def test_runtime_slot_captures_immutable_source_selection_and_observations() -> None:
    source = ProjectSnapshot("a" * 64, "b" * 64, "c" * 40)
    selection = RuntimeSelection("3.14", ("web",))
    candidate = RuntimeSlot(uuid4(), source, selection)
    observed = RuntimeSlot(
        candidate.slot_id,
        source,
        selection,
        version="1.2.3",
        python_version="3.14.2",
    )
    assert candidate.source == observed.source
    assert candidate.selection == observed.selection
    assert candidate.slot_id == observed.slot_id
    with pytest.raises(InstallationError, match="observations"):
        RuntimeSlot(uuid4(), source, selection, version=" ")


def test_editable_checkout_requires_canonical_absolute_paths(tmp_path: Path) -> None:
    runtime = EditableCheckout(tmp_path / "checkout", tmp_path / "checkout/.venv")
    assert runtime.project.is_absolute()
    assert runtime.environment.is_absolute()
    with pytest.raises(InstallationError, match="absolute"):
        EditableCheckout(Path("checkout"), Path("checkout/.venv"))


def test_editable_checkout_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(InstallationError, match="normalized"):
        EditableCheckout(tmp_path / ".." / "outside", tmp_path / ".venv")
