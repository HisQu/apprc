"""Generate AppRC's recommended config package layout."""

# == Standard Library ========================
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re

_PACKAGE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ConfigScaffoldRequest:
    """Input values for one generated config package.

    :param package: Import package that receives ``config/``.
    :param storage: Whether the generated app declares storage.
    :param app_id: Stable AppRC application name.
    :param display_name: Human-readable application label.
    :param target: Source root containing the package.
    :param storage_selector_env_key: Optional storage selector env key override.
    :param env_prefix: Prefix used by the generated env-backed section.
    :param force: Whether existing generated files may be replaced.
    """

    package: str
    app_id: str
    target: Path
    storage: bool = False
    display_name: str | None = None
    storage_selector_env_key: str | None = None
    env_prefix: str | None = None
    force: bool = False


@dataclass(frozen=True, slots=True)
class ConfigScaffoldResult:
    """Files written by the config package scaffold.

    :param config_package_dir: Directory containing the generated config
        package.
    :param written_files: Files created or replaced by the scaffold.
    """

    config_package_dir: Path
    written_files: tuple[Path, ...]


def scaffold_config_package(
    request: ConfigScaffoldRequest,
) -> ConfigScaffoldResult:
    """Create AppRC's standard config package files.

    :param request: Scaffold inputs from the CLI or a test.
    :return: Paths written by the scaffold.
    :raises ValueError: If request values are inconsistent.
    :raises FileExistsError: If generated files already exist and
        ``force`` is false.
    """
    _validate_request(request)
    package_parts = tuple(request.package.split("."))
    package_dir = request.target.joinpath(*package_parts)
    config_dir = package_dir / "config"
    env_prefix = request.env_prefix or _default_env_prefix(request)
    bundle_name = f"{_pascal_identifier(request.app_id)}Config"
    files = _render_files(
        request=request,
        config_dir=config_dir,
        env_prefix=env_prefix,
        bundle_name=bundle_name,
    )
    existing_files = tuple(path for path in files if path.exists())
    if existing_files and not request.force:
        joined = "\n".join(f"- {path}" for path in existing_files)
        raise FileExistsError(
            "AppRC config scaffold target files already exist. "
            "Pass --force to replace them:\n"
            f"{joined}"
        )

    _ensure_package_dirs(request.target, package_parts)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return ConfigScaffoldResult(
        config_package_dir=config_dir,
        written_files=tuple(files),
    )


def _validate_request(request: ConfigScaffoldRequest) -> None:
    """Reject inconsistent scaffold inputs before touching the filesystem."""
    _validate_package(request.package)
    if not request.app_id:
        raise ValueError("--app-id must be non-empty.")
    if not request.storage and request.storage_selector_env_key:
        raise ValueError("--storage-selector-env-key requires --storage.")
    if request.storage_selector_env_key and request.env_prefix:
        _validate_env_key_prefix(
            storage_selector_env_key=request.storage_selector_env_key,
            env_prefix=request.env_prefix,
        )


def _validate_package(package: str) -> None:
    """Validate a dotted import package."""
    parts = package.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError("--package must be a dotted Python package name.")
    invalid = [part for part in parts if not _PACKAGE_TOKEN.fullmatch(part)]
    if invalid:
        raise ValueError(
            "--package contains invalid Python package segments: "
            + ", ".join(invalid)
        )


def _validate_env_key_prefix(
    *,
    storage_selector_env_key: str,
    env_prefix: str,
) -> None:
    """Ensure generated storage fields satisfy AppRC prefix validation."""
    if not storage_selector_env_key.startswith(env_prefix):
        raise ValueError(
            f"--storage-selector-env-key {storage_selector_env_key!r} must "
            "start with "
            f"--env-prefix {env_prefix!r}."
        )


def _ensure_package_dirs(target: Path, package_parts: tuple[str, ...]) -> None:
    """Create missing parent package ``__init__.py`` files."""
    current = target
    for part in package_parts:
        current = current / part
        current.mkdir(parents=True, exist_ok=True)
        init_path = current / "__init__.py"
        if not init_path.exists():
            init_path.write_text(
                '"""Application package."""\n', encoding="utf-8"
            )


