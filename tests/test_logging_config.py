import io
import json
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from apprc.logging import (
    AppLogger,
    clear_cid,
    get_logger,
    set_cid,
    setup_logging,
)
from apprc.logging.context import CID

ROOT = Path(__file__).resolve().parents[1]


def test_get_logger_returns_app_logger_for_new_names() -> None:
    log = get_logger("apprc.tests.normal_contract")

    assert isinstance(log, AppLogger)


def test_get_logger_rejects_precreated_plain_logger() -> None:
    script = textwrap.dedent(
        """
        import logging

        plain_logger = logging.getLogger("apprc.tests.precreated_plain")
        assert type(plain_logger) is logging.Logger

        from apprc.logging import get_logger

        try:
            get_logger("apprc.tests.precreated_plain")
        except RuntimeError as exc:
            assert "install_app_logger_class()" in str(exc)
            assert "get_logger()" in str(exc)
        else:
            raise AssertionError("pre-created plain logger was accepted")
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "src"), os.environ.get("PYTHONPATH", ""))
        ),
    }
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_setup_logging_can_configure_named_logger_without_replacing_root() -> (
    None
):
    root = logging.getLogger()
    sentinel = logging.NullHandler()
    target = logging.getLogger("apprc.tests.named_logger")
    root.addHandler(sentinel)
    try:
        setup_logging(
            level="DEBUG",
            colorize=False,
            force=True,
            logger="apprc.tests.named_logger",
        )

        assert sentinel in root.handlers
        assert target.handlers
        assert target.level == logging.DEBUG
        assert target.propagate is False
    finally:
        target.handlers.clear()
        target.propagate = True
        root.removeHandler(sentinel)


def test_semantic_logger_preserves_structured_fields_and_validation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = get_logger("apprc.tests.semantic")

    with caplog.at_level(logging.INFO, logger="apprc.tests.semantic"):
        log.success("done", extra_struct={"rows": 2})

    record = caplog.records[-1]
    assert record.getMessage() == "done"
    assert getattr(record, "event_type") == "SUCCESS"
    assert getattr(record, "rows") == 2

    with caplog.at_level(logging.INFO, logger="apprc.tests.semantic"):
        with pytest.raises(TypeError, match="extra_struct"):
            log.info("bad", rows=1)
        with pytest.raises(
            KeyError,
            match="Duplicate logging structured field",
        ):
            log.info("bad", extra={"rows": 1}, extra_struct={"rows": 2})


def test_clear_cid_is_public_and_unbinds_contexts() -> None:
    import structlog.contextvars

    structlog.contextvars.clear_contextvars()
    clear_cid()

    assert CID.get() is None
    assert "cid" not in structlog.contextvars.get_contextvars()

    assert set_cid("cid-public") == "cid-public"
    assert CID.get() == "cid-public"
    assert structlog.contextvars.get_contextvars()["cid"] == "cid-public"

    clear_cid()

    assert CID.get() is None
    assert "cid" not in structlog.contextvars.get_contextvars()


def test_json_renderer_uses_lazy_exception_renderer_and_redacts_fields() -> (
    None
):
    stream = io.StringIO()
    target = logging.getLogger("apprc.tests.json_renderer")
    try:
        setup_logging(
            renderer="json",
            colorize=False,
            force=True,
            logger=target,
        )
        handler = target.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.stream = stream
        log = get_logger("apprc.tests.json_renderer.child")
        log.setLevel(logging.INFO)

        try:
            raise RuntimeError("sensitive failure")
        except RuntimeError as exc:
            log.traceback(
                "rendered failure",
                exc=exc,
                extra_struct={"DATABASE_URL": "postgres://secret"},
            )

        payload = json.loads(stream.getvalue())
        assert payload["DATABASE_URL"] == "[redacted]"
        assert payload["message"] == "rendered failure:"
        assert payload["exception"][0]["exc_type"] == "RuntimeError"
    finally:
        target.handlers.clear()
        target.propagate = True


def test_base_logging_api_imports_without_structlog() -> None:
    script = textwrap.dedent(
        """
        import importlib.abc
        import logging
        import sys


        class BlockStructlog(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "structlog" or fullname.startswith("structlog."):
                    raise ModuleNotFoundError(
                        "No module named 'structlog'",
                        name=fullname,
                    )
                return None


        sys.meta_path.insert(0, BlockStructlog())
        sys.modules.pop("structlog", None)

        import apprc
        from apprc.logging import clear_cid, get_logger, set_cid, setup_logging
        from apprc.logging.context import CID

        assert apprc.get_logger is get_logger
        assert set_cid("cid-1") == "cid-1"
        clear_cid()
        assert CID.get() is None

        log = get_logger("apprc.tests.no_structlog")
        log.setLevel(logging.INFO)
        log.success("works", extra_struct={"rows": 1})

        try:
            setup_logging()
        except ImportError as exc:
            assert 'python -m pip install "apprc[logging]"' in str(exc)
        else:
            raise AssertionError("setup_logging did not require apprc[logging]")
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "src"), os.environ.get("PYTHONPATH", ""))
        ),
    }
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_incompatible_structlog_reports_import_guidance() -> None:
    script = textwrap.dedent(
        """
        import types
        import sys

        for name in list(sys.modules):
            if name == "structlog" or name.startswith("structlog."):
                del sys.modules[name]

        structlog = types.ModuleType("structlog")
        structlog.__path__ = []
        sys.modules["structlog"] = structlog

        from apprc.logging import set_cid, setup_logging

        for action in (lambda: set_cid("cid-1"), setup_logging):
            try:
                action()
            except ImportError as exc:
                assert "structlog>=25.5" in str(exc)
            else:
                raise AssertionError("incompatible structlog was accepted")
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "src"), os.environ.get("PYTHONPATH", ""))
        ),
    }
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
