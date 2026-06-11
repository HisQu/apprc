"""Shared utility facade."""

# ruff: noqa: F401

from . import path_resolver, stdlib
from .path_resolver import (
    get_local_dir_from_env,
    package_root_dir,
    require_env,
)
from .stdlib import (
    deep_get,
    deep_right_merge,
    deep_set,
    timer,
)