def _default_env_prefix(request: ConfigScaffoldRequest) -> str:
    """Return an explicit generated prefix for the example section."""
    if (
        request.storage_selector_env_key
        and "_" in request.storage_selector_env_key
    ):
        return request.storage_selector_env_key.rsplit("_", 1)[0] + "_"
    return _upper_env_token(request.app_id) + "_"


def _upper_env_token(value: str) -> str:
    """Convert free-form app names into shell-friendly env-token text."""
    token = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return token.upper() or "APP"


def _pascal_identifier(value: str) -> str:
    """Convert free-form app names into a Python class stem."""
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    if not parts:
        return "App"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _render_files(
    *,
    request: ConfigScaffoldRequest,
    config_dir: Path,
    env_prefix: str,
    bundle_name: str,
) -> dict[Path, str]:
    """Render all files in the standard AppRC config package layout."""
    module_prefix = f"{request.package}.config"
    return {
        config_dir / "__init__.py": _render_config_init(),
        config_dir / "__init__.pyi": _render_config_stub(
            bundle_name=bundle_name,
        ),
        config_dir / "_facade.py": _render_config_facade(
            bundle_name=bundle_name,
        ),
        config_dir / "app.py": _render_app_module(
            request=request,
            module_prefix=module_prefix,
        ),
        config_dir / "sections" / "__init__.py": _render_sections_init(),
        config_dir / "sections" / "__init__.pyi": _render_sections_stub(),
        config_dir / "sections" / "_facade.py": _render_sections_facade(),
        config_dir / "sections" / "app.py": _render_section_module(
            request=request,
            env_prefix=env_prefix,
        ),
        config_dir / "bundle.py": _render_bundle_module(
            module_prefix=module_prefix,
            bundle_name=bundle_name,
        ),
        config_dir / "catalog.py": _render_catalog_module(
            module_prefix=module_prefix,
        ),
    }


def _render_config_init() -> str:
    """Render ``config/__init__.py``."""
    return '''"""Application AppRC config package."""

# ruff: noqa: F401

from ._facade import __all__, __dir__, __getattr__
'''


def _render_config_stub(*, bundle_name: str) -> str:
    """Render ``config/__init__.pyi``."""
    return f'''"""Typed surface for the AppRC config package."""

# ruff: noqa: F401

from .app import MyRC as MyRC
from .bundle import {bundle_name} as {bundle_name}
from .catalog import (
    CONFIG_SECTIONS as CONFIG_SECTIONS,
    CONFIG_SPEC as CONFIG_SPEC,
    SECTION_BY_KEY as SECTION_BY_KEY,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
'''


def _render_config_facade(*, bundle_name: str) -> str:
    """Render ``config/_facade.py``."""
    return _render_lazy_facade(
        docstring="Application AppRC config package.",
        export_modules={
            "CONFIG_SECTIONS": ".catalog",
            "CONFIG_SPEC": ".catalog",
            "MyRC": ".app",
            "SECTION_BY_KEY": ".catalog",
            bundle_name: ".bundle",
        },
    )


def _render_app_module(
    *,
    request: ConfigScaffoldRequest,
    module_prefix: str,
) -> str:
    """Render ``config/app.py``."""
    display_name = request.display_name or request.app_id
    storage_line = ""
    if request.storage:
        env_key = (
            f"selector_env_key={request.storage_selector_env_key!r}"
            if request.storage_selector_env_key is not None
            else ""
        )
        storage_line = f"    storage=rc.Storage({env_key}),\n"
    return f'''"""AppRC application contract."""

import apprc as rc


MyRC = rc.AppRC(
    app_id={request.app_id!r},
    display_name={display_name!r},
    config_package={module_prefix!r},
{storage_line}    command_name={request.app_id!r},
)

'''


