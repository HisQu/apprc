"""User-wide dotenv persistence declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserDotenv:
    """Allow an application to load and edit ``apprc.user.env``.

    AppRC owns the filename and layout. Application code decides whether this
    writable layer exists and whether its absence makes diagnostics fail.

    :param required: Whether a missing user dotenv is a doctor issue. Optional
        user dotenv files remain available to setup, editing, and bootstrap.
    """

    required: bool = True


__all__ = ["UserDotenv"]
