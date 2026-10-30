from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.installation import InstallationSnapshot
from apprc.definition.maintenance import (
    AppDataOperations,
    CacheOperations,
    MaintenanceHandlers,
    RemovalOperation,
    RemovalPlan,
    RemovalResult,
)
from apprc.definition.paths import AppPaths, Layout, Paths, ResourceKind
from apprc.services.maintenance import (
    MaintenanceManager,
    _MaintenanceApplyError,
)
from apprc.user_files.app_home.ownership import (
    ensure_owned_path,
    inspect_ownership,
)
from apprc.user_files.app_home.removal import apply_removal, plan_removal
from apprc.user_files.app_home.writes import managed_lock_path


def _spec(
    app_id: str = "maintenance-test",
    paths: Paths = Paths(appdata=True, cache=True, state=True),
) -> AppConfigSpec:
    return AppConfigSpec(
        app_id=app_id, display_name="Maintenance test", paths=paths
    )


def _paths(root: Path, *, logs: Path | None = None) -> AppPaths:
    return AppPaths(
        layout=Layout.single_root(root),
        source="invocation",
        config_dir=root / "config",
        appdata_dir=root / "appdata",
        cache_dir=root / "cache",
        state_dir=root / "state",
        logs_dir=logs,
        installation=InstallationSnapshot(root / "installation", None, None),
    )


def test_ownership_requires_adoption_and_marks_root(tmp_path: Path) -> None:
    spec = _spec(paths=Paths(cache=True))
    paths = _paths(tmp_path)
    root = paths.require("cache")
    root.mkdir(parents=True)
    (root / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="nonempty unowned"):
        ensure_owned_path(spec, paths, "cache")
    assert inspect_ownership(root, spec.app_id, "cache") == "unowned"
    ensure_owned_path(spec, paths, "cache", adopt=True)
    assert inspect_ownership(root, spec.app_id, "cache") == "owned"
    assert (root / "user.txt").read_text(encoding="utf-8") == "keep"


def test_ownership_rejects_marker_mismatch_and_symlink_roots(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(cache=True))
    paths = _paths(tmp_path)
    root = paths.require("cache")
    root.mkdir(parents=True)
    (root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"other","category":"cache"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Mismatched"):
        ensure_owned_path(spec, paths, "cache")
    target = tmp_path / "target"
    target.mkdir()
    marker = root / ".apprc-owner.json"
    marker.unlink()
    marker.symlink_to(target)
    with pytest.raises(ValueError, match="link"):
        inspect_ownership(root, spec.app_id, "cache")
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    unsafe = AppPaths(
        layout=Layout.single_root(tmp_path),
        source="invocation",
        config_dir=None,
        appdata_dir=None,
        cache_dir=link,
        state_dir=None,
        logs_dir=None,
        installation=InstallationSnapshot(
            tmp_path / "installation", None, None
        ),
    )
    with pytest.raises(ValueError, match="link"):
        ensure_owned_path(spec, unsafe, "cache")


def test_removal_plan_rejects_stale_filesystem(tmp_path: Path) -> None:
    spec = _spec(paths=Paths(cache=True))
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, "cache")
    marker = root / ".apprc-owner.json"
    original = marker.read_text(encoding="utf-8")
    plan = plan_removal("cache", root, spec.app_id)
    marker.write_text(original + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        apply_removal(plan, spec.app_id)
    assert marker.read_text(encoding="utf-8") == original + "\n"
    fresh = plan_removal("cache", root, spec.app_id)
    result = apply_removal(fresh, spec.app_id)
    assert result.removed == fresh.targets == (marker, root)
    assert not root.exists()


@pytest.mark.parametrize("category", ["appdata", "cache", "state"])
@pytest.mark.parametrize("nested", [False, True])
def test_generic_purge_refuses_unsupported_payload_without_changes(
    tmp_path: Path, category: ResourceKind, nested: bool
) -> None:
    spec = _spec()
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, category)
    marker = root / ".apprc-owner.json"
    before = marker.read_bytes()
    payload = root / "payload"
    if nested:
        payload.mkdir()
        payload = payload / "data"
    payload.write_bytes(b"keep")
    manager = MaintenanceManager(spec, app_paths=paths)
    with pytest.raises(ValueError):
        manager.plan_purge((category,))
    assert payload.read_bytes() == b"keep"
    assert marker.read_bytes() == before
    assert root.is_dir()


