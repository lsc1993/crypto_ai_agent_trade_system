import logging

import structlog


def configure_logging(log_level: str) -> None:
    normalized_level = log_level.upper()
    numeric_level = logging.getLevelNamesMapping().get(normalized_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
