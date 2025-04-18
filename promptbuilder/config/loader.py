# promptbuilder/config/loader.py
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from loguru import logger

from .schema import AppConfig
from .paths import get_user_config_file, get_bundled_config_path

_cached_config: Optional[AppConfig] = None

def load_config() -> AppConfig:
    """Loads the application configuration."""
    global _cached_config
    if _cached_config:
        return _cached_config

    config_path = get_user_config_file()
    loaded_data = {}

    if config_path.exists():
        logger.info(f"Loading user configuration from: {config_path}")
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load user config file {config_path}: {e}")
            # Consider backing up the corrupted file here
            try:
                 backup_path = config_path.with_suffix(".json.corrupted")
                 if backup_path.exists(): backup_path.unlink(missing_ok=True) # Remove old backup
                 config_path.rename(backup_path)
                 logger.info(f"Backed up corrupted config to: {backup_path}")
            except OSError as backup_err:
                 logger.error(f"Failed to backup corrupted config: {backup_err}")
            loaded_data = {} # Fallback to defaults
    else:
        logger.info("User config file not found, trying bundled config.")
        bundled_path = get_bundled_config_path()
        if bundled_path and bundled_path.exists():
             logger.info(f"Loading bundled configuration from: {bundled_path}")
             try:
                 with open(bundled_path, 'r', encoding='utf-8') as f:
                     loaded_data = json.load(f)
             except (json.JSONDecodeError, OSError) as e:
                 logger.error(f"Failed to load bundled config file {bundled_path}: {e}")
                 loaded_data = {}
        else:
            logger.info("No user or bundled config found. Using default settings.")

    try:
        config = AppConfig(**loaded_data)
        _cached_config = config
        logger.info("Configuration loaded successfully.")
        # Optionally save the config back immediately if it was created/migrated
        # save_config(config) # Avoid saving on load unless needed
        return config
    except ValidationError as e:
        logger.error(f"Configuration validation failed: {e}")
        logger.warning("Falling back to default configuration.")
        _cached_config = AppConfig() # Use default config on validation error
        return _cached_config

    # TODO: Implement environment variable overrides (PROMPTBUILDER_*)

def save_config(config: AppConfig) -> None:
    """Saves the application configuration using atomic write via NamedTemporaryFile."""
    config_path = get_user_config_file()
    logger.info(f"Saving configuration to: {config_path}")
    temp_file_path: Optional[Path] = None
    try:
        # Fixes Polish P-3: Use NamedTemporaryFile for atomic save and cleanup
        # Create temp file in the *same directory* as the target for atomic os.replace
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=config_path.parent,
            prefix=f".{config_path.name}_tmp", # Use a prefix related to the target file
            suffix=".json",
            delete=False # Keep the file after closing for os.replace
        ) as temp_f:
            temp_file_path = Path(temp_f.name)
            logger.debug(f"Writing config to temporary file: {temp_file_path}")
            # Use Pydantic's json export for proper serialization
            temp_f.write(config.model_dump_json(indent=4))
            # Ensure data is flushed to disk before replacing
            temp_f.flush()
            os.fsync(temp_f.fileno())

        # Atomically replace the original file with the temporary file
        os.replace(temp_file_path, config_path)
        logger.info("Configuration saved successfully.")
        temp_file_path = None # Prevent cleanup in finally block if replace succeeded

    except (OSError, IOError, TypeError, AttributeError) as e:
        logger.error(f"Failed to save configuration to {config_path}: {e}")
        # Attempt to clean up the temporary file if replace failed or error occurred before replace
        if temp_file_path and temp_file_path.exists():
            logger.warning(f"Attempting to clean up temporary config file: {temp_file_path}")
            try:
                temp_file_path.unlink()
            except OSError as unlink_err:
                 logger.error(f"Failed to remove temporary config file {temp_file_path}: {unlink_err}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during config save: {e}")
        if temp_file_path and temp_file_path.exists():
             logger.warning(f"Attempting to clean up temporary config file after unexpected error: {temp_file_path}")
             try: temp_file_path.unlink()
             except OSError as unlink_err: logger.error(f"Failed to remove temporary config file {temp_file_path}: {unlink_err}")
    finally:
        # Final check: Ensure temp file is removed if it still exists (e.g., power loss scenario unlikely handled here)
        # This block might not execute on power loss, but handles other exceptions.
        if temp_file_path and temp_file_path.exists():
             logger.warning(f"Cleaning up leftover temporary config file in finally block: {temp_file_path}")
             try: temp_file_path.unlink()
             except OSError as unlink_err: logger.error(f"Failed to remove temporary config file {temp_file_path} in finally: {unlink_err}")


def get_config() -> AppConfig:
    """Returns the cached configuration object, loading if necessary."""
    if _cached_config is None:
        return load_config()
    return _cached_config