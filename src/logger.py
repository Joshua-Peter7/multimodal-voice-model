"""
logger.py — Structured JSON / text logger for the translation system.
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Generator

import structlog
from src.config_loader import cfg


def _configure_logging() -> None:
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
    ]

    if cfg.logging.format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


_configure_logging()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


@contextmanager
def log_latency(logger: structlog.stdlib.BoundLogger, stage: str) -> Generator[None, None, None]:
    """Context manager that logs elapsed time for a pipeline stage."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if cfg.logging.log_latency:
            logger.info("stage_latency", stage=stage, latency_ms=round(elapsed_ms, 2))
