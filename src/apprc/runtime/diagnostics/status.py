"""Runtime readiness states reported by ``config doctor``."""

from __future__ import annotations

# == Standard Library ========================
from enum import StrEnum


class ConfigDoctorStatus(StrEnum):
    """Readiness status for one AppRC-backed application."""

    ENV_NOT_SET = "env_not_set"
    STORAGE_NOT_READY = "storage_not_ready"
    APP_CONFIG_NOT_READY = "app_config_not_ready"
    NAMED_STORAGE_NOT_READY = "named_storage_not_ready"
    RUNNABLE = "runnable"
