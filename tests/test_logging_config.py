import logging

import pytest

from apprc.logging import get_logger, setup_logging


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
