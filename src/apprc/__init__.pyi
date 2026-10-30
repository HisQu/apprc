"""Typed public declarations, without importing optional interfaces eagerly."""

from apprc.definition.app_config.user_dotenv import UserDotenv as UserDotenv
from apprc.definition.app_config.workspaces import Workspaces as Workspaces
from apprc.definition.installation import (
    InstallationError as InstallationError,
    InstallationInspection as InstallationInspection,
    InstallationRecord as InstallationRecord,
    InstallationSnapshot as InstallationSnapshot,
)
from apprc.services.installation import (
    InstallationManager as InstallationManager,
)
from apprc.user_files.installation.discovery import (
    installation_directory as installation_directory,
)
from apprc.definition.maintenance import (
    AppDataOperations as AppDataOperations,
)
from apprc.definition.maintenance import (
    CacheOperations as CacheOperations,
)
from apprc.definition.maintenance import (
    MaintenanceHandlers as MaintenanceHandlers,
)
from apprc.definition.maintenance import (
    RemovalOperation as RemovalOperation,
)
from apprc.definition.maintenance import (
    RemovalPlan as RemovalPlan,
)
from apprc.definition.maintenance import (
    RemovalResult as RemovalResult,
)
from apprc.definition.maintenance import (
    StateOperations as StateOperations,
)
from apprc.definition.paths import (
    AppPaths as AppPaths,
)
from apprc.definition.paths import (
    Layout as Layout,
)
from apprc.definition.paths import (
    PathKind as PathKind,
)
from apprc.definition.paths import (
    Paths as Paths,
)
from apprc.definition.paths import (
    ResourceKind as ResourceKind,
)
from apprc.definition.resolution import (
    ImportedConfig as ImportedConfig,
)
from apprc.definition.resolution import (
    ResolveOptions as ResolveOptions,
)
from apprc.public.app_rc import AppRC as AppRC
from apprc.public.config import Config as Config
from apprc.public.config import ConfigBase as ConfigBase
from apprc.public.field import field as field
from apprc.runtime.resolution import ResolvedConfig as ResolvedConfig

from . import (
    cli as cli,
)
from . import (
    files as files,
)
from . import (
    provenance as provenance,
)
from . import (
    schema as schema,
)
from . import (
    tui as tui,
)
from . import (
    workspaces as workspaces,
)

__all__: list[str]
