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

from rich.console import Console

console = Console()


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
    from cli.banner import render_banner
    from cli.menus import select_tenant
    from cli.menus.main_menu import main_menu
    from cli.session import set_active_tenant

    init_db()
    render_banner()
    check_secret_key()

    # Select active tenant at startup (skipped if none are configured yet)
    from services.config_service import list_tenants
    if list_tenants():
        tenant = select_tenant()
        if tenant:
            set_active_tenant(tenant)

    main_menu()


if __name__ == "__main__":
    main()
