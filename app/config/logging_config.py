"""Logging configuration."""
import logging
import sys
from app.config.settings import get_settings


def configure_logging():
    """Configure structured logging for the application."""
    settings = get_settings()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    
    # Console handler with detailed formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(settings.log_level)
    
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    root_logger.addHandler(console_handler)
    
    return root_logger


# Initialize logger
logger = logging.getLogger(__name__)