@pytest.mark.parametrize("category", ["cache", "config"])
@pytest.mark.parametrize("owned", [False, True])
def test_empty_purge_plan_and_result_include_exact_root_removal(
    tmp_path: Path, category: ResourceKind, owned: bool
) -> None:
    spec = _spec(paths=Paths(config=True, cache=True))
    paths = _paths(tmp_path)
    root = paths.require(category)
    if owned:
        ensure_owned_path(spec, paths, category)
    else:
        root.mkdir()
    lock = managed_lock_path(root)
    lock.touch(exist_ok=True)
    lock_identity = lock.stat().st_ino
    manager = MaintenanceManager(spec, app_paths=paths)
    (plan,) = manager.plan_purge((category,))
    expected = (root / ".apprc-owner.json", root) if owned else (root,)
    assert plan.targets == expected
    (result,) = manager.apply_purge((plan,))
    assert result.removed == expected
    assert result.skipped == ()
    assert not root.exists()
    assert lock.stat().st_ino == lock_identity


def test_unsupported_payload_added_after_planning_prevents_all_apply(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(config=True, cache=True))
    paths = _paths(tmp_path)
    config = ensure_owned_path(spec, paths, "config")
    cache = ensure_owned_path(spec, paths, "cache")
    manager = MaintenanceManager(spec, app_paths=paths)
    plans = manager.plan_purge(("config", "cache"))
    payload = cache / "new-data"
    payload.write_bytes(b"keep")
    with pytest.raises(ValueError):
        manager.apply_purge(plans)
    assert payload.read_bytes() == b"keep"
    assert (config / ".apprc-owner.json").is_file()
    assert (cache / ".apprc-owner.json").is_file()


def test_purge_preflights_all_scopes_before_provider_mutation(
    tmp_path: Path,
) -> None:
    spec = _spec()
    paths = _paths(tmp_path)
    calls: list[str] = []
    appdata_root = ensure_owned_path(spec, paths, "appdata")

    def provider_plan(root: Path) -> RemovalPlan:
        return RemovalPlan("appdata", root, (), "fresh")

    def provider_apply(plan: RemovalPlan) -> RemovalResult:
        calls.append("apply")
        return RemovalResult(())

    handlers = MaintenanceHandlers(
        appdata=AppDataOperations(
            purge=RemovalOperation(provider_plan, provider_apply)
        )
    )
    manager = MaintenanceManager(spec, app_paths=paths, handlers=handlers)
    assert appdata_root.is_dir()
    bad_root = paths.require("cache")
    bad_root.mkdir(parents=True)
    (bad_root / ".apprc-owner.json").write_text("invalid", encoding="utf-8")
    bad_plan = RemovalPlan("cache", bad_root, (), "invalid")
    with pytest.raises(ValueError):
        manager.apply_purge((provider_plan(appdata_root), bad_plan))
    assert calls == []


def test_missing_disabled_scopes_and_provider_declaration(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(cache=True))
    paths = _paths(tmp_path)
    manager = MaintenanceManager(spec, app_paths=paths)
    (plan,) = manager.plan_purge(("cache",))
    assert plan.targets == ()
    with pytest.raises(ValueError, match="not enabled"):
        manager.plan_purge(("appdata",))
    with pytest.raises(ValueError):
        manager.plan_cache_clear()
    with pytest.raises(ValueError, match="requires enabled"):
        MaintenanceManager(
            spec,
            app_paths=paths,
            handlers=MaintenanceHandlers(appdata=AppDataOperations()),
        )


