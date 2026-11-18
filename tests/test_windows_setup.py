"""Windows setup behavior exercised with isolated console and registry inputs."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from apprc.distribution.runtime import _setup_terminal as terminal
from apprc.distribution.runtime import _windows_command_path as windows


@pytest.mark.parametrize(
    ("args", "processes", "dedicated"),
    [
        ([], {11, 12}, True),
        ([], {10, 11, 12}, False),
        (["--yes"], {11, 12}, False),
    ],
)
def test_setup_acknowledgement_and_early_diagnostic(
    tmp_path, monkeypatch, capsys, args, processes, dedicated
):
    stdin = io.StringIO("\n")
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    stderr = io.StringIO()
    monkeypatch.setattr(stderr, "isatty", lambda: True)
    monkeypatch.setattr(
        terminal,
        "sys",
        SimpleNamespace(stdin=stdin, stderr=stderr, argv=["loader.py", *args]),
    )
    import os

    monkeypatch.setattr(
        terminal,
        "os",
        SimpleNamespace(
            name="nt",
            getpid=lambda: 12,
            getppid=lambda: 11,
            environ=os.environ,
        ),
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("API_TOKEN", "my-private-value")
    monkeypatch.setattr(terminal, "_console_processes", lambda: processes)

    def fail():
        raise OSError("Cannot start my-private-value")

    with pytest.raises(SystemExit) as error:
        terminal.run_setup_loader(fail, {})
    assert error.value.code == 1
    assert ("Press Enter" in stderr.getvalue()) is dedicated
    assert stdin.tell() == int(dedicated)
    [log] = (tmp_path / "AppRC" / "setup-logs").glob("*.log")
    assert str(log) in stderr.getvalue()
    text = log.read_text(encoding="utf-8")
    assert "OSError" in text and "[redacted]" in text
    assert "my-private-value" not in text


def test_user_path_update_preserves_type_and_deduplicates(
    tmp_path, monkeypatch
):
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    key = Key()
    user = 101
    writes = []
    values = [("%PROFILE%\\tools;D:\\Keep", 2)]

    def open_key(root, key_name):
        if root != user:
            raise FileNotFoundError
        assert key_name == "Environment"
        return key

    def set_value(handle, name, reserved, kind, value):
        assert handle is key and name == "Path"
        writes.append(value)
        values[:] = [(value, kind)]

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=user,
        HKEY_LOCAL_MACHINE=102,
        REG_SZ=1,
        REG_EXPAND_SZ=2,
        KEY_SET_VALUE=4,
        OpenKey=open_key,
        QueryValueEx=lambda *args: values[0],
        ExpandEnvironmentStrings=lambda value: value.replace(
            "%PROFILE%", "C:\\Users\\Example"
        ),
        CreateKeyEx=lambda root, name, *args: open_key(root, name),
        SetValueEx=set_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    environment = {"LOCALAPPDATA": str(tmp_path)}
    assert not windows.ensure_user_path(
        Path("c:/users/example/Tools/"), environment
    )
    path = Path("C:/Users/Example/.local/bin")
    assert windows.ensure_user_path(path, environment)
    assert values == [("%PROFILE%\\tools;D:\\Keep;" + str(path), 2)]
    assert not windows.ensure_user_path(
        Path("c:/users/example/.LOCAL/Bin"), environment
    )
    assert len(writes) == 1


def test_bridge_failure_keeps_child_stderr_when_response_is_missing(capsys):
    import subprocess

    from apprc.definition.installation import InstallationError
    from apprc.distribution.runtime.probe import _bridge_response

    result = subprocess.CompletedProcess(
        ["python"], 7, "", "ModuleNotFoundError: candidate dependency\n"
    )
    with pytest.raises(
        InstallationError, match=r"invalid initialize JSON \(exit 7\)"
    ):
        _bridge_response(result, "initialize")
    assert capsys.readouterr().err == result.stderr


def test_bridge_stderr_is_visible_but_not_saved_as_setup_diagnostics(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    from apprc.definition.installation import InstallationError
    from apprc.distribution.runtime.probe import _bridge_response

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = subprocess.CompletedProcess(
        ["python"],
        7,
        '{"action":"initialize","result":{}}',
        "settings_password=unregistered-sensitive-value\n",
    )
    with pytest.raises(InstallationError, match="exit 7") as failure:
        _bridge_response(result, "initialize")
    assert capsys.readouterr().err == result.stderr
    log = terminal.setup_diagnostic("Initializing Resources", failure.value)
    assert log is not None
    content = log.read_text(encoding="utf-8")
    assert "Child diagnostics were written to stderr" in content
    assert "unregistered-sensitive-value" not in content


def test_setup_import_failure_is_logged_and_acknowledged(monkeypatch, capsys):
    import builtins
    from unittest.mock import Mock

    from apprc.distribution.runtime import _manager

    state = {"dispatched": True}
    monkeypatch.setattr(_manager, "_APPRC_SETUP_LAUNCH", state, raising=False)
    monkeypatch.setattr(terminal, "dedicated_setup_console", lambda: True)
    acknowledgements = []
    diagnostics = []
    monkeypatch.setattr(
        terminal, "_acknowledge_setup", lambda: acknowledgements.append(True)
    )
    monkeypatch.setattr(
        terminal,
        "setup_diagnostic",
        lambda stage, error: diagnostics.append(error),
    )
    original_import = builtins.__import__

    def broken_renderer(name, *args, **kwargs):
        if name == "apprc.distribution.runtime._install_progress":
            raise ImportError("Missing setup renderer")
        return original_import(name, *args, **kwargs)

    def load() -> None:
        _manager._install(Mock(), Mock(), Path("setup"), ())

    monkeypatch.setattr(builtins, "__import__", broken_renderer)
    with pytest.raises(SystemExit) as failure:
        terminal.run_setup_loader(load, state)
    assert failure.value.code == 1
    assert acknowledgements == [True]
    assert len(diagnostics) == 1 and isinstance(diagnostics[0], ImportError)
    assert "Missing setup renderer" in capsys.readouterr().err


@pytest.mark.parametrize("install", [False, True])
def test_only_a_dedicated_setup_lingers_after_success(monkeypatch, install):
    monkeypatch.setattr(terminal, "dedicated_setup_console", lambda: True)
    acknowledgements = []
    monkeypatch.setattr(
        terminal, "_acknowledge_setup", lambda: acknowledgements.append(True)
    )
    state = {}

    def finish():
        state["install"] = install
        raise SystemExit(0)

    with pytest.raises(SystemExit) as exit_request:
        terminal.run_setup_loader(finish, state)
    assert exit_request.value.code == 0
    assert acknowledgements == ([True] if install else [])
