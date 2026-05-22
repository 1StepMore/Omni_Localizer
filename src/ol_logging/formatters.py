"""Log formatters for structured output."""

import logging

FORMATTER = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def get_formatter() -> logging.Formatter:
    """Return configured formatter instance."""
    return logging.Formatter(FORMATTER, datefmt=DATE_FORMAT)
