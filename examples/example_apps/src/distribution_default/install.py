"""Default install composition using the maintained lifecycle transaction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from apprc.definition.installation import InstallPlan, InstallationInspection
from apprc.distribution.runtime.acquisition import SourceSelection
from apprc.distribution.runtime.installation import install_prepared_application


def install_default(
    plan: InstallPlan,
    *,
    selection: SourceSelection,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
) -> InstallationInspection:
    """Install from the exact selected source and save the current support outputs."""
    with TemporaryDirectory(prefix="apprc-install-source-") as temporary:
        prepared = selection.prepare(Path(temporary))
        return install_prepared_application(
            plan,
            prepared,
            environment=environment,
            probe_path=probe_path,
            support_files=support_files,
            python_requirement=python_requirement,
        )