def test_missing_root_purge_apply_does_not_create_root_or_lock(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(config=True, cache=True))
    paths = _paths(tmp_path)
    manager = MaintenanceManager(spec, app_paths=paths)
    plans = manager.plan_purge(("config", "cache"))

    results = manager.apply_purge(plans)

    assert results == (RemovalResult(()), RemovalResult(()))
    for root in (paths.require("config"), paths.require("cache")):
        assert not root.exists()
        assert not managed_lock_path(root).exists()


def test_state_external_and_nested_log_roots_are_deduplicated(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(state=True))
    paths = _paths(tmp_path, logs=tmp_path / "outside-logs")
    manager = MaintenanceManager(spec, app_paths=paths)
    plans = manager.plan_purge(("state",))
    assert {plan.root for plan in plans} == {
        paths.require("state"),
        paths.require("logs"),
    }
    nested_root = tmp_path / "nested"
    nested_paths = _paths(nested_root, logs=nested_root / "state" / "logs")
    nested = MaintenanceManager(spec, app_paths=nested_paths)
    assert len(nested.plan_purge(("state",))) == 1


def test_backup_rejects_destination_inside_appdata(tmp_path: Path) -> None:
    spec = _spec(paths=Paths(appdata=True))
    paths = _paths(tmp_path)
    handlers = MaintenanceHandlers(
        appdata=AppDataOperations(
            backup=lambda _root, _destination: pytest.fail(
                "unsafe backup dispatched"
            ),
        )
    )
    ensure_owned_path(spec, paths, "appdata")
    manager = MaintenanceManager(spec, app_paths=paths, handlers=handlers)
    with pytest.raises(ValueError):
        manager.backup_appdata(paths.require("appdata") / "nested")


def test_config_purge_preserves_unknown_files(tmp_path: Path) -> None:
    from apprc.user_files.purge import apply_config_purge, plan_config_purge

    spec = _spec(paths=Paths(config=True))
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, "config")
    unknown = root / "manual-notes.txt"
    unknown.write_text("keep", encoding="utf-8")
    managed = root / spec.user_dotenv_filename
    managed.write_text("VALUE=remove\n", encoding="utf-8")
    lock = managed_lock_path(root)
    lock_identity = lock.stat().st_ino
    plan = plan_config_purge(spec, paths)
    assert plan.targets == (managed, root / ".apprc-owner.json")
    result = apply_config_purge(plan, spec, paths)
    assert result.removed == plan.targets
    assert result.skipped == (unknown,)
    assert result.warnings
    assert unknown.read_text(encoding="utf-8") == "keep"
    assert root.is_dir()
    assert lock.stat().st_ino == lock_identity


def test_info_accepts_only_json_compatible_provider_values(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(appdata=True))
    paths = _paths(tmp_path)
    ensure_owned_path(spec, paths, "appdata")
    provider = AppDataOperations(
        info=lambda root: {"count": 3, "files": ["db"]}
    )
    manager = MaintenanceManager(
        spec, app_paths=paths, handlers=MaintenanceHandlers(appdata=provider)
    )
    assert manager.info("appdata") == {
        "category": "appdata",
        "roots": [
            {
                "root": str(paths.require("appdata")),
                "exists": True,
                "ownership": "owned",
                "details": {"count": 3, "files": ["db"]},
            }
        ],
    }
    invalid = MaintenanceManager(
        spec,
        app_paths=paths,
        handlers=MaintenanceHandlers(
            appdata=AppDataOperations(info=lambda root: {"value": object()})
        ),
    )
    with pytest.raises(TypeError, match="JSON-compatible"):
        invalid.info("appdata")


@pytest.mark.parametrize("boundary", ["traversal", "parent", "cross-root"])
def test_provider_plan_rejects_outside_targets(
    tmp_path: Path, boundary: str
) -> None:
    spec = _spec(paths=Paths(appdata=True, cache=True))
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, "appdata")
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")
    calls: list[bool] = []
    other_root = ensure_owned_path(spec, paths, "cache")
    target = {
        "traversal": root / ".." / "outside",
        "parent": tmp_path,
        "cross-root": other_root,
    }[boundary]
    plan = RemovalPlan("appdata", root, (target,), "revision")
    operations = RemovalOperation(
        plan=lambda selected_root: plan,
        apply=lambda selected_plan: calls.append(True) or RemovalResult(()),
    )
    manager = MaintenanceManager(
        spec,
        app_paths=paths,
        handlers=MaintenanceHandlers(
            appdata=AppDataOperations(purge=operations)
        ),
    )
    with pytest.raises(ValueError):
        manager.apply_purge((plan,))
    assert calls == []
    assert outside.read_text(encoding="utf-8") == "keep"
    assert (root / ".apprc-owner.json").is_file()
    assert (other_root / ".apprc-owner.json").is_file()


