"""Safe application-owned resource inspection and maintenance operations."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.installation import (
    InstallationWriteAuthority,
    OperationContext,
)
from apprc.definition.maintenance import (
    AppDataOperations,
    CacheOperations,
    MaintenanceHandlers,
    RemovalOperation,
    RemovalPlan,
    RemovalResult,
    StateOperations,
)
from apprc.definition.paths import AppPaths, PathKind, ResourceKind
from apprc.definition.resolution import ResolveOptions
from apprc.user_files.app_home.layouts import resolve_app_paths
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import (
    ensure_owned_path,
    inspect_ownership,
    validate_category_root_boundaries,
)
from apprc.user_files.app_home.removal import (
    apply_removal,
    plan_removal,
    validate_removal_plan,
)
from apprc.user_files.app_home.writes import managed_write_lock
from apprc.user_files.purge import apply_config_purge, plan_config_purge


class _MaintenanceApplyError(Exception):
    """Retain completed maintenance results when a later apply step fails."""

    def __init__(
        self,
        results: tuple[RemovalResult, ...],
        failed_plan: RemovalPlan,
    ) -> None:
        """Capture factual successes and an indeterminate failed operation."""
        super().__init__(
            f"Applying maintenance failed for {failed_plan.category} at "
            f"{failed_plan.root}; the provider may have partially changed it."
        )
        self.results: tuple[RemovalResult, ...] = results
        self.failed_plan: RemovalPlan = failed_plan
        self.failure_result: RemovalResult = RemovalResult(
            removed=(),
            skipped=(),
            warnings=(
                "Apply failed; provider may have partially changed this root.",
            ),
        )


class MaintenanceManager:
    """Manage declared paths and explicitly supplied application operations.

    :param spec: Application's independent path declarations.
    :param options: Resolution options retained for callers.
    :param environment: Captured environment snapshot.
    :param handlers: Explicit category-specific application operations.
    :param app_paths: Previously resolved paths to preserve invocation identity.
    :param operation_context: Pending lifecycle permission for staged mutations.
    """

    def __init__(
        self,
        spec: AppConfigSpec,
        *,
        options: ResolveOptions | None = None,
        environment: Mapping[str, str] | None = None,
        handlers: MaintenanceHandlers = MaintenanceHandlers(),
        app_paths: AppPaths | None = None,
        operation_context: OperationContext | None = None,
    ) -> None:
        self.spec = spec
        self.options = options or ResolveOptions()
        self.handlers = handlers
        self.operation_context = operation_context
        self.environment = dict(
            os.environ if environment is None else environment
        )
        if operation_context is not None and app_paths is not None:
            raise ValueError(
                "Do not combine a pending operation context with pre-resolved paths."
            )
        self.app_paths = app_paths or resolve_app_paths(
            spec,
            self.options,
            self.environment,
            operation_context=operation_context,
        )
        validate_category_root_boundaries(spec, self.app_paths)
        declared = {
            "appdata": spec.paths.appdata,
            "cache": spec.paths.cache,
            "state": spec.paths.state,
        }
        providers = {
            "appdata": handlers.appdata,
            "cache": handlers.cache,
            "state": handlers.state,
        }
        for category, provider in providers.items():
            if provider is not None and not declared[category]:
                raise ValueError(
                    f"Maintenance provider requires enabled {category} path."
                )

    def info(self, kind: ResourceKind) -> Mapping[str, object]:
        """Describe declared roots and optional provider details.

        :param kind: Enabled resource category to inspect.
        :return: JSON-compatible roots, existence, ownership, and details.
        :raises ValueError: If the category is disabled or ownership is unsafe.
        """
        if not self._enabled(kind):
            raise ValueError(f"AppRC path component '{kind}' is not enabled.")
        values: list[dict[str, object]] = []
        handler = self._handler(kind)
        for root in self._roots(kind):
            exists = root.exists()
            ownership = inspect_ownership(root, self.spec.app_id, kind)
            entry: dict[str, object] = {
                "root": str(root),
                "exists": exists,
                "ownership": ownership,
            }
            if exists and handler is not None and handler.info is not None:
                entry["details"] = _json_value(handler.info(root))
            values.append(entry)
        return {"category": kind, "roots": values}

    def plan_purge(
        self, scopes: tuple[ResourceKind, ...]
    ) -> tuple[RemovalPlan, ...]:
        """Build exact purge plans after preflighting every selected category.

        :param scopes: Enabled resource categories to purge.
        :return: Revision-bound plans for each selected root.
        :raises ValueError: If a scope is disabled or any root is unsafe.
        """
        scopes = tuple(dict.fromkeys(scopes))
        for scope in scopes:
            if not self._enabled(scope):
                raise ValueError(
                    f"AppRC path component '{scope}' is not enabled."
                )
        plans: list[RemovalPlan] = []
        for scope in scopes:
            if scope == "config":
                plans.append(plan_config_purge(self.spec, self.app_paths))
                continue
            provider = self._handler(scope)
            operation = provider.purge if provider is not None else None
            category_plans: list[RemovalPlan] = []
            for root in self._roots(scope):
                self._validate_root(scope, root)
                plan = (
                    _provider_plan(operation, scope, root)
                    if operation
                    else plan_removal(scope, root, self.spec.app_id)
                )
                if (
                    plan.category != scope
                    or plan.root.expanduser().absolute() != root
                ):
                    raise ValueError(
                        f"Provider returned an invalid {scope} purge plan."
                    )
                self._validate_plan_boundary(scope, plan)
                category_plans.append(plan)
            plans.extend(category_plans)
        return tuple(plans)

    def apply_purge(
        self, plans: tuple[RemovalPlan, ...]
    ) -> tuple[RemovalResult, ...]:
        """Apply plans only after every scope and provider revision is fresh.

        :param plans: Exact plans previously returned by :meth:`plan_purge`.
        :return: Per-root removal results in plan order.
        :raises ValueError: If any plan is stale, unsafe, or outside its root.
        :raises _MaintenanceApplyError: If apply dispatch fails.
        """
        seen_roots: set[tuple[ResourceKind, Path]] = set()
        for plan in plans:
            key = (plan.category, plan.root.expanduser().absolute())
            if key in seen_roots:
                raise ValueError(f"Duplicate purge plan for {plan.root}")
            seen_roots.add(key)
            if not self._enabled(plan.category):
                raise ValueError(
                    f"AppRC path component '{plan.category}' is not enabled."
                )
            self._validate_plan_boundary(plan.category, plan)
            if plan.category == "config":
                if plan_config_purge(self.spec, self.app_paths) != plan:
                    raise ValueError(
                        f"Configuration purge plan is stale: {plan.root}"
                    )
            else:
                provider = self._handler(plan.category)
                operation = provider.purge if provider is not None else None
                if operation is None:
                    validate_removal_plan(plan, self.spec.app_id)
                elif (
                    _provider_plan(operation, plan.category, plan.root) != plan
                ):
                    raise ValueError(
                        f"Provider purge plan is stale: {plan.root}"
                    )
        results: list[RemovalResult] = []
        for plan in plans:
            try:
                provider = (
                    self._handler(plan.category)
                    if plan.category != "config"
                    else None
                )
                operation = provider.purge if provider is not None else None
                if (
                    not plan.root.exists()
                    and not plan.targets
                    and operation is None
                ):
                    results.append(
                        RemovalResult(removed=(), warnings=plan.warnings)
                    )
                    continue
                with managed_write_lock(
                    plan.root,
                    authority=InstallationWriteAuthority(
                        self.spec.app_id,
                        self.app_paths.installation,
                        self.operation_context,
                    ),
                ):
                    if plan.category == "config":
                        if not plan.root.exists() and not plan.targets:
                            result = RemovalResult(
                                removed=(), warnings=plan.warnings
                            )
                        else:
                            result = apply_config_purge(
                                plan, self.spec, self.app_paths
                            )
                    else:
                        provider = self._handler(plan.category)
                        operation = (
                            provider.purge if provider is not None else None
                        )
                        if operation is not None:
                            if operation.plan(plan.root) != plan:
                                raise ValueError(
                                    f"Provider purge plan is stale: {plan.root}"
                                )
                            result = operation.apply(plan)
                        elif not plan.root.exists() and not plan.targets:
                            result = RemovalResult(
                                removed=(), warnings=plan.warnings
                            )
                        else:
                            result = apply_removal(plan, self.spec.app_id)
            except Exception as exc:
                raise _MaintenanceApplyError(tuple(results), plan) from exc
            results.append(result)
        return tuple(results)

    def ensure_path(self, kind: PathKind, *, adopt: bool = False) -> Path:
        """Initialize one enabled captured path and write its ownership marker.

        :param kind: Component or subordinate logs location to initialize.
        :param adopt: Whether an existing nonempty unowned root may be adopted.
        :return: The initialized captured root.
        :raises ValueError: If disabled, overlapping, linked, or unsafe.
        """
        return ensure_owned_path(
            self.spec,
            self.app_paths,
            kind,
            adopt=adopt,
            context=self.operation_context,
        )

    def backup_appdata(self, destination: Path) -> Path:
        """Create a new application-owned backup outside the source root.

        :param destination: New absolute destination selected by the caller.
        :return: Path returned by the appdata backup provider.
        :raises ValueError: If the provider is absent or a boundary is unsafe.
        """
        root = self.app_paths.require("appdata")
        provider = self.handlers.appdata
        if provider is None or provider.backup is None:
            raise ValueError(
                "AppData backup is not supported by this application."
            )
        if inspect_ownership(root, self.spec.app_id, "appdata") != "owned":
            raise ValueError(
                f"AppData backup source is not an owned directory: {root}"
            )
        destination = destination.expanduser().absolute()
        assert_no_links(destination)
        if (
            destination.exists()
            or destination == root
            or root in destination.parents
        ):
            raise ValueError(
                "Backup destination must be new and outside AppData."
            )
        assert_no_links(root)
        with managed_write_lock(
            root,
            authority=InstallationWriteAuthority(
                self.spec.app_id,
                self.app_paths.installation,
                self.operation_context,
            ),
        ):
            return provider.backup(root, destination)

    def restore_appdata(self, source: Path) -> None:
        """Restore an existing backup only into an empty owned appdata root.

        The provider must check for existing payload under its own coordination
        lock before writing. Only it can distinguish retained lock metadata
        from application data; a pre-dispatch directory scan cannot do so.

        :param source: Existing application-format backup source.
        :return: None.
        :raises ValueError: If the provider is absent or the destination is unsafe.
        """
        root = self.app_paths.require("appdata")
        provider = self.handlers.appdata
        if provider is None or provider.restore is None:
            raise ValueError(
                "AppData restore is not supported by this application."
            )
        assert_no_links(source)
        if not source.exists():
            raise ValueError(f"AppData restore source is unavailable: {source}")
        assert_no_links(root)
        ownership = inspect_ownership(root, self.spec.app_id, "appdata")
        if ownership == "unowned":
            raise ValueError(
                f"Refusing to restore into unowned AppData: {root}"
            )
        ensure_owned_path(
            self.spec, self.app_paths, "appdata", context=self.operation_context
        )
        with managed_write_lock(
            root,
            authority=InstallationWriteAuthority(
                self.spec.app_id,
                self.app_paths.installation,
                self.operation_context,
            ),
        ):
            provider.restore(root, source)

    def plan_cache_prune(self) -> tuple[RemovalPlan, ...]:
        """Plan provider pruning for each captured cache root.

        :return: Provider plans bound to the current cache inventories.
        :raises ValueError: If pruning is unavailable or a root is unsafe.
        """
        provider = self.handlers.cache
        return self._plan_operation(
            "cache", provider.prune if provider else None
        )

    def apply_cache_prune(
        self, plans: tuple[RemovalPlan, ...]
    ) -> tuple[RemovalResult, ...]:
        """Apply fresh cache-prune plans under provider coordination.

        :param plans: Exact plans previously returned by :meth:`plan_cache_prune`.
        :return: Provider results in captured-root order.
        :raises ValueError: If a plan is stale, unsafe, or pruning is unavailable.
        :raises _MaintenanceApplyError: If provider apply fails.
        """
        provider = self.handlers.cache
        return self._apply_operation(
            "cache", provider.prune if provider else None, plans
        )

    def plan_cache_clear(self) -> tuple[RemovalPlan, ...]:
        """Plan clearing recognized cache data while retaining provider-owned files.

        :return: Provider plans bound to the current cache inventories.
        :raises ValueError: If cache clearing is unavailable or unsafe.
        """
        provider = self.handlers.cache
        return self._plan_operation(
            "cache", provider.clear if provider else None
        )

    def apply_cache_clear(
        self, plans: tuple[RemovalPlan, ...]
    ) -> tuple[RemovalResult, ...]:
        """Apply fresh cache-clear plans under provider coordination.

        :param plans: Exact plans previously returned by :meth:`plan_cache_clear`.
        :return: Provider results in captured-root order.
        :raises ValueError: If a plan is stale, unsafe, or clearing is unavailable.
        :raises _MaintenanceApplyError: If provider apply fails.
        """
        provider = self.handlers.cache
        return self._apply_operation(
            "cache", provider.clear if provider else None, plans
        )

    def plan_state_prune(self) -> tuple[RemovalPlan, ...]:
        """Plan state pruning separately for non-contained state and log roots.

        :return: Provider plans for each distinct captured state root.
        :raises ValueError: If pruning is unavailable or a root is unsafe.
        """
        provider = self.handlers.state
        return self._plan_operation(
            "state", provider.prune if provider else None
        )

    def apply_state_prune(
        self, plans: tuple[RemovalPlan, ...]
    ) -> tuple[RemovalResult, ...]:
        """Apply fresh state-prune plans under provider coordination.

        :param plans: Exact plans previously returned by :meth:`plan_state_prune`.
        :return: Provider results in captured-root order.
        :raises ValueError: If a plan is stale, unsafe, or pruning is unavailable.
        :raises _MaintenanceApplyError: If provider apply fails.
        """
        provider = self.handlers.state
        return self._apply_operation(
            "state", provider.prune if provider else None, plans
        )

    def plan_state_reset(self) -> tuple[RemovalPlan, ...]:
        """Plan resetting state separately for each distinct captured root.

        :return: Provider plans for state and any external logs root.
        :raises ValueError: If resetting is unavailable or a root is unsafe.
        """
        provider = self.handlers.state
        return self._plan_operation(
            "state", provider.reset if provider else None
        )

    def apply_state_reset(
        self, plans: tuple[RemovalPlan, ...]
    ) -> tuple[RemovalResult, ...]:
        """Apply fresh state-reset plans under provider coordination.

        :param plans: Exact plans previously returned by :meth:`plan_state_reset`.
        :return: Provider results in captured-root order.
        :raises ValueError: If a plan is stale, unsafe, or resetting is unavailable.
        :raises _MaintenanceApplyError: If provider apply fails.
        """
        provider = self.handlers.state
        return self._apply_operation(
            "state", provider.reset if provider else None, plans
        )

    def _plan_operation(
        self, kind: ResourceKind, operation: RemovalOperation | None
    ) -> tuple[RemovalPlan, ...]:
        if not self._enabled(kind):
            raise ValueError(f"AppRC path component '{kind}' is not enabled.")
        if operation is None:
            raise ValueError(f"{kind} maintenance operation is unavailable.")
        plans_list: list[RemovalPlan] = []
        for root in self._roots(kind):
            self._validate_root(kind, root)
            plans_list.append(_provider_plan(operation, kind, root))
        plans = tuple(plans_list)
        if tuple(
            plan.root.expanduser().absolute() for plan in plans
        ) != self._roots(kind):
            raise ValueError(
                f"Provider returned invalid {kind} maintenance roots."
            )
        for plan in plans:
            self._validate_plan_boundary(kind, plan)
        return plans

    def _apply_operation(
        self,
        kind: ResourceKind,
        operation: RemovalOperation | None,
        plans: tuple[RemovalPlan, ...],
    ) -> tuple[RemovalResult, ...]:
        if not self._enabled(kind):
            raise ValueError(f"AppRC path component '{kind}' is not enabled.")
        if operation is None:
            raise ValueError(f"{kind} maintenance operation is unavailable.")
        roots = self._roots(kind)
        if tuple(plan.root.expanduser().absolute() for plan in plans) != roots:
            raise ValueError(f"Invalid {kind} maintenance plan roots.")
        for plan in plans:
            self._validate_plan_boundary(kind, plan)
            if _provider_plan(operation, kind, plan.root) != plan:
                raise ValueError(
                    f"{kind} maintenance plan is stale: {plan.root}"
                )
        results: list[RemovalResult] = []
        for plan in plans:
            try:
                with managed_write_lock(
                    plan.root,
                    authority=InstallationWriteAuthority(
                        self.spec.app_id,
                        self.app_paths.installation,
                        self.operation_context,
                    ),
                ):
                    self._validate_plan_boundary(kind, plan)
                    if _provider_plan(operation, kind, plan.root) != plan:
                        raise ValueError(
                            f"{kind} maintenance plan is stale: {plan.root}"
                        )
                    results.append(operation.apply(plan))
            except Exception as exc:
                raise _MaintenanceApplyError(tuple(results), plan) from exc
        return tuple(results)

    def _roots(self, kind: ResourceKind) -> tuple[Path, ...]:
        if kind == "state":
            roots = (self.app_paths.state_dir, self.app_paths.logs_dir)
        else:
            roots = (
                {
                    "config": self.app_paths.config_dir,
                    "appdata": self.app_paths.appdata_dir,
                    "cache": self.app_paths.cache_dir,
                }[kind],
            )
        unique = tuple(
            dict.fromkeys(
                path.expanduser().absolute()
                for path in roots
                if path is not None
            )
        )
        return tuple(
            path
            for path in unique
            if not any(
                path != other and other in path.parents for other in unique
            )
        )

    def _enabled(self, kind: ResourceKind) -> bool:
        return {
            "config": self.spec.paths.config,
            "appdata": self.spec.paths.appdata,
            "cache": self.spec.paths.cache,
            "state": self.spec.paths.state,
        }[kind]

    def _handler(
        self, kind: ResourceKind
    ) -> AppDataOperations | CacheOperations | StateOperations | None:
        return {
            "appdata": self.handlers.appdata,
            "cache": self.handlers.cache,
            "state": self.handlers.state,
        }.get(kind)

    def _validate_root(self, kind: ResourceKind, root: Path) -> None:
        root = root.expanduser().absolute()
        if root not in self._roots(kind):
            raise ValueError(
                f"AppRC root is outside captured {kind} paths: {root}"
            )
        assert_no_links(root)
        if inspect_ownership(root, self.spec.app_id, kind) == "unowned" and any(
            root.iterdir()
        ):
            raise ValueError(
                f"Refusing operation on unowned {kind} root: {root}"
            )

    def _validate_plan_boundary(
        self, kind: ResourceKind, plan: RemovalPlan
    ) -> None:
        root = plan.root.expanduser().absolute()
        if root not in self._roots(kind) or plan.category != kind:
            raise ValueError(
                f"Removal plan is outside captured {kind} roots: {root}"
            )
        self._validate_root(kind, root)
        for target in plan.targets:
            absolute = target.expanduser().absolute()
            assert_no_links(absolute)
            if absolute == root:
                if not absolute.is_dir():
                    raise ValueError(
                        f"Removal root is not a directory: {target}"
                    )
            elif root not in absolute.parents:
                raise ValueError(
                    f"Removal target is outside captured root: {target}"
                )


def _provider_plan(
    operation: RemovalOperation,
    category: ResourceKind,
    root: Path,
) -> RemovalPlan:
    """Normalize provider planning failures before any apply dispatch begins."""
    try:
        return operation.plan(root)
    except Exception as exc:
        raise ValueError(
            f"Unable to preflight {category} maintenance for {root}."
        ) from exc


def _json_value(value: object) -> object:
    """Reject non-JSON provider details rather than stringifying their types."""
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("Maintenance info numbers must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Maintenance info mapping keys must be strings.")
        return {key: _json_value(item) for key, item in value.items()}
    raise TypeError(
        f"Maintenance info is not JSON-compatible: {type(value).__name__}"
    )
