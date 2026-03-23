"""Shared default paths for zs-config."""

from pathlib import Path

# Default working directory for all user files (XML exports, CSVs, output dirs, etc.)
# Created on first launch by cli/z_config.py.
DEFAULT_WORK_DIR = Path.home() / 'Documents' / 'zs-config'
