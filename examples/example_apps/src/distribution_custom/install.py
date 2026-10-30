"""Example repository-owned install ordering through public lifecycle primitives."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from apprc.definition.installation import (
    InstallPlan,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    UvToolTarget,
)
from apprc.distribution.models import DistributionSpec
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    SourceSelection,
    parse_source_arguments,
)
from apprc.distribution.runtime.installation import install_prepared_application
from apprc.user_files.installation.operations import plan_install


def plan_custom_install(
    spec: DistributionSpec,
    arguments: Sequence[str],
    *,
    identity: InstallationIdentity,
    placement: InstallationPlacement,
    backend: UvToolTarget,
    inspection: InstallationInspection,
) -> tuple[InstallPlan, SourceSelection, tuple[str, ...]]:
    """Select the exact bootstrap source before planning or parsing app flags."""
    selection, remaining = parse_source_arguments(spec, arguments)
    plan = plan_install(
        identity, selection.source, placement, backend, inspection=inspection
    )
    return plan, selection, remaining


def install_with_project_setup(
    plan: InstallPlan,
    *,
    selection: SourceSelection,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
    prepare_project: Callable[[PreparedSource], None],
) -> InstallationInspection:
    """Run acquisition, project setup, then the complete locked install transaction.

    The repository owns the order of source preparation and its project action;
    ``install_prepared_application`` then validates the exact prepared input and
    performs backend mutation, target probing, support publication, checkpoints,
    and commit. There is no required framework or hook registry.

    :param plan: Captured exact installation plan.
    :param environment: Explicit backend subprocess environment.
    :param probe_path: Staged target interpreter probe.
    :param support_files: Exact saved support payloads.
    :param python_requirement: Exact project ``requires-python`` expression.
    :param prepare_project: This repository's setup action for the verified source.
    :return: Ready observed installation inspection.
    """
    with TemporaryDirectory(prefix="apprc-project-setup-") as temporary:
        prepared = selection.prepare(Path(temporary))
        prepare_project(prepared)
        return install_prepared_application(
            plan,
            prepared,
            environment=environment,
            probe_path=probe_path,
            support_files=support_files,
            python_requirement=python_requirement,
        )
