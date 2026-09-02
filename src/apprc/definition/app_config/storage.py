"""Storage requirements declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ============================================
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Storage:
    """Declare that an application needs one active storage directory.

    The declaration describes storage-specific naming and first-run behavior.
    AppRC derives an environment key and platform data path when the caller
    leaves them unset.

    :param env_key: Environment key that selects the active storage. AppRC
        derives ``<APP>_STORAGE`` when omitted.
    :param suggested_root: First storage proposed during setup. AppRC uses the
        application's platform data directory when omitted.
    :param prompt_on_first_run: Whether an interactive generated CLI may offer
        to create the suggested storage before a runtime command.
    :param env_filename: Dotenv filename stored inside each storage root.
    """

    env_key: str | None = None
    suggested_root: Path | None = None
    prompt_on_first_run: bool = True
    env_filename: str = "apprc.storage.env"


__all__ = ["Storage"]
