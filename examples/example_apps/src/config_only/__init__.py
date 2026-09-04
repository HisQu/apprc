"""Config-only AppRC example application."""

from config_only.cli import build_app
from config_only.config import AppSettings, KIT

__all__ = ["AppSettings", "KIT", "build_app"]
