"""Legacy path constants for scaffolded AppRC applications.

New applications should prefer :class:`apprc.AppConfigKit` and the storage
registry helpers in :mod:`apprc.config.storage_registry`. This module is kept
only for older scaffold-style code that imports ``apprc.paths.ROOT_PKG`` or
``apprc.paths.ROOT_STORAGE`` directly.

Importing this module still resolves ``ROOT_STORAGE`` from the historical
``apprc_STORAGE`` environment variable, so do not import it from general
library code unless that variable is intentionally configured.
"""

# == Standard Library ========================
import logging
from pathlib import Path

# == Internal ================================
import apprc
from apprc import utils as ut

LOG = logging.getLogger(__name__)

ROOT_PKG: Path = ut.package_root_dir(apprc)
LOG.debug(f"AppRC package directory: {ROOT_PKG}")

ROOT_STORAGE = ut.get_local_dir_from_env(
    env_var="apprc_STORAGE",
    env_file=".env.template",
)
