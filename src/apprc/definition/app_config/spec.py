"""Application-level configuration contract."""

from __future__ import annotations

# == Standard Library ============================================
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ====================================================
from apprc.definition.app_config._validation import (
    derive_apprc_toml_env_key,
    resolve_storage_selector_env_key,
)
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.storage import Storage
from apprc.definition.env_config._validation import (
    validate_config_owner_inventory,
)
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import config_owner_for
from apprc.definition.env_config.schema import ConfigOwner
from apprc.user_files.app_home._paths import normalize_apprc_toml_path
from apprc.user_files.app_home.locations import (
    AppConfigHome,
    app_config_file,
    app_config_home,
    ensure_text_file,
    require_config_filename,
    resolve_app_config_home,
)
from apprc.user_files.env_files.files import storage_env_path
from apprc.user_files.managed_files import (
    ManagedFileResolution,
    resolve_managed_file,
)

DEFAULT_DEFAULTS_ENV_FILENAME = "apprc.defaults.env"
DEFAULT_APP_ENV_FILENAME = "apprc.app.env"
DEFAULT_STORAGE_ENV_FILENAME = "apprc.storage.env"
DEFAULT_APPRC_TOML_FILENAME = "apprc.toml"

LEGACY_DEFAULTS_ENV_FILENAME = ".env.shared"
LEGACY_APP_ENV_FILENAME = ".env.apprc-app"
LEGACY_STORAGE_ENV_FILENAME = ".env.apprc-storage"


