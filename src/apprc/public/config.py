"""Public AppRC config base classes."""

# == Internal ================================
from apprc.definition.env_config.base import BaseConfig as ConfigBase
from apprc.definition.env_config.env import EnvConfig


class Config(EnvConfig):
    """Env-backed AppRC config base.

    Subclasses read values from the current process environment after AppRC
    bootstrap has prepared the runtime layers. Every env-backed attribute must
    be declared with :func:`apprc.field` and every subclass must be registered
    with ``@MyRC.config("key", prefix="FULL_PREFIX_", ...)`` before it is
    constructed.
    """

    __slots__ = ()


__all__ = [
    "Config",
    "ConfigBase",
]
