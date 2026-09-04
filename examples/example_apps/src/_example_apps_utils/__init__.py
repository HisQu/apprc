"""Shared orchestration for the repository-local AppRC example apps."""

# ruff: noqa: F401

from _example_apps_utils.registry import (
    EXAMPLE_APPS,
    ExampleAppSpec,
    example_app,
    example_app_specs,
)

__all__ = [
    "EXAMPLE_APPS",
    "ExampleAppSpec",
    "example_app",
    "example_app_specs",
]
