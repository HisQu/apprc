"""Shared utility facade."""

# ruff: noqa: F401

from . import stdlib
from .stdlib import (
    dataclass_slots_preserving_class_identity,
    deep_get,
    deep_right_merge,
    deep_set,
    timer,
)