@pytest.mark.parametrize("remove_root", [False, True])
def test_provider_purge_preserves_exact_target_authority(
    tmp_path: Path, remove_root: bool
) -> None:
    spec = _spec(paths=Paths(appdata=True))
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, "appdata")
    payload = root / "known.db"
    payload.write_bytes(b"remove")
    marker = root / ".apprc-owner.json"
    unknown = root / "unknown"
    if remove_root:
        targets = (payload, marker, root)
    else:
        unknown.write_bytes(b"keep")
        targets = (payload,)
    plan = RemovalPlan("appdata", root, targets, "provider-revision")

    def apply(selected: RemovalPlan) -> RemovalResult:
        for target in selected.targets:
            if target == root:
                target.rmdir()
            else:
                target.unlink()
        return RemovalResult(selected.targets)

    manager = MaintenanceManager(
        spec,
        app_paths=paths,
        handlers=MaintenanceHandlers(
            appdata=AppDataOperations(
                purge=RemovalOperation(lambda selected_root: plan, apply)
            )
        ),
    )
    plans = manager.plan_purge(("appdata",))
    (result,) = manager.apply_purge(plans)
    assert result.removed == plan.targets
    if remove_root:
        assert not root.exists()
    else:
        assert marker.is_file()
        assert unknown.read_bytes() == b"keep"


def test_manager_rejects_overlapping_enabled_category_roots(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(config=True, cache=True))
    config_root = tmp_path / "config"
    cache_root = config_root / "cache"
    config_root.mkdir()
    cache_root.mkdir()
    (config_root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"maintenance-test","category":"config"}',
        encoding="utf-8",
    )
    (cache_root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"maintenance-test","category":"cache"}',
        encoding="utf-8",
    )
    paths = AppPaths(
        layout=Layout.single_root(tmp_path),
        source="invocation",
        config_dir=config_root,
        appdata_dir=None,
        cache_dir=cache_root,
        state_dir=None,
        logs_dir=None,
        installation=InstallationSnapshot(
            tmp_path / "installation", None, None
        ),
    )
    with pytest.raises(ValueError, match="category roots overlap"):
        MaintenanceManager(spec, app_paths=paths)


def test_apply_failure_preserves_completed_scope_results(
    tmp_path: Path,
) -> None:
    spec = _spec(paths=Paths(appdata=True, cache=True))
    paths = _paths(tmp_path)
    appdata_root = ensure_owned_path(spec, paths, "appdata")
    ensure_owned_path(spec, paths, "cache")
    payload = appdata_root / "saved.db"
    payload.write_text("data", encoding="utf-8")
    success = RemovalResult((payload,))

    def plan_appdata(root: Path) -> RemovalPlan:
        return RemovalPlan("appdata", root, (payload,), "appdata-revision")

    def apply_appdata(plan: RemovalPlan) -> RemovalResult:
        payload.unlink()
        return success

    def plan_cache(root: Path) -> RemovalPlan:
        return RemovalPlan("cache", root, (), "cache-revision")

    def fail_cache(plan: RemovalPlan) -> RemovalResult:
        raise RuntimeError("cache provider failed")

    handlers = MaintenanceHandlers(
        appdata=AppDataOperations(
            purge=RemovalOperation(plan_appdata, apply_appdata)
        ),
        cache=CacheOperations(purge=RemovalOperation(plan_cache, fail_cache)),
    )
    manager = MaintenanceManager(spec, app_paths=paths, handlers=handlers)
    plans = manager.plan_purge(("appdata", "cache"))
    with pytest.raises(_MaintenanceApplyError) as caught:
        manager.apply_purge(plans)
    error = caught.value
    assert error.results == (success,)
    assert error.failed_plan.category == "cache"
    assert error.failure_result.removed == ()
    assert error.failure_result.skipped == ()
    assert error.failure_result.warnings
    assert isinstance(error.__cause__, RuntimeError)
    assert not payload.exists()


