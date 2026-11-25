"""
Structured logging for VibeFinder, using only the standard library.

Log lines go to stderr so they never mix with the recommendations printed on
stdout. Each message is a set of key=value pairs, for example:

    2026-11-25 15:02:11 INFO vibefinder event=dataset_loaded path=data/songs.csv songs=20
"""

import logging
import sys
from typing import Any

LOGGER_NAME = "vibefinder"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _CurrentStderrHandler(logging.StreamHandler):
    """Write to whatever sys.stderr is at emit time (keeps pytest capture working)."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value):
        pass


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Send vibefinder logs to stderr at the given level. Safe to call repeatedly."""
    logger = get_logger()
    for handler in list(logger.handlers):
        if isinstance(handler, _CurrentStderrHandler):
            logger.removeHandler(handler)
    handler = _CurrentStderrHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    return logger


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    text = str(value)
    return f'"{text}"' if (" " in text or not text) else text


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Log one event as `event=<name> key=value ...`."""
    parts = [f"event={event}"] + [f"{key}={_format_value(value)}" for key, value in fields.items()]
    logger.log(level, " ".join(parts))
