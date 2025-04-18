# promptbuilder/services/logging.py
import sys
from loguru import logger
from pathlib import Path

from ..config.paths import get_user_log_dir, is_frozen

def setup_logging(level="INFO", verbose=False):
    """Configures logging using Loguru."""
    log_level = "DEBUG" if verbose else level
    log_dir = get_user_log_dir()
    log_file_path = log_dir / "promptbuilder_{time:YYYY-MM-DD}.log"
    # Fixes high-priority issue #6: Convert Path to str for logger.add
    log_file_str = str(log_file_path)

    # Remove default handler
    logger.remove()

    # Console handler (colored)
    # Use simplified format for console, full format for file
    fmt_console = "<level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>"
    # Only add console logger if not running frozen (e.g., in dev) or if explicitly enabled?
    # For now, always add it.
    logger.add(
        sys.stderr,
        level=log_level,
        format=fmt_console,
        colorize=True,
        enqueue=True # Make logging calls non-blocking
    )

    # File handler (JSON or plain text)
    fmt_file = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process} | {thread.name} | {name}:{function}:{line} - {message}"
    try:
        logger.add(
            log_file_str, # Use the string representation of the path
            level="DEBUG", # Log more details to file
            format=fmt_file,
            rotation="1 day", # Rotate logs daily
            retention="7 days", # Keep logs for 7 days
            compression="zip", # Compress rotated logs
            enqueue=True, # Async file writing
            # serialize=True # Uncomment for JSON logs
            encoding="utf-8" # Explicitly set encoding
        )
        logger.info(f"Logging initialized. Level: {log_level}. Log file: {log_file_str}")
    except Exception as e:
         # Fallback if file logging fails (e.g., permissions)
         logger.error(f"Could not configure file logging to {log_file_str}: {e}")
         logger.warning("File logging disabled.")