"""Explicitly move legacy secret assignments out of ordinary dotenv files."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import re

from dotenv.parser import parse_stream

from apprc.user_files.app_home.locations import write_text_atomic
from apprc.user_files.app_home.writes import (
    StaleEditError,
    file_revision,
    managed_write_lock,
)
from apprc.user_files.env_files._document import (
    clear_dotenv_document_value,
    set_dotenv_document_value,
)
from apprc.user_files.env_files.secrets import inspect_secret_file


@dataclass(frozen=True, slots=True)
class SecretMigrationPlan:
    """Two-file change reviewed before any credential is moved.

    :param ordinary_path: Existing managed dotenv containing old assignments.
    :param secret_path: Private companion that will receive them.
    :param keys: Environment keys to move, safe to display without values.
    :param ordinary_revision: Source digest at planning time.
    :param secret_revision: Companion digest at planning time.
    :param ordinary_text: Complete source text after migration.
    :param secret_text: Complete companion text after migration.
    """

    ordinary_path: Path
    secret_path: Path
    keys: tuple[str, ...]
    ordinary_revision: str | None
    secret_revision: str | None
    ordinary_text: str = field(repr=False)
    secret_text: str = field(repr=False)
    lock_roots: tuple[Path, ...] = ()


def plan_secret_migration(
    ordinary_path: Path, secret_path: Path, secret_keys: set[str]
) -> SecretMigrationPlan:
    """Plan a value-preserving move without touching either file.

    :param ordinary_path: Managed user or storage dotenv path.
    :param secret_path: Its secret companion.
    :param secret_keys: Keys declared with ``secret=True``.
    :return: Revision-checked plan with no values in its representation.
    """
    ordinary = (
        ordinary_path.read_text(encoding="utf-8")
        if ordinary_path.is_file()
        else ""
    )
    secret = (
        secret_path.read_text(encoding="utf-8") if secret_path.is_file() else ""
    )
    existing = _assignments(secret)
    moving = {
        key: value
        for key, value in _assignments(ordinary).items()
        if key in secret_keys
    }
    for key, value in moving.items():
        if key in existing and existing[key] != value:
            raise ValueError(
                f"{key} has different saved values in the ordinary and secret files. Resolve this conflict before migration."
            )
    commented = _commented_assignments(ordinary, secret_keys)
    if moving or commented:
        status = inspect_secret_file(secret_path)
        if not status.available:
            raise ValueError(status.issue or "Secret file is unavailable.")
    new_ordinary = ordinary
    new_secret = secret
    for key, value in moving.items():
        new_secret = set_dotenv_document_value(
            new_secret, env_key=key, value=value
        ).text
        new_ordinary = clear_dotenv_document_value(
            new_ordinary, env_key=key
        ).text
    new_ordinary = _remove_commented_assignments(new_ordinary, secret_keys)
    return SecretMigrationPlan(
        ordinary_path=ordinary_path,
        secret_path=secret_path,
        keys=tuple(sorted(set(moving) | commented)),
        ordinary_revision=file_revision(ordinary_path),
        secret_revision=file_revision(secret_path),
        ordinary_text=new_ordinary,
        secret_text=new_secret,
    )


def apply_secret_migration(plan: SecretMigrationPlan) -> None:
    """Write the private copy first, then remove old assignments.

    If the second write fails, the private copy wins during resolution and the
    original remains available for a retry. Both revisions are checked while
    holding the same cross-process lock used by ordinary edits.

    :param plan: Reviewed plan from :func:`plan_secret_migration`.
    :return: None.
    """
    if not plan.keys:
        return
    with managed_write_lock(*(plan.lock_roots or (plan.ordinary_path.parent,))):
        for path, revision in (
            (plan.ordinary_path, plan.ordinary_revision),
            (plan.secret_path, plan.secret_revision),
        ):
            current = file_revision(path)
            if current != revision:
                raise StaleEditError(path, revision, current)
        write_text_atomic(plan.secret_path, plan.secret_text, private=True)
        write_text_atomic(plan.ordinary_path, plan.ordinary_text)


def _assignments(text: str) -> dict[str, str]:
    """Read raw parsed values without interpolating process variables."""
    values: dict[str, str] = {}
    for binding in parse_stream(StringIO(text)):
        if not binding.error and binding.key is not None:
            values[binding.key] = binding.value or ""
    return values


def _commented_assignments(text: str, secret_keys: set[str]) -> set[str]:
    """Find dotenv-shaped secret values disabled in ordinary-file comments."""
    found: set[str] = set()
    for line in text.splitlines():
        for key in secret_keys:
            if re.match(
                rf"\s*#\s*(?:AppRC disabled duplicate assignment:\s*)?"
                rf"(?:export\s+)?(?:'{re.escape(key)}'|{re.escape(key)})\s*=",
                line,
            ):
                found.add(key)
    return found


def _remove_commented_assignments(text: str, secret_keys: set[str]) -> str:
    """Erase complete commented assignments, including quoted continuations."""
    lines = text.splitlines(keepends=True)
    retained: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        keys = _commented_assignments(line, secret_keys)
        if not keys:
            retained.append(line)
            index += 1
            continue
        key = next(iter(keys))
        assignment = re.sub(
            r"^\s*#\s*(?:AppRC disabled duplicate assignment:\s*)?",
            "",
            line,
            count=1,
        )
        consumed = 1
        while not _parsed_assignment(assignment, key):
            if index + consumed >= len(lines) or not re.match(
                r"^\s*#\s", lines[index + consumed]
            ):
                raise ValueError(
                    f"Cannot safely remove the commented {key} assignment. "
                    "Edit the ordinary file before migrating secrets."
                )
            assignment += re.sub(
                r"^\s*#\s", "", lines[index + consumed], count=1
            )
            consumed += 1
        index += consumed
    return "".join(retained)


def _parsed_assignment(text: str, key: str) -> bool:
    """Check whether reconstructed commented text forms one full binding."""
    bindings = list(parse_stream(StringIO(text)))
    return (
        len(bindings) == 1 and not bindings[0].error and bindings[0].key == key
    )
