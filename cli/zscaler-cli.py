#!/usr/bin/env python3
"""Zscaler Management CLI — interactive Rich TUI.

Usage:
    python cli/zscaler-cli.py

Requirements:
    ZSCALER_SECRET_KEY env var must be set (for encrypted DB storage).
    Run 'Settings → Generate Encryption Key' on first run if needed.
"""

import os
import sys

# Ensure repo root is importable regardless of working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

VERSION = "1.0.0"

ASCII_LOGO = r"""
 _____        ____             __ _
|__  /  ___  / ___|___  _ __  / _(_) __ _
  / /  |___|| |   / _ \| '_ \| |_| |/ _` |
 / /__      | |__| (_) | | | |  _| | (_| |
/____|       \____\___/|_| |_|_| |_|\__, |
                                      |___/
"""


def check_secret_key() -> bool:
    """Warn if ZSCALER_SECRET_KEY is not set."""
    if not os.environ.get("ZSCALER_SECRET_KEY"):
        console.print(
            "[yellow]⚠  ZSCALER_SECRET_KEY is not set.[/yellow]\n"
            "   Tenant secrets cannot be encrypted/decrypted.\n"
            "   Go to [bold]Settings → Generate Encryption Key[/bold] to create one,\n"
            "   then set it in your environment before adding tenants.\n"
        )
        return False
    return True


def main():
    from db.database import init_db
    from cli.menus.main_menu import main_menu
    from cli.menus import select_tenant
    from cli.session import set_active_tenant

    # Initialise database (creates tables if needed)
    init_db()

    # Pad all logo lines to the same width so Align centres the block as a unit
    # (justify="center" would centre each line independently against the panel width)
    _lines = ASCII_LOGO.strip().split("\n")
    _w = max(len(l) for l in _lines)
    _logo = "\n".join(l.ljust(_w) for l in _lines)

    console.print(
        Panel(
            Align(Text(_logo, style="bold cyan", no_wrap=True), align="center"),
            subtitle=f"v{VERSION}  |  Zscaler OneAPI Automation",
            border_style="cyan",
            padding=(0, 4),
        )
    )

    check_secret_key()

    # Select active tenant at startup (skipped if none are configured yet)
    from services.config_service import list_tenants
    if list_tenants():
        tenant = select_tenant()
        if tenant:
            set_active_tenant(tenant)
            console.print(f"[dim]Active tenant: [bold cyan]{tenant.name}[/bold cyan][/dim]\n")

    main_menu()


if __name__ == "__main__":
    main()
