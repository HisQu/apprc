"""Probe the target's real package with no bundled AppRC ahead of its imports.


The metadata-only branch is stdlib-only, including when invoked by the bridge.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

import argparse
import contextlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys at the private JSON bridge boundary.

    :param pairs: Object members in their decoded input order.
    :return: A mapping containing each unique member.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate application bridge field: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    """Read bridge JSON with duplicate-member rejection.

    :param path: Private request file to decode.
    :return: Decoded JSON value.
    """
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
    )


def _loads_json(value: str) -> object:
    """Decode captured doctor output with duplicate-member rejection.

    :param value: Captured stdout from the primary application command.
    :return: Decoded JSON value.
    """
    return json.loads(value, object_pairs_hook=_strict_object)


def _distribution_observations(
    distribution: importlib.metadata.Distribution,
    commands: Sequence[str],
) -> dict[str, object]:
    """Capture installed distribution and console-script observations.

    :param distribution: Distribution loaded from the target interpreter.
    :param commands: Every declared application console command.
    :return: Runtime identity, interpreter, and entry-point observations.
    """
    entries: dict[str, str] = {}
    declared = set(commands)
    for entry in distribution.entry_points:
        if entry.group != "console_scripts" or entry.name not in declared:
            continue
        if (
            entry.name in entries
            or not isinstance(entry.value, str)
            or not entry.value
        ):
            raise ValueError(
                "Installed distribution has an invalid console entry point."
            )
        entries[entry.name] = entry.value
    if any(command not in entries for command in commands):
        raise ValueError(
            "Installed distribution does not own every declared command."
        )
    return {
        "distribution": distribution.metadata["Name"],
        "version": distribution.version,
        "prefix": sys.prefix,
        "interpreter": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "commands": {command: entries[command] for command in commands},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Serve one strict application bridge request.

    :param argv: Optional CLI tokens, without the executable name.
    :return: The request action's process status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    request = _read_json(args.request)
    if isinstance(request, dict) and request.get("action") == "probe":
        return _probe_request(request)
    return _serve_request(request)


def _probe_request(request: object) -> int:
    """Return metadata-only runtime observations without importing AppRC.

    :param request: Decoded bridge request object.
    :return: Probe action process status.
    """
    fields = {
        "action",
        "identity",
        "command_name",
        "directory",
        "expected_revision",
        "runtime_options",
        "operation_context",
        "categories",
        "forget_retained",
        "migration_plan",
        "hooks",
    }
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("Application bridge request fields are invalid.")
    identity = request["identity"]
    if not isinstance(identity, dict) or set(identity) != {
        "app_id",
        "distribution",
        "import_package",
        "apprc_reference",
        "commands",
    }:
        raise ValueError("Probe identity fields are invalid.")
    if (
        not isinstance(identity["app_id"], str)
        or not isinstance(identity["distribution"], str)
        or not isinstance(identity["import_package"], str)
        or (
            identity["apprc_reference"] is not None
            and not isinstance(identity["apprc_reference"], str)
        )
        or not isinstance(identity["commands"], list)
        or not all(isinstance(command, str) for command in identity["commands"])
        or not identity["commands"]
        or len(set(identity["commands"])) != len(identity["commands"])
    ):
        raise ValueError("Probe identity is invalid.")
    command_name = request["command_name"]
    if (
        not isinstance(command_name, str)
        or command_name not in identity["commands"]
    ):
        raise ValueError("Probe command differs from declared identity.")
    if (
        not isinstance(request["directory"], str)
        or not Path(request["directory"]).is_absolute()
        or (
            request["expected_revision"] is not None
            and not isinstance(request["expected_revision"], str)
        )
        or request["operation_context"] is not None
        or request["categories"] != []
        or request["forget_retained"] is not False
        or request["migration_plan"] is not None
        or not isinstance(request["runtime_options"], dict)
    ):
        raise ValueError("Probe request contains invalid unused fields.")
    hooks = request["hooks"]
    if (
        not isinstance(hooks, dict)
        or set(hooks)
        != {
            "initialize",
            "inventory",
            "cleanup",
            "migrate",
        }
        or any(
            value is not None and not isinstance(value, str)
            for value in hooks.values()
        )
    ):
        raise ValueError("Probe hook declaration is invalid.")

    distribution = importlib.metadata.distribution(identity["distribution"])
    result = _distribution_observations(distribution, identity["commands"])
    print(json.dumps({"action": "probe", "result": result}, sort_keys=True))
    return 0


def _serve_request(request: object) -> int:
    """Execute a provider request after validating installation authority.

    :param request: Decoded 11-field application bridge request.
    :return: The request action's process status.
    """
    with contextlib.redirect_stdout(sys.stderr):
        from apprc.definition.installation import (
            CleanupInventory,
            InstallationHooks,
            InstallationIdentity,
            InstallationInspection,
            MigrationPlan,
            OperationContext,
        )
        from apprc.definition.paths import ResourceKind
        from apprc.definition.resolution import _BridgeRuntimeOptions
        from apprc.user_files.installation import codec

        initialize_hook = Callable[[OperationContext], None]
        inventory_hook = Callable[
            [InstallationInspection, frozenset[ResourceKind], bool],
            CleanupInventory,
        ]
        migration_hook = Callable[[MigrationPlan, OperationContext], None]

        fields = {
            "action",
            "identity",
            "command_name",
            "directory",
            "expected_revision",
            "runtime_options",
            "operation_context",
            "categories",
            "forget_retained",
            "migration_plan",
            "hooks",
        }
        if not isinstance(request, dict) or set(request) != fields:
            raise ValueError("Application bridge request fields are invalid.")
        action = request["action"]
        if not isinstance(action, str) or action not in {
            "initialize",
            "doctor",
            "inventory",
            "cleanup",
            "migrate",
        }:
            raise ValueError("Application bridge action is invalid.")
        if (
            action not in {"initialize", "cleanup", "migrate"}
            and request["operation_context"] is not None
        ):
            raise ValueError("Unexpected operation context for bridge action.")
        if action != "migrate" and request["migration_plan"] is not None:
            raise ValueError("Unexpected migration plan for bridge action.")
        if action != "inventory" and (
            request["categories"] != []
            or request["forget_retained"] is not False
        ):
            raise ValueError("Unexpected cleanup options for bridge action.")
        if action == "inventory" and (
            type(request["forget_retained"]) is not bool
            or not isinstance(request["categories"], list)
            or not all(type(item) is str for item in request["categories"])
            or len(set(request["categories"])) != len(request["categories"])
        ):
            raise ValueError("Invalid cleanup options.")

        if not isinstance(request["runtime_options"], dict):
            raise ValueError("Bridge runtime options must be an object.")
        identity = codec._decode(
            request["identity"], InstallationIdentity, "identity"
        )
        hooks = codec._decode(request["hooks"], InstallationHooks, "hooks")
        command_name = request["command_name"]
        directory_value = request["directory"]
        expected_revision = request["expected_revision"]
        if (
            not isinstance(identity, InstallationIdentity)
            or not isinstance(hooks, InstallationHooks)
            or not isinstance(command_name, str)
            or command_name not in identity.commands
            or not isinstance(directory_value, str)
            or not Path(directory_value).is_absolute()
            or not isinstance(expected_revision, str)
        ):
            raise ValueError("Application bridge request is invalid.")
        directory = Path(directory_value)
        categories: frozenset[ResourceKind] = frozenset()
        if action == "inventory":
            accepted = {"config", "appdata", "cache", "state"}
            requested = request["categories"]
            if (
                not isinstance(requested, list)
                or not all(isinstance(item, str) for item in requested)
                or not set(requested) <= accepted
            ):
                raise ValueError("Unknown cleanup category.")
            categories = frozenset(
                cast(ResourceKind, item) for item in requested
            )

        reference = identity.apprc_reference
        if not reference or ":" not in reference:
            raise ValueError(
                "Application declaration reference is unavailable."
            )
        module_name, attribute = reference.split(":", 1)
        application = vars(importlib.import_module(module_name))[attribute]
        from apprc import AppRC
        from apprc.services.installation import InstallationManager

        if (
            not isinstance(application, AppRC)
            or application.schema.app_id != identity.app_id
        ):
            raise ValueError("Installed AppRC declaration identity mismatches.")
        manager = InstallationManager(
            application.schema,
            environment=dict(os.environ),
            directory=directory,
        )
        inspection = manager.inspect()
        if inspection.revision != expected_revision:
            raise ValueError("Application bridge authority revision changed.")
        record = inspection.record
        if (
            record is None
            or record.identity != identity
            or record.command_name != command_name
        ):
            raise ValueError(
                "Application bridge identity differs from authority."
            )
        if action in {"doctor", "inventory"}:
            inspection.require_usable()
        if action in {"doctor", "inventory", "cleanup", "migrate"}:
            if record.active_runtime is None:
                raise ValueError("Application runtime is unavailable.")
            if record.active_runtime.hooks != hooks:
                raise ValueError(
                    "Application hooks differ from runtime authority."
                )
        if action == "initialize":
            operation = record.operation
            intended = operation.intended if operation is not None else None
            if intended is None or intended.identity != identity:
                raise ValueError(
                    "Initialization does not address its pending identity."
                )
            if intended.runtime.hooks != hooks:
                raise ValueError(
                    "Initialization hooks differ from candidate authority."
                )

        context_value = request["operation_context"]
        context = (
            codec.decode_operation_context(json.dumps(context_value).encode())
            if context_value is not None
            else None
        )
        if action in {"initialize", "cleanup", "migrate"} and context is None:
            raise ValueError(f"{action} requires an operation context.")
        if context is not None:
            from apprc.user_files.installation.validation import (
                validate_snapshot,
            )

            validate_snapshot(
                inspection.snapshot,
                app_id=identity.app_id,
                context=context,
            )
            operation = record.operation
            if operation is None:
                raise ValueError("Provider operation is no longer pending.")
            if action == "initialize" and operation.kind not in {
                "install",
                "replace",
                "repair",
            }:
                raise ValueError(
                    "Initialization does not match pending operation."
                )
            expected_kind = {
                "cleanup": "uninstall",
                "migrate": "migrate",
            }.get(action)
            if expected_kind is not None and operation.kind != expected_kind:
                raise ValueError(
                    "Provider callback does not match pending operation."
                )
        exit_status = 0
        if action == "initialize":
            if context is None:
                raise ValueError(
                    "Initialization requires an operation context."
                )
            observations = _distribution_observations(
                importlib.metadata.distribution(identity.distribution),
                identity.commands,
            )
            paths = application.schema.paths
            capabilities = {
                "config": paths.config,
                "appdata": paths.appdata,
                "cache": paths.cache,
                "state": paths.state,
            }
            initialized = manager.initialize(context=context)
            if hooks.initialize:
                cast(initialize_hook, _hook(hooks.initialize))(context)
            result = {
                **observations,
                "capabilities": capabilities,
                "paths": [str(item) for item in initialized.paths],
            }
        elif action == "doctor":
            from apprc.interfaces.cli.context import cli_runtime_options_to_args

            options = codec._decode(
                request["runtime_options"],
                _BridgeRuntimeOptions,
                "runtime_options",
            )
            if not isinstance(options, _BridgeRuntimeOptions):
                raise ValueError("Bridge runtime options are invalid.")
            distribution = importlib.metadata.distribution(
                identity.distribution
            )
            entry_points = [
                entry
                for entry in distribution.entry_points
                if entry.group == "console_scripts"
                and entry.name == command_name
            ]
            if len(entry_points) != 1:
                raise ValueError(
                    "Primary application console entrypoint is ambiguous."
                )
            entry_point = entry_points[0]
            entrypoint = entry_point.load()
            old_argv = sys.argv
            captured = io.StringIO()
            try:
                sys.argv = [
                    entry_point.name,
                    *cli_runtime_options_to_args(options.runtime),
                    options.maintenance_group_name,
                    "doctor",
                    "--json",
                    "--verbose",
                ]
                from apprc.interfaces.cli.maintenance_command import (
                    application_diagnostics_scope,
                )

                with (
                    application_diagnostics_scope(),
                    contextlib.redirect_stdout(captured),
                ):
                    try:
                        entrypoint()
                    except SystemExit as error:
                        status = 0 if error.code is None else error.code
                    else:
                        status = 0
            finally:
                sys.argv = old_argv
            if type(status) is not int or status not in {0, 1}:
                raise ValueError(
                    "Application doctor returned an invalid status."
                )
            result = _loads_json(captured.getvalue())
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("status"), str)
                or result["status"]
                not in {
                    "ok",
                    "warning",
                    "error",
                    "invalid",
                    "provisional",
                    "incomplete",
                }
                or not isinstance(result.get("checks"), list)
                or not isinstance(result.get("details"), dict)
            ):
                raise ValueError(
                    "Application doctor returned an invalid result."
                )
            exit_status = status
        elif action == "inventory":
            if not hooks.inventory:
                raise ValueError(
                    "Application cleanup inventory hook is unavailable."
                )
            inventory = cast(inventory_hook, _hook(hooks.inventory))(
                inspection,
                categories,
                cast(bool, request["forget_retained"]),
            )
            result = json.loads(codec.encode_cleanup_inventory(inventory))
        elif action == "cleanup":
            if context is None:
                raise ValueError("Cleanup requires an operation context.")
            cast(initialize_hook, _hook(hooks.cleanup))(context)
            result = {"completed": True}
        else:
            if not hooks.migrate:
                raise ValueError("Application migration hook is unavailable.")
            if context is None:
                raise ValueError("Migration requires an operation context.")
            plan = codec._decode(
                request["migration_plan"], MigrationPlan, "migration_plan"
            )
            migration = record.migration
            if (
                migration is None
                or plan.directory != directory
                or plan.app_id != identity.app_id
                or plan.operation_id != context.operation_id
                or plan.generation_id != context.generation_id
                or plan.placement != context.placement
                or plan.identity != identity
                or plan.command_name != command_name
                or plan.inventory != migration.inventory
                or not plan.quiescent
            ):
                raise ValueError(
                    "Migration plan differs from pending authority."
                )
            cast(migration_hook, _hook(hooks.migrate))(plan, context)
            result = {"completed": True}
    print(json.dumps({"action": action, "result": result}, sort_keys=True))
    return exit_status


def _hook(reference: str) -> Callable[..., object]:
    """Load exactly one importable module:function reference.

    :param reference: Authored callback reference from installation authority.
    :return: The referenced callable.
    """
    module, separator, function = reference.partition(":")
    if (
        not separator
        or not all(part.isidentifier() for part in module.split("."))
        or not function.isidentifier()
    ):
        raise ValueError("Application hook must be module:function.")
    value = getattr(importlib.import_module(module), function)
    if not callable(value):
        raise ValueError("Application hook is not callable.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
