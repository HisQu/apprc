"""Linux process waiters retain OS-bound identity without Python wrappers."""

from __future__ import annotations

import os
import select
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from apprc.distribution.runtime import removal


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pidfd process waiters"
)


@contextmanager
def _owned_child() -> Generator[subprocess.Popen[str], None, None]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.readline()"],
        stdin=subprocess.PIPE,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        if process.stdin is not None:
            process.stdin.close()


def _without_python_pidfd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "pidfd_open", raising=False)


def _assert_closed(fd: int) -> None:
    with pytest.raises(OSError):
        os.fstat(fd)


def test_libc_pidfd_waits_for_owned_child_without_python_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    with _owned_child() as process:
        expected = removal.process_start_token(process.pid)
        waiter = removal._open_process_waiter(process.pid, expected)
        assert waiter[0] == "pidfd"
        fd = waiter[1]
        assert isinstance(fd, int)
        try:
            assert select.select([fd], [], [], 0)[0] == []

            assert process.stdin is not None
            process.stdin.write("exit\n")
            process.stdin.flush()
            removal._wait_open_process(waiter)
            _assert_closed(fd)
            assert process.wait(timeout=5) == 0
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def test_pidfd_closes_when_process_start_identity_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    opened: list[int] = []
    open_pidfd = removal._linux_pidfd_open

    def track_pidfd(pid: int) -> int:
        fd = open_pidfd(pid)
        opened.append(fd)
        return fd

    monkeypatch.setattr(removal, "_linux_pidfd_open", track_pidfd)
    try:
        with _owned_child() as process:
            waiter = removal._open_process_waiter(
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


def test_pidfd_closes_when_process_exits_during_identity_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_python_pidfd(monkeypatch)
    opened: list[int] = []
    open_pidfd = removal._linux_pidfd_open

    def track_pidfd(pid: int) -> int:
        fd = open_pidfd(pid)
        opened.append(fd)
        return fd

    monkeypatch.setattr(removal, "_linux_pidfd_open", track_pidfd)
    try:
        with _owned_child() as process:
            original_token = removal._linux_process_token
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
                removal, "_linux_process_token", exit_before_token_read
            )
            waiter = removal._open_process_waiter(process.pid, "unused")
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
