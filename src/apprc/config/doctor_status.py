"""Runtime readiness states reported by ``config doctor``."""

from __future__ import annotations

# == Standard Library ========================
from enum import StrEnum


class ConfigDoctorStatus(StrEnum):
    """Readiness status for one AppRC-backed application."""

    ENV_NOT_SET = "env_not_set"
    REGISTRY_NOT_READY = "registry_not_ready"
    STORAGE_NOT_READY = "storage_not_ready"
    RUNNABLE = "runnable"
