"""Legacy path constants for scaffolded AppRC applications.

New applications should prefer :class:`apprc.AppConfigKit` and the storage
registry helpers in :mod:`apprc.config.storage_registry`. This module is kept
only for older scaffold-style code that imports ``apprc.paths.ROOT_PKG`` or
``apprc.paths.ROOT_STORAGE`` directly.

``ROOT_STORAGE`` is resolved lazily on first access from the quarantined
``APPRC_LEGACY_STORAGE`` environment variable so importing this module does not
read dotenv files or require local storage to be configured.
"""

# == Standard Library ========================
import logging
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
import apprc
from apprc import utils as ut

LOG = logging.getLogger(__name__)

ROOT_PKG: Path = ut.package_root_dir(apprc)
LOG.debug(f"AppRC package directory: {ROOT_PKG}")


def root_storage() -> Path:
    """Return the legacy local storage directory for scaffolded projects.

    :return: Path selected by ``APPRC_LEGACY_STORAGE`` in ``.env.template`` or
        the current process environment.
    """
    return ut.get_local_dir_from_env(
        env_var="APPRC_LEGACY_STORAGE",
        env_file=".env.template",
    )


def __getattr__(name: str) -> Path:
    """Resolve legacy module constants without import-time env reads.

    :param name: Module attribute requested by the caller.
    :return: Lazily resolved legacy constant.
    :raises AttributeError: If ``name`` is not a known lazy constant.
    """
    if name == "ROOT_STORAGE":
        value = root_storage()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ROOT_PKG", "ROOT_STORAGE", "root_storage"]

if TYPE_CHECKING:
    ROOT_STORAGE: Path
