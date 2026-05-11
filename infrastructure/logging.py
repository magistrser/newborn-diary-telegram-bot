import logging
from os import environ

_DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s [%(name)s] %(message)s'


def configure_logging() -> None:
    level_name = environ.get('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=_DEFAULT_LOG_FORMAT)
    logging.getLogger().setLevel(level)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
