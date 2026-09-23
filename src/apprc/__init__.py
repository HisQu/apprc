"""Clean public facade for AppRC."""

# ruff: noqa: F401

# > Explicit aliases mark public imports for downstream type checkers.
from apprc.public.app_rc import AppRC as AppRC
from apprc.definition.resolution import ResolveOptions as ResolveOptions
from apprc.runtime.resolution import ResolvedConfig as ResolvedConfig
from apprc.public.config import Config as Config, ConfigBase as ConfigBase
from apprc.public.field import field as field
from apprc.definition.app_config.storage import Storage as Storage
from apprc.definition.app_config.user_dotenv import UserDotenv as UserDotenv

from . import cli
from . import tui
from . import files
from . import provenance
from . import schema
from . import storage

from ._exports import PUBLIC_NAMES as __all__
