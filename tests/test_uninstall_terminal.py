"""Uninstall terminal acknowledgement keeps unattended invocations bounded."""

import io
import os

import pytest
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


@pytest.mark.parametrize("no_color", ["", "1"])
def test_result_path_is_literal_and_no_color(
    monkeypatch, capsys, tmp_path, no_color
):
    from apprc.interfaces._terminal_console import color_environment

    for key, value in color_environment(os.environ, True).items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("NO_COLOR", no_color)
    path = tmp_path / "[red]settings"
    terminal.result_line("Retained configuration", path)
    result = capsys.readouterr().err
    assert str(path) in result
    assert "\x1b[" not in result


def test_result_window_preserves_readiness_and_exit_pipes(monkeypatch):
    control_input, control_output = io.StringIO("EXIT\n"), io.StringIO()
    display = io.StringIO()
    monkeypatch.setattr(
        terminal,
        "os",
        SimpleNamespace(
            name="nt", environ={"_APPRC_UNINSTALL_RESULT_WINDOW": "1"}
        ),
    )
    monkeypatch.setattr(terminal.sys, "stdin", control_input)
    monkeypatch.setattr(terminal.sys, "stdout", control_output)
    monkeypatch.setattr(
        "builtins.open",
        lambda path, *args, **kwargs: display if path == "CONOUT$" else None,
    )
    terminal.prepare_result_window()
    assert terminal.sys.stdin is control_input
    assert terminal.sys.stdout is control_output
    assert terminal.sys.stderr is display
    assert control_input.tell() == 0
    terminal.sys.stderr.write("Uninstall completed.\n")
    assert "Uninstall completed" in display.getvalue()
    assert control_output.getvalue() == ""
