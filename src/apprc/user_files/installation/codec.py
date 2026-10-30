"""Strict deterministic JSON codec for the installation dataclass schema.

The decoder accepts only declared fields and exact JSON types. It never imports
an application or constructs arbitrary classes supplied by record contents.
"""

from __future__ import annotations

import dataclasses
import json
import re
import types
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Literal, Union, get_args, get_origin, get_type_hints
from uuid import UUID

from apprc.definition.installation import (
    InstallationError,
    InstallationRecord,
    OperationContext,
)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise InstallationError(f"Duplicate installation field: {key}.")
        result[key] = value
    return result


def _decode(value: object, annotation: object, location: str) -> object:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (Union, types.UnionType):
        for alternative in arguments:
            try:
                return _decode(value, alternative, location)
            except InstallationError:
                continue
        raise InstallationError(f"Invalid value at {location}.")
    if origin is Literal:
        if any(
            type(value) is type(item) and value == item for item in arguments
        ):
            return value
    elif annotation is type(None):
        if value is None:
            return None
    elif annotation in (str, bool, int):
        if type(value) is annotation:
            return value
    elif annotation is Path:
        if isinstance(value, str) and Path(value).is_absolute():
            return Path(value)
    elif annotation is UUID:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError as error:
                raise InstallationError(
                    f"Invalid UUID at {location}."
                ) from error
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        try:
            return annotation(value)
        except (ValueError, TypeError) as error:
            raise InstallationError(f"Invalid enum at {location}.") from error
    elif origin in (tuple, frozenset):
        if isinstance(value, list):
            decoded = [
                _decode(item, arguments[0], f"{location}[{index}]")
                for index, item in enumerate(value)
            ]
            if origin is frozenset:
                result = frozenset(decoded)
                if len(result) != len(decoded):
                    raise InstallationError(f"Duplicate members at {location}.")
                return result
            return tuple(decoded)
    elif isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        if isinstance(value, dict):
            hints = get_type_hints(annotation)
            if set(value) != set(hints):
                raise InstallationError(
                    f"Missing or unknown fields at {location}."
                )
            decoded_fields = {
                name: _decode(value[name], field_type, f"{location}.{name}")
                for name, field_type in hints.items()
            }
            try:
                return annotation(**decoded_fields)
            except (ValueError, TypeError) as error:
                raise InstallationError(
                    f"Invalid record at {location}: {error}"
                ) from error
    raise InstallationError(f"Invalid type or value at {location}.")


def _encode(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (Path, UUID, Enum)):
        return str(value)
    if isinstance(value, (tuple, frozenset)):
        items = [_encode(item) for item in value]
        if isinstance(value, frozenset):
            if not all(isinstance(item, str) for item in items):
                raise InstallationError(
                    "Installation set members must encode as strings."
                )
            return sorted(item for item in items if isinstance(item, str))
        return items
    if value is None or type(value) in (str, bool, int):
        return value
    raise InstallationError(
        f"Unsupported installation value: {type(value).__name__}."
    )


def _validate(record: InstallationRecord, app_id: str) -> None:
    if (
        record.app_id != app_id
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None
    ):
        raise InstallationError(
            "Installation application identity does not match."
        )
    for output in record.owned_outputs:
        if output.kind == "support":
            path = PurePosixPath(output.path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in output.path
                or not path.parts
            ):
                raise InstallationError(
                    "Owned support paths must be safe relative paths."
                )
        if (
            output.digest is not None
            and re.fullmatch(r"[0-9a-f]{64}", output.digest) is None
        ):
            raise InstallationError("Owned output digest must be SHA-256.")
    sources = [
        snapshot.source
        for snapshot in (record.current, record.last_successful)
        if snapshot is not None
    ]
    if record.operation is not None and record.operation.intended is not None:
        sources.append(record.operation.intended.source)
    if any(
        source.digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", source.digest) is None
        for source in sources
    ):
        raise InstallationError("Installation source digest must be SHA-256.")
    for snapshot in (record.current, record.last_successful):
        if snapshot is not None and (
            not snapshot.prefix.is_absolute()
            or not snapshot.interpreter.is_absolute()
            or any(not command.is_absolute() for command in snapshot.commands)
        ):
            raise InstallationError(
                "Installed backend observations must use absolute paths."
            )
    if any(
        snapshot is not None
        and snapshot.distribution_record_digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", snapshot.distribution_record_digest)
        is None
        for snapshot in (record.current, record.last_successful)
    ):
        raise InstallationError(
            "Installed distribution RECORD digest must be SHA-256."
        )


def decode_record(content: bytes, *, app_id: str) -> InstallationRecord:
    """Decode exact schema 1 fields without accepting JSON coercions.

    :param content: Exact UTF-8 authority bytes.
    :param app_id: Expected host identity, never obtained from untrusted bytes.
    :return: Validated immutable installation record.
    """
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs)
        record = _decode(value, InstallationRecord, "installation")
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise InstallationError(
            f"Invalid installation JSON: {error}"
        ) from error
    if not isinstance(record, InstallationRecord):
        raise InstallationError("Installation root must be a record.")
    _validate(record, app_id)
    return record


def encode_record(record: InstallationRecord) -> bytes:
    """Return canonical UTF-8 JSON including a final newline.

    :param record: Validated schema record.
    :return: Stable bytes used for revisions and atomic publication.
    """
    _validate(record, record.app_id)
    content = (
        json.dumps(
            _encode(record),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    decode_record(content, app_id=record.app_id)
    return content


def encode_operation_context(context: OperationContext) -> bytes:
    """Serialize private probe inputs, never a second discovery authority.

    :param context: Explicit pending operation authorization.
    :return: Deterministic UTF-8 bytes.
    """
    return (
        json.dumps(_encode(context), ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def decode_operation_context(content: bytes) -> OperationContext:
    """Decode only the fixed operation-context schema.

    :param content: Private controller-supplied inputs.
    :return: Typed context, still requiring validation against live authority.
    """
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs)
        context = _decode(value, OperationContext, "operation-context")
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise InstallationError("Invalid operation context JSON.") from error
    if not isinstance(context, OperationContext):
        raise InstallationError("Invalid operation context.")
    return context
