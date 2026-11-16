"""Lazy exports for the tui interface package."""

from apprc._lazy import build_lazy_facade

_SYMBOL_EXPORTS = {
    "ConfigEditorApp": "apprc.interfaces.tui.editor",
    "ConfigEditorWorkspaceWorkflows": "apprc.interfaces.tui.editor",
    "ConfigSetupApp": "apprc.interfaces.tui.setup",
    "ConfigEditorScreen": "apprc.interfaces.tui.editor.app",
    "LauncherAction": "apprc.interfaces.tui.launcher",
    "LauncherContext": "apprc.interfaces.tui.launcher",
    "LauncherSpec": "apprc.interfaces.tui.launcher",
    "run_launcher": "apprc.interfaces.tui.launcher",
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.interfaces.tui",
    all_exports=tuple(_SYMBOL_EXPORTS),
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
