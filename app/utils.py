"""Utility functions for path resolution and common helpers."""

from pathlib import Path


def get_repo_root() -> Path:
    """
    Get the repository root directory.
    
    This function finds the repo root by looking for the prompts/ directory
    or other top-level markers. It works regardless of where the module
    is located in the package structure.
    
    Returns:
        Path to the repository root directory
    """
    # Start from this file's location
    current = Path(__file__).resolve()
    
    # Walk up the directory tree looking for prompts/ directory
    # or other top-level markers (emails.json, README.md, etc.)
    for parent in current.parents:
        if (parent / "prompts").exists() or (parent / "emails.json").exists():
            return parent
    
    # Fallback: assume we're in app/utils.py, so repo root is 2 levels up
    # This should work for the expected structure: repo/app/app/utils.py
    return current.parent.parent


def get_prompts_dir() -> Path:
    """
    Get the prompts directory path.
    
    Returns:
        Path to the prompts/ directory
    """
    return get_repo_root() / "prompts"
