"""Uninstall terminal acknowledgement keeps unattended invocations bounded."""

import io
from types import SimpleNamespace

from apprc.distribution.runtime import _uninstall_terminal as terminal


def test_acknowledgement_uses_interactive_input(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "os", SimpleNamespace(name="posix"))
    stream = io.StringIO("\n")
    monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr(terminal.sys, "stdin", stream)
    terminal.acknowledge()
    assert stream.tell() == 1
    assert "Press Enter" in capsys.readouterr().err


def test_acknowledgement_does_not_read_redirected_input(monkeypatch):
    monkeypatch.setattr(terminal, "os", SimpleNamespace(name="posix"))

    class Input:
        def isatty(self):
            return False

        def readline(self):
            raise AssertionError("noninteractive input must not block")

    monkeypatch.setattr(terminal.sys, "stdin", Input())
    terminal.acknowledge()


def test_result_path_is_literal_and_no_color(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NO_COLOR", "1")
    path = tmp_path / "[red]settings"
    terminal.result_line("Retained configuration", path)
    result = capsys.readouterr().err
    assert str(path) in result
    assert "\x1b[" not in result
