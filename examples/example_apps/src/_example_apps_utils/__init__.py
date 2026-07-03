"""Shared orchestration for the repository-local AppRC example apps."""

# ruff: noqa: F401

from _example_apps_utils.registry import (
    EXAMPLE_APPS,
    ExampleAppSpec,
    example_app_specs,
    example_kits,
)

__all__ = [
    "EXAMPLE_APPS",
    "ExampleAppSpec",
    "example_app_specs",
    "example_kits",
]
