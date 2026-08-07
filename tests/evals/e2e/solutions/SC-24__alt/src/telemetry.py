"""Independent second reference for SC-24.

Where solution A exposes a `health()` function and a JSON logging formatter in
`observability.py`, this one names the module differently, routes the probe through a
`/health` path constant, and configures logging via dictConfig -- so a discriminator
pinned to solution A's module or function name fails here.
"""

import logging
import logging.config

HEALTH_PATH = "/health"

# Availability SLO: 99.9% of probes succeed over a rolling 30 days.
SLO = {"availability": 0.999, "window_days": 30}

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"structured": {"format": '{"level":"%(levelname)s","msg":"%(message)s"}'}},
        "handlers": {"default": {"class": "logging.StreamHandler", "formatter": "structured"}},
        "root": {"handlers": ["default"], "level": "INFO"},
    }
)

log = logging.getLogger("pyservice")


def probe() -> dict:
    """Readiness probe served at HEALTH_PATH."""
    log.info("health probe served")
    return {"status": "ok", "slo": SLO}
