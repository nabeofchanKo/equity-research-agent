"""
Shared utilities for moomoo-dashboard.
"""

import yaml
from pathlib import Path

def load_settings() -> dict:
    """Load settings from config/settings.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent
