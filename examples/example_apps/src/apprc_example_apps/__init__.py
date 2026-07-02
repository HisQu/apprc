"""Shared orchestration for the repository-local AppRC example apps."""

# ruff: noqa: F401

from apprc_example_apps.registry import (
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