def test_config_purge_removes_only_complete_planned_inventory(
    tmp_path: Path,
) -> None:
    from apprc.user_files.env_files.secrets import secret_companion_path

    spec = _spec(paths=Paths(config=True))
    paths = _paths(tmp_path)
    root = ensure_owned_path(spec, paths, "config")
    managed = tuple(
        path
        for name in (spec.user_dotenv_filename, spec.apprc_toml_filename)
        for path in (root / name, secret_companion_path(root / name))
    )
    for path in managed:
        path.write_text("VALUE=remove\n", encoding="utf-8")
    manager = MaintenanceManager(spec, app_paths=paths)
    (plan,) = manager.plan_purge(("config",))
    assert plan.targets == (*managed, root / ".apprc-owner.json", root)
    (result,) = manager.apply_purge((plan,))
    assert result.removed == plan.targets
    assert result.skipped == ()
    assert result.warnings == ()
    assert not root.exists()
    assert managed_lock_path(root).is_file()


@pytest.mark.parametrize("native_base_changed", [False, True])
def test_pending_operation_context_initializes_captured_maintenance_paths(
    tmp_path: Path,
    native_base_changed: bool,
) -> None:
    from uuid import uuid4

    from apprc import AppRC
    from apprc.definition.installation import (
        InstallationError,
        InstallationIdentity,
        InstallationPlacement,
        InstallationSource,
        OperationContext,
        UvToolTarget,
    )
    from apprc.user_files.installation.operations import (
        begin_operation,
        plan_install,
    )

    environment = {
        "HOME": str(tmp_path),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    app = AppRC(app_id="maintenance-context", paths=Paths(cache=True))
    installation = app.installation(environment=environment)
    placement = InstallationPlacement(
        Layout.single_root(tmp_path / "application"),
        cache_dir=tmp_path / "application" / "cache",
        capabilities=frozenset({"cache"}),
    )
    identity = InstallationIdentity(
        "maintenance-context",
        "example-package",
        "example_package",
        None,
        ("example-command",),
    )
    source = InstallationSource("editable", str(tmp_path / "project"))
    backend = UvToolTarget(
        tmp_path / "uv", tmp_path / "tools", tmp_path / "tool-bin"
    )
    plan = plan_install(
        identity, source, placement, backend, inspection=installation.inspect()
    )
    begin_operation(plan)
    context = OperationContext(
        installation.directory, plan.operation_id, plan.generation_id, placement
    )
    provider_environment = dict(environment)
    if native_base_changed:
        provider_environment.update(
            {
                "HOME": str(tmp_path / "new-home"),
                "USERPROFILE": str(tmp_path / "new-home"),
                "LOCALAPPDATA": str(tmp_path / "new-local"),
                "XDG_DATA_HOME": str(tmp_path / "new-data"),
            }
        )

    manager = app.maintain(environment=provider_environment, context=context)
    assert placement.cache_dir is not None
    assert manager.app_paths.cache_dir == placement.cache_dir
    assert manager.app_paths.installation.directory == installation.directory
    assert manager.ensure_path("cache") == placement.cache_dir
    assert (
        inspect_ownership(placement.cache_dir, identity.app_id, "cache")
        == "owned"
    )
    if native_base_changed:
        new_discovery = app.installation(
            environment=provider_environment
        ).directory
        assert new_discovery != installation.directory
        assert not new_discovery.exists()

    stale = OperationContext(
        installation.directory, uuid4(), plan.generation_id, placement
    )
    with pytest.raises(
        InstallationError, match="Pending operation authorization is stale"
    ):
        app.maintain(environment=provider_environment, context=stale)
