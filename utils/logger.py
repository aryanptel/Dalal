import logging
import sys
import os
import traceback
from logging.handlers import RotatingFileHandler
from utils.paths import get_logs_dir

def setup_logger() -> logging.Logger:
    """Initialize a global rotating file logger in the user's Document directory."""
    logger = logging.getLogger("DalalAI")
    
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    log_file = os.path.join(get_logs_dir(), "app.log")
    
    # Create rotating file handler (5 MB max size, keep 3 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Create console handler for INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Format
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger()

def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_unhandled_exception
