"""Runtime readiness states reported by ``config doctor``."""

from __future__ import annotations

# == Standard Library ========================
from enum import StrEnum


class ConfigDoctorStatus(StrEnum):
    """Readiness status for one AppRC-backed application."""

    CONFIG_NOT_READY = "config_not_ready"
    ENV_NOT_SET = "env_not_set"
    MULTI_STORAGE_NOT_READY = "multi_storage_not_ready"
    STORAGE_NOT_READY = "storage_not_ready"
    RUNNABLE = "runnable"
