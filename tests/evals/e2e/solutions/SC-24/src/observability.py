"""Health, structured logging and the stated SLO for the calculation service."""

import json
import logging

# Availability SLO: 99.9% of health probes succeed over a rolling 30 days.
SLO_AVAILABILITY = 0.999


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


def get_logger(name: str = "calc") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def health() -> dict:
    """Liveness/readiness probe served at /health."""
    return {"status": "ok", "slo_availability": SLO_AVAILABILITY}
