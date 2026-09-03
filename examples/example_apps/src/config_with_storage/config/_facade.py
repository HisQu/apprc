"""Lazy exports for the config-with-storage example config package."""

# pyright: reportUnsupportedDunderAll=false

from importlib import import_module


_ALL_EXPORTS = (
    "CONFIG_SECTIONS",
    "CONFIG_SPEC",
    "AppSettings",
    "ConfigWithStorageExampleConfig",
    "KIT",
    "MyRC",
    "SECTION_BY_KEY",
)

_EXPORT_MODULES = {
    "CONFIG_SECTIONS": ".catalog",
    "CONFIG_SPEC": ".catalog",
    "AppSettings": ".sections.app",
    "ConfigWithStorageExampleConfig": ".bundle",
    "KIT": ".catalog",
    "MyRC": ".app",
    "SECTION_BY_KEY": ".catalog",
}

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
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc
    module = import_module(module_name, __package__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List normal module attributes and lazy public exports.

    :return: Sorted module attribute names.
    """
    return sorted({*globals(), *__all__})
