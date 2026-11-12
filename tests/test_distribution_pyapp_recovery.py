"""Opt-in Linux proof of recovery after interrupted PyApp wheel installation."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import unquote, urlsplit

import pytest

from apprc.distribution.standalone import MANAGEMENT_REQUIREMENTS
from tests.support_pyapp import (
    UV_VERSION,
    isolated_environment,
    native_builder,
    pinned_uv,
    require_opt_in,
    run,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("APPRC_TEST_PYAPP") != "1",
        reason="Set APPRC_TEST_PYAPP=1 to enable native feasibility builds.",
    ),
    pytest.mark.skipif(
        sys.platform != "linux",
        reason="Bootstrap recovery executes only the Linux native artifact.",
    ),
]


def test_native_bootstrap_restore_after_wheel_transport_failure(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Restore a genuinely incomplete bootstrap without executing its entry."""
    require_opt_in()
    if hasattr(request.config, "workerinput"):
        pytest.fail("Run PyApp feasibility serially with pytest -n 0.")

    fixture_uv = pinned_uv(tmp_path / "fixture-uv")
    fixture_python = fixture_uv.parent / "python"
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n".join((*MANAGEMENT_REQUIREMENTS, f"uv=={UV_VERSION}")) + "\n",
        encoding="utf-8",
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    run(
        [
            str(fixture_python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--dest",
            str(wheelhouse),
            "--requirement",
            str(requirements),
        ]
    )
    wheel_names = {path.name for path in wheelhouse.glob("*.whl")}

    environment = isolated_environment(tmp_path / "runtime")
    bootstrap = Path(
        environment["PYAPP_INSTALL_DIR_APPRC-PYAPP-FIXTURE-BOOTSTRAP"]
    )
    entry_marker = tmp_path / "dispatcher-entered.json"
    environment["APPRC_FIXTURE_RECOVERY_ENTRY"] = str(entry_marker)
    dispatcher = tmp_path / "recovery_dispatcher.py"
    dispatcher.write_text(
        "import uv\n"
        "import json, os, sys\n"
        "from importlib.metadata import version\n"
        "from pathlib import Path\n"
        "identity = {'python': sys.executable, 'prefix': sys.prefix, "
        "'uv': uv.find_uv_bin(), 'uv_version': version('uv')}\n"
        "Path(os.environ['APPRC_FIXTURE_RECOVERY_ENTRY']).write_text("
        "json.dumps(identity), encoding='utf-8')\n"
        "print(json.dumps(identity))\n",
        encoding="utf-8",
    )
    healthy = Event()
    download_started = Event()
    request_finished = Event()
    traffic: list[tuple[str, int]] = []
    traffic_lock = Lock()

    class WheelHandler(SimpleHTTPRequestHandler):
        """Reject wheel bodies until the test enables the unchanged wheelhouse."""

        timeout = 10

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(wheelhouse), **kwargs)

        def do_GET(self) -> None:
            if (
                urlsplit(self.path).path.endswith(".whl")
                and not healthy.is_set()
            ):
                download_started.set()
                healthy.wait(timeout=180)
                try:
                    self.send_error(503, "Interrupted bootstrap wheel transfer")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    request_finished.set()
                return
            super().do_GET()

        def log_request(
            self, code: int | str = "-", size: int | str = "-"
        ) -> None:
            if isinstance(code, int):
                with traffic_lock:
                    traffic.append((unquote(urlsplit(self.path).path), code))

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), WheelHandler) as server:
        port = server.server_port
        builder = native_builder(
            tmp_path / "compiler",
            pip_extra_args=(
                f"--no-index --find-links http://127.0.0.1:{port}/ --retries 0"
            ),
        )
        binary = builder.build(
            dispatcher,
            target="x86_64-unknown-linux-gnu",
            destination=tmp_path / "recovery-linux",
        ).path
        worker = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}
        )
        worker.start()
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [str(binary)],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            received_wheel = download_started.wait(timeout=180)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            failed_stdout, failed_stderr = process.communicate(timeout=30)
            assert received_wheel, failed_stdout + failed_stderr
            assert process.returncode == -signal.SIGKILL
            assert not entry_marker.exists()
            assert bootstrap.is_dir()
            assert (bootstrap / "pyvenv.cfg").is_file()
            healthy.set()
            assert request_finished.wait(timeout=15)
            with traffic_lock:
                initial_traffic = tuple(traffic)
            assert any(
                path.endswith(".whl") and status == 503
                for path, status in initial_traffic
            )
            partial = run(
                [
                    str(bootstrap / "bin" / "python"),
                    "-I",
                    "-c",
                    "import importlib.util, json, sys; "
                    "print(json.dumps({'prefix': sys.prefix, "
                    "'uv_missing': importlib.util.find_spec('uv') is None}))",
                ],
                environment=environment,
            )
            partial_identity = json.loads(partial.stdout)
            assert (
                Path(partial_identity["prefix"]).resolve()
                == bootstrap.resolve()
            )
            assert partial_identity["uv_missing"] is True

            # > PyApp v0.31.0 checks directory existence, not install completion.
            healthy.set()
            retry = run([str(binary)], environment=environment, check=False)
            assert retry.returncode != 0, retry.stdout + retry.stderr
            assert "ModuleNotFoundError: No module named 'uv'" in retry.stderr
            assert not entry_marker.exists()
            with traffic_lock:
                assert tuple(traffic) == initial_traffic

            restored = run(
                [str(binary), "bootstrap", "restore"],
                environment=environment,
                check=False,
            )
            assert restored.returncode == 0, restored.stdout + restored.stderr
            assert not entry_marker.exists(), (
                "Restore must not execute the entry."
            )
            with traffic_lock:
                restored_traffic = tuple(traffic)
            served_wheels = {
                Path(path).name
                for path, status in restored_traffic[len(initial_traffic) :]
                if path.endswith(".whl") and status == 200
            }
            assert served_wheels == wheel_names, (
                restored.stdout + restored.stderr
            )

            launched = run([str(binary)], environment=environment)
            assert entry_marker.is_file()
            identity = json.loads(launched.stdout)
            python = Path(identity["python"])
            uv_binary = Path(identity["uv"])
            assert identity["uv_version"] == UV_VERSION
            assert Path(identity["prefix"]).resolve() == bootstrap.resolve()
            assert python.is_absolute() and python.is_file()
            assert python.is_relative_to(bootstrap)
            assert uv_binary.is_absolute() and uv_binary.is_file()
            assert uv_binary.resolve().is_relative_to(bootstrap.resolve())
            uv_version = run(
                [str(uv_binary), "--version"], environment=environment
            )
            assert uv_version.stdout.split()[:2] == ["uv", UV_VERSION]
            with traffic_lock:
                assert tuple(traffic) == restored_traffic
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=30)
            healthy.set()
            server.shutdown()
            worker.join(timeout=15)
            assert not worker.is_alive(), "Wheel server thread did not stop."
