"""Basic tests for utility functions."""

from src.utils import load_settings, get_project_root


def test_load_settings():
    settings = load_settings()
    assert "moomoo" in settings
    assert settings["moomoo"]["port"] == 11111


def test_get_project_root():
    root = get_project_root()
    assert (root / "README.md").exists()
