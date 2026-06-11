"""Resolve package roots and user-owned local directories.

Most AppRC code uses the newer config registry and dotenv helpers in
``apprc.config``. This module remains as a small compatibility utility layer
for projects that need package-root lookup or direct env-var-to-directory
resolution outside the full AppConfigKit workflow.
"""

from __future__ import annotations

# == Standard Library ========================
import logging
import os
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

# == 3rd Party ===============================
from dotenv import dotenv_values, find_dotenv

LOG = logging.getLogger(__name__)


def package_root_dir(mod: ModuleType) -> Path:
    """Return the filesystem directory for a regular (non-namespace) package.

    Requires an ``__init__.py`` on disk (i.e., rejects PEP 420 namespace packages).
    Intentionally fails for non-filesystem imports (frozen/zip/etc.).

    This prefers :attr:`module.__spec__.origin` (PEP 451)
    and falls back to :attr:`module.__file__` when needed.

    :param mod: Imported package module.
    :return: Package directory on disk.
    :raises RuntimeError: If no usable directory can be determined.
    """
    # -- Prefer __spec__.origin ---------------------------------------
    # > e.g.: opa.rag.__spec__.origin = "./OPA/src/opa/rag/__init__.py"
    spec: ModuleSpec | None = getattr(mod, "__spec__", None)
    origin: str | None = getattr(spec, "origin", None) or None
    if origin and isinstance(origin, str):
        origin_path = Path(origin)
        if origin_path.name == "__init__.py" and origin_path.is_file():
            return origin_path.resolve().parent  # !! Early exit
    # -- Fallback to __file__ -----------------------------------------
    module_file = getattr(mod, "__file__", None)
    if module_file:
        module_path = Path(module_file).resolve()
        if module_path.name == "__init__.py" and module_path.is_file():
            return module_path.parent
    raise RuntimeError(
        f"Cannot determine package directory for {mod.__name__!r}. "
        "Expected a regular package with an __init__.py on disk."
    )


def _read_dotenv_var(env_file: Path, var_name: str) -> str | None:
    """Read one dotenv value without mutating ``os.environ``.

    :param env_file: Dotenv file to parse.
    :param var_name: Variable name to look up.
    :return: String value or ``None`` when the key is absent.
    """
    env_path = env_file.expanduser().resolve()
    if not env_path.is_file():
        raise RuntimeError(f".env file not found: {env_path}")

    values = dotenv_values(env_path)
    return values.get(var_name)


def require_env(
    var_name: str,
    *,
    env_file: str | Path | None = None,
    allow_os_env: bool = True,
) -> str:
    """Return a required variable from dotenv or the process environment.

    Resolution order:
    1. ``env_file`` when provided.
    2. ``os.environ`` when ``allow_os_env`` is true.

    :param var_name: Environment variable name.
    :param env_file: Optional path to a specific .env file to read.
    :param allow_os_env: If False, do not consult os.environ.
    :raises RuntimeError: If the variable is not set or empty.
    """
    value: str | None = None

    if env_file is not None:
        env_file = Path(find_dotenv(str(env_file)))
        value = _read_dotenv_var(env_file, var_name)
    if (value is None or not value.strip()) and allow_os_env:
        value = os.getenv(var_name)
    if value is None or not value.strip():
        where = []
        if env_file is not None:
            where.append(f".env file ({Path(env_file).expanduser().resolve()})")
        if allow_os_env:
            where.append("process environment")
        where_txt = " and ".join(where) if where else "nowhere"

        raise RuntimeError(
            f"Missing required environment variable: {var_name}\n"
            f"Searched: {where_txt}\n"
            f"Set it, e.g.\n"
            f"  {var_name}=/absolute/path/to/opa_rag"
        )
    return value


def get_local_dir_from_env(
    env_var: str,
    *,
    env_file: str | Path | None = None,
    allow_os_env: bool = True,
) -> Path:
    """Return the local root directory for user-writable resources.

    Enforced via a single source to keep behavior deterministic.

    :param env_var: Name of the env var holding the root path.
    :param env_file: Optional path to a specific .env file to read.
    :param allow_os_env: If False, do not consult os.environ.
    """
    root = (
        Path(require_env(env_var, env_file=env_file, allow_os_env=allow_os_env))
        .expanduser()
        .resolve()
    )
    if env_file is not None:
        env_file = Path(env_file)
        LOG.info(
            f"Using '{env_var}' from .env file '{Path(env_file).expanduser().resolve()}': '{root}'."
        )
    else:
        LOG.info(f"Using '{env_var}' from environment: '{root}'.")
    return root
