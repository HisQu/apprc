"""Native process waiters retain OS-bound identity without Python wrappers."""

from __future__ import annotations

import ctypes
import os
import select
import sys
from ctypes import wintypes

import pytest

from tests.support_installation import owned_child_process

from apprc.distribution.runtime import (
    _handoff,
    uninstall_handoff,
    _process_waiter,
)


def _without_python_pidfd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "pidfd_open", raising=False)


def _assert_closed(fd: int) -> None:
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pidfd process waiters"
)
def test_libc_pidfd_waits_for_owned_child_without_python_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    with owned_child_process() as process:
        expected = _handoff.process_start_token(process.pid)
        waiter = uninstall_handoff._open_process_waiter(process.pid, expected)
        assert waiter[0] == "pidfd"
        fd = waiter[1]
        assert isinstance(fd, int)
        try:
            assert select.select([fd], [], [], 0)[0] == []

            assert process.stdin is not None
            process.stdin.write("exit\n")
            process.stdin.flush()
            uninstall_handoff._wait_open_process(waiter)
            _assert_closed(fd)
            assert process.wait(timeout=5) == 0
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pidfd process waiters"
)
def test_pidfd_closes_when_process_start_identity_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    opened: list[int] = []
    open_pidfd = _process_waiter._linux_pidfd_open

    def track_pidfd(pid: int) -> int:
        fd = open_pidfd(pid)
        opened.append(fd)
        return fd

    monkeypatch.setattr(_process_waiter, "_linux_pidfd_open", track_pidfd)
    try:
        with owned_child_process() as process:
            waiter = uninstall_handoff._open_process_waiter(
                process.pid, "linux:wrong:identity"
            )
            assert waiter == ("already-exited", None)
            assert len(opened) == 1
            _assert_closed(opened[0])
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pidfd process waiters"
)
def test_pidfd_closes_when_process_exits_during_identity_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    opened: list[int] = []
    open_pidfd = _process_waiter._linux_pidfd_open

    def track_pidfd(pid: int) -> int:
        fd = open_pidfd(pid)
        opened.append(fd)
        return fd

    monkeypatch.setattr(_process_waiter, "_linux_pidfd_open", track_pidfd)
    try:
        with owned_child_process() as process:
            original_token = _process_waiter._linux_process_token
            observed: list[int] = []

            def exit_before_token_read(pid: int) -> str:
                if pid == process.pid:
                    observed.append(pid)
                    assert process.stdin is not None
                    process.stdin.write("exit\n")
                    process.stdin.flush()
                    assert process.wait(timeout=5) == 0
                return original_token(pid)

            monkeypatch.setattr(
                _process_waiter, "_linux_process_token", exit_before_token_read
            )
            waiter = uninstall_handoff._open_process_waiter(
                process.pid, "unused"
            )
            assert observed == [process.pid]
            assert waiter == ("already-exited", None)
            assert len(opened) == 1
            _assert_closed(opened[0])
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.skipif(os.name != "nt", reason="Windows process handle waiters")
def test_windows_waiter_waits_for_exit_and_closes_handle() -> None:
    kernel32, _ = _process_waiter._windows_api()
    kernel32.GetHandleInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetHandleInformation.restype = wintypes.BOOL
    with owned_child_process() as process:
        expected = _handoff.process_start_token(process.pid)
        waiter = uninstall_handoff._open_process_waiter(process.pid, expected)
        assert waiter[0] == "windows"
        handle = waiter[1]
        flags = wintypes.DWORD()
        try:
            assert kernel32.GetHandleInformation(handle, ctypes.byref(flags))
            assert process.poll() is None
            assert process.stdin is not None
            process.stdin.write("exit\n")
            process.stdin.flush()
            uninstall_handoff._wait_open_process(waiter)
            ctypes.set_last_error(0)
            assert not kernel32.GetHandleInformation(
                handle, ctypes.byref(flags)
            )
            assert ctypes.get_last_error() == 6
            assert process.wait(timeout=5) == 0
        finally:
            if kernel32.GetHandleInformation(handle, ctypes.byref(flags)):
                kernel32.CloseHandle(handle)
