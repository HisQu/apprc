"""Lazy facade for process-time AppRC behavior."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_DIAGNOSTIC_EXPORTS = [
    "ConfigDoctorPayload",
    "ConfigDoctorStatus",
    "build_config_doctor_payload",
    "config_command_text",
    "config_setup_message",
]
_PROVENANCE_EXPORTS = [
    "ConfigOriginState",
    "ConfigProvenance",
    "ConfigProvenanceOrigin",
    "ConfigProvenanceSource",
    "EnvValueOrigin",
    "PythonProvenanceOrigin",
    "ShellProvenanceOrigin",
    "base_config_provenance_of",
    "constructor_field_origins",
    "env_value_origin",
    "provenance",
    "provenance_of",
    "provenance_origin_label",
    "public_config_fields",
    "register_env_value_origins",
    "set_field_origin",
    "shell_origin_for_env_value",
    "source_for_origin",
    "with_field_origin",
]
_RESULT_EXPORTS = [
    "BootstrapLogger",
    "EnvBootstrapResult",
]
_BOOTSTRAP_EXPORTS = [
    "bootstrap_env",
]

_SYMBOL_EXPORTS = {
    **{name: "apprc.runtime.diagnostics" for name in _DIAGNOSTIC_EXPORTS},
    **{name: "apprc.runtime.provenance" for name in _PROVENANCE_EXPORTS},
    **{name: "apprc.runtime.result" for name in _RESULT_EXPORTS},
    **{name: "apprc.runtime.bootstrap" for name in _BOOTSTRAP_EXPORTS},
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.runtime",
    all_exports=[
        *_BOOTSTRAP_EXPORTS,
        *_DIAGNOSTIC_EXPORTS,
        *_PROVENANCE_EXPORTS,
        *_RESULT_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
