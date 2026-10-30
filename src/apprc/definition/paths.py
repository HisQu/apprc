"""Independent filesystem capabilities and their resolved locations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from apprc.definition.installation import InstallationSnapshot

ResourceKind = Literal["config", "appdata", "cache", "state"]
PathKind = Literal["config", "appdata", "cache", "state", "logs"]
LayoutSource = Literal[
    "invocation", "environment", "installation", "declaration", "default"
]


@dataclass(frozen=True, slots=True)
class Paths:
    """Declare capabilities without reading or creating filesystem locations."""

    config: bool = False
    appdata: bool = False
    cache: bool = False
    state: bool = False


@dataclass(frozen=True, slots=True)
class Layout:
    """Select native locations or one absolute application root.

    Relative roots are captured against the invocation's current directory.
    """

    mode: Literal["native", "single-root"] = "native"
    root: Path | None = None

    def __post_init__(self) -> None:
        """Validate the pair and detach roots from subsequent CWD changes."""
        if self.mode == "native":
            if self.root is not None:
                raise ValueError("Native layout does not accept a root.")
        elif self.mode == "single-root":
            if self.root is None:
                raise ValueError("Single-root layout requires a root.")
            object.__setattr__(
                self, "root", Path(os.path.abspath(self.root.expanduser()))
            )
        else:
            raise ValueError(f"Unknown AppRC layout: {self.mode!r}.")

    @classmethod
    def native(cls) -> Layout:
        """Select the operating system's standard locations."""
        return cls()

    @classmethod
    def single_root(cls, root: str | Path) -> Layout:
        """Select colocated component directories below ``root``.

        :param root: Application root, resolved against the current directory.
        :return: An immutable layout with an absolute root.
        """
        return cls(mode="single-root", root=Path(root))


@dataclass(frozen=True, slots=True)
class AppPaths:
    """One invocation's resolved paths; disabled capabilities remain absent."""

    layout: Layout
    source: LayoutSource
    config_dir: Path | None
    appdata_dir: Path | None
    cache_dir: Path | None
    state_dir: Path | None
    logs_dir: Path | None
    installation: InstallationSnapshot

    def require(self, kind: PathKind) -> Path:
        """Return an enabled location without creating it.

        :param kind: Component or subordinate log location.
        :return: The captured absolute directory path.
        :raises ValueError: If the requested component is disabled.
        """
        locations = {
            "config": self.config_dir,
            "appdata": self.appdata_dir,
            "cache": self.cache_dir,
            "state": self.state_dir,
            "logs": self.logs_dir,
        }
        path = locations[kind]
        if path is None:
            raise ValueError(f"AppRC path component '{kind}' is not enabled.")
        return path
