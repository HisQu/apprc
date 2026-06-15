"""Installation health states for one AppRC-backed application."""

from __future__ import annotations

# == Standard Library ========================
from enum import StrEnum


class ConfigInstallState(StrEnum):
    """Explicit setup state for one application's registry."""

    ENV_NOT_SET = "env_not_set"
    NOT_INSTALLED = "not_installed"
    INSTALLED_UNHEALTHY = "installed_unhealthy"
    INSTALLED_HEALTHY = "installed_healthy"
