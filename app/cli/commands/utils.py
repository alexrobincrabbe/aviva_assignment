"""CLI utility functions."""

import json
import logging
from pathlib import Path

from app.utils import get_repo_root


def load_config() -> dict:
    """
    Load configuration from config.json file.
    
    Returns:
        Dictionary with configuration values
    """
    config_path = get_repo_root() / "config.json"
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Failed to load config file {config_path}: {e}. Using defaults.")
    
    # Return default config
    return {
        "logging": {
            "level": "INFO"
        }
    }


def setup_logging():
    """Configure logging level from config file."""
    config = load_config()
    
    # Get logging level from config
    log_level_str = config.get("logging", {}).get("level", "INFO").upper()
    
    # Map string to logging level constant
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    
    level = level_map.get(log_level_str, logging.INFO)
    logging.getLogger().setLevel(level)
