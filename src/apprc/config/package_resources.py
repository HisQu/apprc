"""Package resource discovery helpers for AppRC integrations."""

from __future__ import annotations

# == Standard Library ========================
from importlib import import_module
from pathlib import Path
from types import ModuleType


def resolve_package_root(pkg: ModuleType | str) -> Path:
    """Return the filesystem directory for a regular package.

    Requires an ``__init__.py`` on disk and intentionally rejects namespace,
    frozen, and zip-backed packages because AppRC needs a concrete directory for
    packaged dotenv resources.

    :param pkg: Imported package module or import path, e.g. ``your_app.rag``.
    :return: Package directory on disk.
    :raises RuntimeError: If no usable directory can be determined.
    """
    module = pkg if isinstance(pkg, ModuleType) else import_module(pkg)
    origin = None if module.__spec__ is None else module.__spec__.origin
    if isinstance(origin, str):
        origin_path = Path(origin)
        if origin_path.name == "__init__.py" and origin_path.is_file():
            return origin_path.resolve().parent
    module_file = getattr(module, "__file__", None)
    if module_file:
        module_path = Path(module_file).resolve()
        if module_path.name == "__init__.py" and module_path.is_file():
            return module_path.parent
    raise RuntimeError(
        f"Cannot determine package directory for {module.__name__!r}. "
        "Expected a regular package with an __init__.py on disk."
    )
