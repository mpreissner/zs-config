#!/usr/bin/env python3
"""Zscaler Management CLI — interactive Rich TUI.

Usage:
    python cli/zscaler-cli.py
"""

import os
import sys

# Ensure repo root is importable regardless of working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    from db.database import init_db
    from cli.banner import render_banner
    from cli.menus import select_tenant
    from cli.menus.main_menu import main_menu
    from cli.session import set_active_tenant

    init_db()
    render_banner()

    # Select active tenant at startup (skipped if none are configured yet)
    from services.config_service import list_tenants
    if list_tenants():
        tenant = select_tenant()
        if tenant:
            set_active_tenant(tenant)

    main_menu()


if __name__ == "__main__":
    main()
