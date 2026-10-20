import logging
import sys
from logging.config import dictConfig

from app.core.config import settings


def configure_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "std": {
                    "format": "%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
                    "datefmt": "%H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "std",
                    "stream": sys.stdout,
                }
            },
            "root": {"handlers": ["console"], "level": settings.log_level},
            "loggers": {"uvicorn.access": {"level": "WARNING"}},
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)