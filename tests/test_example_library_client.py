"""The importable example loads layers without caller setup."""

from pathlib import Path

import pytest

from library_client import LibraryClient
from library_client.config.app import MyRC
from library_client.config.sections.client import ClientSettings


def test_importable_client_reads_current_layers_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new client reads changed files; injected settings stay authoritative."""
    config_dir = tmp_path / "apprc"
    monkeypatch.setenv(MyRC.schema.apprc_dir_env_key, str(config_dir))
    monkeypatch.delenv("APPRC_EXAMPLE_LIBRARY_REQUEST_TIMEOUT", raising=False)

    first = LibraryClient()
    assert first.request_timeout == 20
    assert (
        first.settings.provenance_of("request_timeout").origin
        == "shell_dotenv_defaults"
    )
    assert not config_dir.exists()

    config_dir.mkdir()
    (config_dir / "apprc.user.env").write_text(
        "APPRC_EXAMPLE_LIBRARY_REQUEST_TIMEOUT=15\n", encoding="utf-8"
    )
    second = LibraryClient()
    assert first.request_timeout == 20
    assert second.request_timeout == 15
    assert (
        second.settings.provenance_of("request_timeout").origin
        == "shell_dotenv_user"
    )

    monkeypatch.setenv("APPRC_EXAMPLE_LIBRARY_REQUEST_TIMEOUT", "10")
    assert LibraryClient().request_timeout == 10

    injected = ClientSettings(request_timeout=7)
    assert LibraryClient(settings=injected).settings is injected
    assert LibraryClient(settings=injected).request_timeout == 7
