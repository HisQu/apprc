"""User-wide dotenv persistence declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserDotenv:
    """Allow an application to load and edit ``apprc.user.env``.

    The empty declaration is intentional. AppRC owns the filename and layout;
    application code only decides whether this writable layer exists.
    """


__all__ = ["UserDotenv"]
