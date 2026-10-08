"""Structured logging setup.

Every module gets its logger through :func:`get_logger`, which returns a
structlog logger bound to that module's name. Key-value pairs beat formatted
strings: a log line carries ``job_id`` as a field, so a job's whole history can
be pulled up without parsing anything.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a module-scoped structured logger.

    Args:
        name: Usually ``__name__``.

    Returns:
        A logger that renders key-value pairs as JSON in production and as
        readable key-value text locally.
    """
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[return-value]


def configure_logging(*, json_output: bool | None = None) -> None:
    """Configure structlog and stdlib logging once per process.

    Idempotent, so importing this from a module and calling it from a worker
    bootstrap is safe.

    Args:
        json_output: Force JSON or human-readable rendering. Defaults to JSON
            when stdout is not a TTY.
    """
    global _configured
    if _configured:
        return

    use_json = json_output if json_output is not None else not sys.stdout.isatty()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
        force=True,
    )
    # Third-party libraries are chatty at INFO; keep the signal.
    for noisy in ("numba", "matplotlib", "soundfile", "botocore", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            (
                structlog.processors.JSONRenderer()
                if use_json
                else structlog.dev.ConsoleRenderer(colors=False)
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def bind_context(**values: Any) -> None:
    """Attach key-value pairs to every subsequent log line in this context.

    Call inside a job's task scope so every line carries the job id without
    each call site repeating it.
    """
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    """Drop everything :func:`bind_context` attached to this context."""
    structlog.contextvars.clear_contextvars()
