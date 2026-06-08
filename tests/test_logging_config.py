import logging

from apprc.logging import setup_logging


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
