import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from apprc.logging import get_logger, setup_logging

ROOT = Path(__file__).resolve().parents[1]


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
        from apprc.logging import get_logger, set_cid, setup_logging

        assert apprc.get_logger is get_logger
        assert set_cid("cid-1") == "cid-1"

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
