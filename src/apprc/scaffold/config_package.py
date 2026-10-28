"""Generate AppRC's recommended config package layout."""

# == Standard Library ========================
import re
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ConfigScaffoldRequest:
    """Input values for one generated config package."""

    package: str
    app_id: str
    target: Path
    user_dotenv: bool = False
    workspaces: bool = False
    display_name: str | None = None
    workspace_selector_env_key: str | None = None
    env_prefix: str | None = None
    force: bool = False


@dataclass(frozen=True, slots=True)
class ConfigScaffoldResult:
    """Files written by the config package scaffold."""

    config_package_dir: Path
    written_files: tuple[Path, ...]


def scaffold_config_package(
    request: ConfigScaffoldRequest,
) -> ConfigScaffoldResult:
    """Create AppRC's standard config package files."""
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
            "AppRC config scaffold target files already exist. Pass --force to replace them:\n"
            f"{joined}"
        )
    _ensure_package_dirs(request.target, package_parts)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return ConfigScaffoldResult(
        config_package_dir=config_dir, written_files=tuple(files)
    )


def _validate_request(request: ConfigScaffoldRequest) -> None:
    """Reject inconsistent scaffold inputs before touching the filesystem."""
    _validate_package(request.package)
    if not request.app_id:
        raise ValueError("--app-id must be non-empty.")
    if not request.workspaces and request.workspace_selector_env_key:
        raise ValueError("--workspace-selector-env-key requires --workspaces.")
    if request.workspace_selector_env_key and request.env_prefix:
        if not request.workspace_selector_env_key.startswith(
            request.env_prefix
        ):
            raise ValueError(
                f"--workspace-selector-env-key {request.workspace_selector_env_key!r} must "
                f"start with --env-prefix {request.env_prefix!r}."
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
    key = request.workspace_selector_env_key
    if key and "_" in key:
        return key.rsplit("_", 1)[0] + "_"
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
        config_dir / "app.py": _render_app_module(
            request=request, module_prefix=module_prefix
        ),
        config_dir / "sections" / "__init__.py": _render_sections_init(),
        config_dir / "sections" / "app.py": _render_section_module(
            request=request, env_prefix=env_prefix
        ),
        config_dir / "bundle.py": _render_bundle_module(
            module_prefix=module_prefix, bundle_name=bundle_name
        ),
    }


def _render_config_init() -> str:
    """Render a package initializer that imports no application sections."""
    return '"""Application configuration. Import chosen sections before resolving."""\n'


def _render_app_module(
    *, request: ConfigScaffoldRequest, module_prefix: str
) -> str:
    """Render ``config/app.py``."""
    display_name = request.display_name or request.app_id
    paths_line = (
        "    paths=rc.Paths(config=True),\n"
        if request.user_dotenv or request.workspaces
        else ""
    )
    user_dotenv_line = (
        "    user_dotenv=rc.UserDotenv(),\n" if request.user_dotenv else ""
    )
    workspace_line = ""
    if request.workspaces:
        key = (
            f"selector_env_key={request.workspace_selector_env_key!r}"
            if request.workspace_selector_env_key is not None
            else ""
        )
        workspace_line = f"    workspaces=rc.Workspaces({key}),\n"
    return f'''"""AppRC application contract."""

import apprc as rc


MyRC = rc.AppRC(
    app_id={request.app_id!r},
    display_name={display_name!r},
    config_package={module_prefix!r},
{paths_line}{user_dotenv_line}{workspace_line}    command_name={request.app_id!r},
)

'''


def _render_sections_init() -> str:
    """Render the lightweight section namespace."""
    return '"""Application configuration sections."""\n'


def _render_section_module(
    *, request: ConfigScaffoldRequest, env_prefix: str
) -> str:
    """Render ``config/sections/app.py``."""
    return f'''"""App-owned AppRC config section."""

import apprc as rc

from {request.package}.config.app import MyRC


@MyRC.config("app", prefix={env_prefix!r}, title="App")
class AppSection(rc.Config):
    profile: str = rc.field(
        {f"{env_prefix}PROFILE"!r},
        default="default",
        title="Profile",
        explanation_short="Application profile name.",
    )
'''


def _render_bundle_module(*, module_prefix: str, bundle_name: str) -> str:
    """Render one bundle combining generated sections."""
    return f'''"""Bundle for the generated AppRC config sections."""

from dataclasses import dataclass, field

import apprc as rc

from {module_prefix}.app import MyRC
from {module_prefix}.sections.app import AppSection


@MyRC.bundle
@dataclass(kw_only=True)
class {bundle_name}(rc.ConfigBase):
    app: AppSection = field(default_factory=AppSection)
'''
