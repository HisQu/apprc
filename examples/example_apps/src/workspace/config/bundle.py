"""Top-level config bundle for the workspace example."""

from dataclasses import dataclass, field

from workspace.config.app import MyRC
from workspace.config.sections.app import AppSettings


@MyRC.bundle
@dataclass(kw_only=True)
class WorkspaceExampleConfig:
    """Aggregate the example's env-backed settings."""

    app: AppSettings = field(default_factory=AppSettings)
