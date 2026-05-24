import logging
import sys

from .config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level_name = getattr(settings, "LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        root_logger.addHandler(handler)
    root_logger.setLevel(level)

    sqlalchemy_level = logging.INFO if settings.SQL_ECHO else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def get_logger(name: str = "serana") -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


logger = get_logger()
