"""Storage-only AppRC example."""

from storage.cli import build_app
from storage.config.sections.app import AppSettings
from storage.config.app import MyRC
from storage.config.bundle import StorageExampleConfig

__all__ = ["AppSettings", "MyRC", "StorageExampleConfig", "build_app"]
