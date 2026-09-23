"""User-wide dotenv persistence declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserDotenv:
    """Allow an application to load and edit ``apprc.user.env``.

    AppRC owns the filename and layout. Application code decides whether this
    writable layer is available. An absent file means no saved overrides.

    """


__all__ = ["UserDotenv"]