def _render_sections_init() -> str:
    """Render ``config/sections/__init__.py``."""
    return '''"""AppRC config section namespace."""

# ruff: noqa: F401

from ._facade import __all__, __dir__, __getattr__
'''


def _render_sections_stub() -> str:
    """Render ``config/sections/__init__.pyi``."""
    return '''"""Typed surface for the AppRC config section namespace."""

# ruff: noqa: F401

from .app import AppSection as AppSection

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
'''


def _render_sections_facade() -> str:
    """Render ``config/sections/_facade.py``."""
    return _render_lazy_facade(
        docstring="AppRC config section namespace.",
        export_modules={
            "AppSection": ".app",
        },
    )


def _render_section_module(
    *,
    request: ConfigScaffoldRequest,
    env_prefix: str,
) -> str:
    """Render ``config/sections/app.py``."""
    imports = "from pathlib import Path\n\n" if request.storage else ""
    storage_field = ""
    if request.storage_selector_env_key is not None:
        _validate_env_key_prefix(
            storage_selector_env_key=request.storage_selector_env_key,
            env_prefix=env_prefix,
        )
        storage_field = f"""    storage_root: Path = rc.field(
        {request.storage_selector_env_key!r},
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root selected for this run.",
    )
"""
    return f'''"""App-owned AppRC config section."""

{imports}import apprc as rc

from {request.package}.config.app import MyRC


@MyRC.config("app", prefix={env_prefix!r}, title="App")
class AppSection(rc.Config):
    """Env-backed application settings."""

{storage_field}    profile: str = rc.field(
        {f"{env_prefix}PROFILE"!r},
        default="default",
        title="Profile",
        explanation_short="Named profile resolved from AppRC env layers.",
    )
'''


def _render_bundle_module(
    *,
    module_prefix: str,
    bundle_name: str,
) -> str:
    """Render ``config/bundle.py``."""
    return f'''"""Top-level AppRC config bundle."""

from dataclasses import dataclass, field

from {module_prefix}.app import MyRC
from {module_prefix}.sections.app import AppSection


@MyRC.bundle
@dataclass(kw_only=True)
class {bundle_name}:
    """Aggregate all registered AppRC config sections."""

    app: AppSection = field(default_factory=AppSection)
'''


def _render_lazy_facade(
    *,
    docstring: str,
    export_modules: Mapping[str, str],
) -> str:
    """Render a lightweight package facade.

    :param docstring: Module docstring for the generated package file.
    :param export_modules: Public names mapped to relative module imports.
    :return: Python source for a lazy facade module.
    """
    export_lines = "\n".join(
        f'    "{export_name}",' for export_name in export_modules
    )
    mapping_lines = "\n".join(
        f'    "{export_name}": "{module_name}",'
        for export_name, module_name in export_modules.items()
    )
    return f'''"""{docstring}"""

# pyright: reportUnsupportedDunderAll=false

from importlib import import_module


_ALL_EXPORTS = (
{export_lines}
)

_EXPORT_MODULES = {{
{mapping_lines}
}}

__all__ = list(_ALL_EXPORTS)


def __getattr__(name: str) -> object:
    """Load one public config export on first use.

    :param name: Export requested through attribute access or import machinery.
    :return: Exported object resolved from its owner module.
    """
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {{__name__!r}} has no attribute {{name!r}}"
        ) from exc
    module = import_module(module_name, __package__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List normal module attributes and lazy public exports.

    :return: Sorted module attribute names.
    """
    return sorted({{*globals(), *__all__}})
'''


def _render_catalog_module(*, module_prefix: str) -> str:
    """Render ``config/catalog.py``."""
    return f'''"""AppRC config section catalog."""

import importlib

from {module_prefix}.app import MyRC

importlib.import_module({f"{module_prefix}.bundle"!r})

KIT = MyRC.kit
CONFIG_SPEC = KIT.spec
CONFIG_SECTIONS = CONFIG_SPEC.owners
SECTION_BY_KEY = {{section.key: section for section in CONFIG_SECTIONS}}

__all__ = [
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "KIT",
    "SECTION_BY_KEY",
]
'''
