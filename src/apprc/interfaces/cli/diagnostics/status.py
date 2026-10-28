"""Structured status values reported by AppRC diagnostics."""

from __future__ import annotations

from enum import StrEnum


class ConfigDoctorStatus(StrEnum):
    """Aggregate status for one read-only configuration report."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
