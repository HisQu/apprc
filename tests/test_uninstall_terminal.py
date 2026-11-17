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
