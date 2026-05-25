import logging

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(log_level: str) -> None:
    """Configure root logging with a simple timestamped format.

    Idempotent enough for app startup; level is taken from settings.log_level.
    """
    logging.basicConfig(level=log_level.upper(), format=_LOG_FORMAT)
