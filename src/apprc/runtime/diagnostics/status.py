"""Runtime readiness states reported by ``config doctor``."""

from __future__ import annotations

# == Standard Library ========================
from enum import StrEnum


class ConfigDoctorStatus(StrEnum):
    """Readiness status for one AppRC-backed application."""

    STORAGE_NOT_SELECTED = "storage_not_selected"
    STORAGE_NOT_READY = "storage_not_ready"
    USER_DOTENV_NOT_READY = "user_dotenv_not_ready"
    STORAGE_REGISTRY_NOT_READY = "storage_registry_not_ready"
    RUNNABLE = "runnable"
