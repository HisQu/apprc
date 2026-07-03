"""Public root facade tests."""

import apprc as rc


def test_root_exports_clean_public_api() -> None:
    """Root exports only the clean public facade and namespaces."""
    assert rc.__all__ == [
        "AppRC",
        "Config",
        "ConfigBase",
        "field",
        "cli",
        "files",
        "provenance",
        "storage",
    ]
    assert hasattr(rc, "AppRC")
    assert hasattr(rc, "Config")
    assert hasattr(rc, "ConfigBase")
    assert hasattr(rc, "field")
    assert hasattr(rc, "cli")
    assert hasattr(rc, "storage")
    assert hasattr(rc, "provenance")
    assert hasattr(rc, "files")


def test_root_does_not_export_legacy_symbols() -> None:
    """The breaking root API removes old declaration helpers."""
    assert not hasattr(rc, "secret")
    assert not hasattr(rc, "EnvConfig")
    assert not hasattr(rc, "env_field")
    assert not hasattr(rc, "env_owner")
    assert not hasattr(rc, "AppConfigKit")
    assert not hasattr(rc, "mount_config_cli")
