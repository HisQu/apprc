"""Lazy imports keep Textual outside the core import path."""

from apprc._lazy import build_lazy_facade

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.tui",
    all_exports=["ConfigEditorApp", "ConfigSetupApp"],
    module_exports={},
    symbol_exports={
        "ConfigEditorApp": "apprc.interfaces.tui.editor.app",
        "ConfigSetupApp": "apprc.interfaces.tui.setup.app",
    },
)