@dataclass(frozen=True, slots=True, init=False)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    New integrations declare optional :class:`Storage` support. App config is
    always available and its dotenv file remains absent until a write needs
    it. Temporary compatibility fields retain the 0.19 capability behavior
    for deprecated constructors.

    :param app_name: Stable application name used in paths and env key
        derivation.
    :param display_name: Human-readable application name.
    :param config_package: Package containing the packaged defaults dotenv.
    :param envs: Env-backed config classes registered by the public facade.
    :param storage: Storage declaration, or ``None`` for storage-free apps.
    :param command_name: Executable name shown in generated instructions.
    :param defaults_env_filename: Packaged defaults dotenv filename.
    :param app_env_filename: Per-user app config dotenv filename.
    :param apprc_toml_filename: AppRC TOML filename below the config home.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    envs: tuple[type[EnvConfig], ...]
    storage: Storage | None
    storage_selector_env_key: str | None
    command_name: str | None
    defaults_env_filename: str
    app_env_filename: str
    apprc_toml_filename: str
    _app_env_enabled: bool
    _setup_creates_app_env: bool
    _named_storage_enabled: bool
    _apprc_toml_required: bool
    _legacy_constructor: str | None

    def __init__(
        self,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage: Storage | None = None,
        command_name: str | None = None,
        defaults_env_filename: str = DEFAULT_DEFAULTS_ENV_FILENAME,
        app_env_filename: str = DEFAULT_APP_ENV_FILENAME,
        apprc_toml_filename: str = DEFAULT_APPRC_TOML_FILENAME,
        storage_layer: StorageLayerState | str | None = None,
        app_wide_layer: CapabilityState | str | None = None,
        named_storage_layer: CapabilityState | str | None = None,
        storage_env_key: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str | None = None,
        app_wide_env_filename: str | None = None,
        storage_env_filename: str | None = None,
        _legacy_constructor: str | None = None,
    ) -> None:
        """Normalize a new declaration or one deprecated capability shape."""
        resolved_owners = tuple(config_owner_for(env_cls) for env_cls in envs)
        validate_config_owner_inventory(resolved_owners)

        resolved_defaults_filename = require_config_filename(
            shared_env_filename or defaults_env_filename,
            field_name="defaults_env_filename",
        )
        resolved_app_filename = require_config_filename(
            app_wide_env_filename or app_env_filename,
            field_name="app_env_filename",
        )
        resolved_toml_filename = require_config_filename(
            index_filename or apprc_toml_filename,
            field_name="apprc_toml_filename",
        )

        resolved_storage = storage
        if storage_layer is not None:
            legacy_storage_layer = StorageLayerState(storage_layer)
            if storage is not None:
                raise ValueError(
                    "storage and storage_layer cannot be declared together."
                )
            if legacy_storage_layer == StorageLayerState.REQUIRED:
                resolved_storage = Storage(
                    env_key=storage_env_key,
                    prompt_on_first_run=False,
                    env_filename=(
                        storage_env_filename or DEFAULT_STORAGE_ENV_FILENAME
                    ),
                )
            elif storage_env_key is not None:
                raise ValueError("storage_env_key requires storage.")
        elif resolved_storage is None and (
            storage_env_key is not None or storage_env_filename is not None
        ):
            raise ValueError(
                "storage_env_key and storage_env_filename require storage."
            )
        elif resolved_storage is not None and storage_env_filename is not None:
            resolved_storage = Storage(
                env_key=resolved_storage.env_key,
                suggested_root=resolved_storage.suggested_root,
                prompt_on_first_run=resolved_storage.prompt_on_first_run,
                env_filename=storage_env_filename,
            )

        resolved_selector_key = None
        if resolved_storage is not None:
            storage_filename = require_config_filename(
                resolved_storage.env_filename,
                field_name="storage.env_filename",
            )
            resolved_selector_key = resolve_storage_selector_env_key(
                app_name=app_name,
                env_key=resolved_storage.env_key or storage_env_key,
            )
            resolved_storage = Storage(
                env_key=resolved_selector_key,
                suggested_root=resolved_storage.suggested_root,
                prompt_on_first_run=resolved_storage.prompt_on_first_run,
                env_filename=storage_filename,
            )

        app_policy = (
            CapabilityState(app_wide_layer)
            if app_wide_layer is not None
            else CapabilityState.OPTIONAL
        )
        named_policy = (
            CapabilityState(named_storage_layer)
            if named_storage_layer is not None
            else (
                CapabilityState.OPTIONAL
                if resolved_storage is not None
                else CapabilityState.DISABLED
            )
        )
        if (
            resolved_storage is None
            and named_policy != CapabilityState.DISABLED
        ):
            raise ValueError("named_storage_layer requires storage.")

        object.__setattr__(self, "app_name", app_name)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "config_package", config_package)
        object.__setattr__(self, "owners", resolved_owners)
        object.__setattr__(self, "envs", tuple(envs))
        object.__setattr__(self, "storage", resolved_storage)
        object.__setattr__(
            self,
            "storage_selector_env_key",
            resolved_selector_key,
        )
        object.__setattr__(self, "command_name", command_name)
        object.__setattr__(
            self,
            "defaults_env_filename",
            resolved_defaults_filename,
        )
        object.__setattr__(self, "app_env_filename", resolved_app_filename)
        object.__setattr__(
            self,
            "apprc_toml_filename",
            resolved_toml_filename,
        )
        object.__setattr__(
            self,
            "_app_env_enabled",
            app_policy != CapabilityState.DISABLED,
        )
        object.__setattr__(
            self,
            "_setup_creates_app_env",
            app_policy == CapabilityState.DEFAULT,
        )
        object.__setattr__(
            self,
            "_named_storage_enabled",
            named_policy != CapabilityState.DISABLED,
        )
        object.__setattr__(
            self,
            "_apprc_toml_required",
            named_policy == CapabilityState.DEFAULT,
        )
        object.__setattr__(self, "_legacy_constructor", _legacy_constructor)

    def config_command_name(self) -> str:
        """Return the executable name shown in generated commands."""
        return self.command_name or self.app_name

    @staticmethod
    def derive_legacy_apprc_toml_filename(app_name: str) -> str:
        """Return the 0.19 AppRC TOML basename for compatibility.

        :param app_name: Application name used by the old convention.
        :return: Legacy ``<app>.apprc.toml`` filename.
        """
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
        return f"{normalized or 'app'}.apprc.toml"

    @staticmethod
    def derive_index_filename(app_name: str) -> str:
        """Return the deprecated 0.19 AppRC TOML basename."""
        return AppConfigSpec.derive_legacy_apprc_toml_filename(app_name)

    @property
    def apprc_toml_env_key(self) -> str:
        """Return the environment key that relocates the AppRC TOML file."""
        return derive_apprc_toml_env_key(self.app_name)

    def uses_storage(self) -> bool:
        """Return whether runtime requires an active storage root."""
        return self.storage is not None

    def uses_legacy_constructor(self) -> bool:
        """Return whether a deprecated constructor built this contract."""
        return self._legacy_constructor is not None

    def app_env_enabled(self) -> bool:
        """Return whether per-user app overrides may be loaded."""
        return self._app_env_enabled

    def setup_creates_app_env(self) -> bool:
        """Return the deprecated setup behavior for legacy constructors."""
        return self._setup_creates_app_env

    def named_storage_enabled(self) -> bool:
        """Return whether storage names may use the AppRC TOML file."""
        return self._named_storage_enabled

    def apprc_toml_required(self) -> bool:
        """Return whether compatibility policy requires an existing TOML."""
        return self._apprc_toml_required

    def config_home(self) -> Path:
        """Return the platform-native per-user config directory."""
        return app_config_home(self.app_name)

    def app_config_file(self, filename: str) -> Path:
        """Return one application-owned path below the config home."""
        return app_config_file(self.app_name, filename)

    def preferred_apprc_toml_path(self) -> Path:
        """Return the conventional AppRC TOML path."""
        return self.config_home() / self.apprc_toml_filename

    def preferred_app_env_path(self) -> Path:
        """Return the path defined by the current app filename."""
        return self.config_home() / self.app_env_filename

    def app_env_resolution(self) -> ManagedFileResolution:
        """Return the active app dotenv path and migration candidates."""
        preferred = self.preferred_app_env_path()
        legacy = ()
        if (
            self._legacy_constructor is None
            and self.app_env_filename == DEFAULT_APP_ENV_FILENAME
        ):
            legacy = (
                preferred.with_name(LEGACY_APP_ENV_FILENAME),
                preferred.with_name(".env.global"),
            )
        return resolve_managed_file(
            preferred=preferred,
            legacy_candidates=legacy,
            label="app dotenv",
        )

    def app_env_path(self) -> Path:
        """Return the active per-user app dotenv path."""
        return self.app_env_resolution().selected

    def storage_env_resolution(
        self,
        storage_root: Path,
    ) -> ManagedFileResolution:
        """Return the active storage dotenv path and migration candidates.

        :param storage_root: Storage directory that owns the file.
        :return: Deterministic current-or-legacy file selection.
        """
        if self.storage is None:
            raise ValueError(f"{self.display_name} does not use AppRC storage.")
        preferred = storage_env_path(
            storage_root,
            filename=self.storage.env_filename,
        )
        legacy = ()
        if (
            self._legacy_constructor is None
            and self.storage.env_filename == DEFAULT_STORAGE_ENV_FILENAME
        ):
            legacy = (
                preferred.with_name(LEGACY_STORAGE_ENV_FILENAME),
                preferred.with_name(".env.local"),
            )
        return resolve_managed_file(
            preferred=preferred,
            legacy_candidates=legacy,
            label="storage dotenv",
        )

    def storage_env_path(self, storage_root: Path) -> Path:
        """Return the active dotenv path inside one storage root."""
        return self.storage_env_resolution(storage_root).selected

    def config_paths(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> AppConfigHome:
        """Return AppRC-managed paths without creating files."""
        return resolve_app_config_home(
            app_name=self.app_name,
            app_env_path=self.app_env_path(),
            apprc_toml_path=self.apprc_toml_path(proc_env=proc_env),
        )

    def ensure_app_env(self) -> Path:
        """Create the app dotenv file for an explicit write."""
        return ensure_text_file(self.app_env_path())

    def ensure_apprc_toml(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create the AppRC TOML file for an explicit storage write."""
        return ensure_text_file(self.apprc_toml_path(proc_env=proc_env))

    def apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the environment override or conventional AppRC TOML path."""
        return self.apprc_toml_resolution(proc_env=proc_env).selected

    def apprc_toml_resolution(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> ManagedFileResolution:
        """Return the active AppRC TOML path and migration candidates.

        :param proc_env: Environment mapping used for relocation lookup.
        :return: Deterministic current-or-legacy file selection.
        """
        env = os.environ if proc_env is None else proc_env
        raw_path = env.get(self.apprc_toml_env_key, "").strip()
        if raw_path:
            overridden = normalize_apprc_toml_path(raw_path)
            return resolve_managed_file(
                preferred=overridden,
                label="AppRC TOML",
            )
        preferred = self.preferred_apprc_toml_path()
        legacy = ()
        if (
            self._legacy_constructor is None
            and self.apprc_toml_filename == DEFAULT_APPRC_TOML_FILENAME
        ):
            legacy = (
                preferred.with_name(
                    self.derive_legacy_apprc_toml_filename(self.app_name)
                ),
            )
        return resolve_managed_file(
            preferred=preferred,
            legacy_candidates=legacy,
            label="AppRC TOML",
        )

    def require_storage_selector_env_key(self) -> str:
        """Return the storage selector key or raise for storage-free apps."""
        if self.storage_selector_env_key is None:
            raise ValueError(f"{self.display_name} does not use AppRC storage.")
        return self.storage_selector_env_key

    # -- 0.19 compatibility -------------------------------------

    @property
    def storage_layer(self) -> StorageLayerState:
        """Return the deprecated storage capability state."""
        return (
            StorageLayerState.REQUIRED
            if self.uses_storage()
            else StorageLayerState.DISABLED
        )

    @property
    def app_wide_layer(self) -> CapabilityState:
        """Return the deprecated app dotenv capability state."""
        if not self.app_env_enabled():
            return CapabilityState.DISABLED
        if self.setup_creates_app_env():
            return CapabilityState.DEFAULT
        return CapabilityState.OPTIONAL

    @property
    def named_storage_layer(self) -> CapabilityState:
        """Return the deprecated named-storage capability state."""
        if not self.named_storage_enabled():
            return CapabilityState.DISABLED
        if self.apprc_toml_required():
            return CapabilityState.DEFAULT
        return CapabilityState.OPTIONAL

    @property
    def storage_env_key(self) -> str | None:
        """Return the deprecated storage selector key property."""
        return self.storage_selector_env_key

    @property
    def index_env_key(self) -> str:
        """Return the deprecated AppRC TOML environment key property."""
        return self.apprc_toml_env_key

    @property
    def index_filename(self) -> str:
        """Return the deprecated AppRC TOML filename property."""
        return self.apprc_toml_filename

    @property
    def shared_env_filename(self) -> str:
        """Return the deprecated packaged defaults filename property."""
        return self.defaults_env_filename

    @property
    def app_wide_env_filename(self) -> str:
        """Return the deprecated app dotenv filename property."""
        return self.app_env_filename

    @property
    def storage_env_filename(self) -> str:
        """Return the deprecated storage dotenv filename property."""
        if self.storage is None:
            return DEFAULT_STORAGE_ENV_FILENAME
        return self.storage.env_filename

    def storage_required(self) -> bool:
        """Return the deprecated storage requirement predicate."""
        return self.uses_storage()

    def app_wide_allowed(self) -> bool:
        """Return the deprecated app dotenv availability predicate."""
        return self.app_env_enabled()

    def app_wide_default(self) -> bool:
        """Return the deprecated app dotenv setup predicate."""
        return self.setup_creates_app_env()

    def named_storage_allowed(self) -> bool:
        """Return the deprecated named-storage availability predicate."""
        return self.named_storage_enabled()

    def named_storage_default(self) -> bool:
        """Return the deprecated AppRC TOML requirement predicate."""
        return self.apprc_toml_required()

    def default_index_path(self) -> Path:
        """Return the deprecated preferred AppRC TOML path."""
        return self.preferred_apprc_toml_path()

    def app_wide_env_path(self) -> Path:
        """Return the deprecated app dotenv path."""
        return self.app_env_path()

    def ensure_app_wide_env(self) -> Path:
        """Create the app dotenv through the deprecated method name."""
        return self.ensure_app_env()

    def ensure_index_file(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Create AppRC TOML through the deprecated method name."""
        return self.ensure_apprc_toml(proc_env=proc_env)

    def required_index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return AppRC TOML through the deprecated method name."""
        return self.apprc_toml_path(proc_env=proc_env)

    def optional_index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return AppRC TOML through the deprecated method name."""
        return self.apprc_toml_path(proc_env=proc_env)

    def index_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return AppRC TOML through the deprecated method name."""
        return self.apprc_toml_path(proc_env=proc_env)

    def require_storage_env_key(self) -> str:
        """Return the deprecated storage selector key."""
        return self.require_storage_selector_env_key()
