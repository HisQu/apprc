"""Uninstall terminal acknowledgement keeps unattended invocations bounded."""

import io
import os

import pytest
from types import SimpleNamespace

from apprc.distribution.runtime import _uninstall_terminal as terminal


@pytest.mark.parametrize(
    ("allocate", "visible", "already_focused", "allow_focus"),
    [
        pytest.param(False, True, False, True, id="visible"),
        pytest.param(True, True, False, False, id="new-console-denied"),
        pytest.param(False, True, True, False, id="already-focused"),
        pytest.param(False, False, False, False, id="hidden-console"),
    ],
)
def test_prepare_requests_focus_for_the_windows_confirmation_console(
    monkeypatch, allocate, visible, already_focused, allow_focus
):
    import ctypes
    from unittest.mock import Mock

    window = 10
    kernel = SimpleNamespace(
        GetConsoleWindow=Mock(
            side_effect=[None, window] if allocate else [window]
        ),
        AllocConsole=Mock(return_value=True),
    )
    user = SimpleNamespace(
        IsWindowVisible=Mock(return_value=visible),
        GetForegroundWindow=Mock(
            return_value=window if already_focused else 20
        ),
        SetForegroundWindow=Mock(return_value=allow_focus),
        FlashWindowEx=Mock(),
    )
    monkeypatch.setattr(terminal, "os", SimpleNamespace(name="nt"))
    tty = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(
        terminal, "sys", SimpleNamespace(stdin=tty, stdout=tty, stderr=tty)
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, **kwargs: {"kernel32": kernel, "user32": user}[name],
        raising=False,
    )

    terminal.prepare()

    assert kernel.AllocConsole.call_count == int(allocate)
    expect_focus_request = visible and not already_focused
    if expect_focus_request:
        user.SetForegroundWindow.assert_called_once_with(window)
    else:
        user.SetForegroundWindow.assert_not_called()

    if expect_focus_request and not allow_focus:
        user.FlashWindowEx.assert_called_once()
        (info_pointer,) = user.FlashWindowEx.call_args.args
        info = ctypes.cast(
            info_pointer, user.FlashWindowEx.argtypes[0]
        ).contents
        assert info.window == window
        assert info.flags == 0x00000002  # < FLASHW_TRAY
        assert info.count == 3
    else:
        user.FlashWindowEx.assert_not_called()


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


def test_result_window_preserves_readiness_and_exit_pipes(
    monkeypatch, tmp_path
):
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
    icons = []
    monkeypatch.setattr(terminal, "apply_result_icon", icons.append)
    icon = tmp_path / "uninstall.ico"
    terminal.prepare_result_window(icon)
    assert icons == [icon]
    assert terminal.sys.stdin is control_input
    assert terminal.sys.stdout is control_output
    assert terminal.sys.stderr is display
    assert control_input.tell() == 0
    terminal.sys.stderr.write("Uninstall completed.\n")
    assert "Uninstall completed" in display.getvalue()
    assert control_output.getvalue() == ""


@pytest.mark.parametrize("visible", [False, True])
def test_result_icon_targets_only_a_visible_window(
    monkeypatch, tmp_path, visible
):
    import ctypes
    from unittest.mock import Mock

    monkeypatch.setattr(
        terminal,
        "os",
        SimpleNamespace(
            name="nt", environ={"_APPRC_UNINSTALL_RESULT_WINDOW": "1"}
        ),
    )
    icon = tmp_path / "uninstall.ico"
    icon.write_bytes(b"artwork")
    kernel = SimpleNamespace(GetConsoleWindow=Mock(return_value=10))
    user = SimpleNamespace(
        IsWindowVisible=Mock(return_value=visible),
        LoadImageW=Mock(return_value=20),
        SendMessageTimeoutW=Mock(),
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, **kwargs: {"kernel32": kernel, "user32": user}[name],
        raising=False,
    )
    terminal.apply_result_icon(icon)
    assert [
        call.args[:4] for call in user.SendMessageTimeoutW.call_args_list
    ] == ([(10, 0x80, 0, 20), (10, 0x80, 1, 20)] if visible else [])
