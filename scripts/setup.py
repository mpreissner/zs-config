#!/usr/bin/env python3
"""Interactive setup for zscaler-oneapi.conf

Prompts for the four required Zscaler OneAPI connection values, optionally
tests them against the ZIdentity token endpoint, then writes the configuration
file with chmod 600.

Usage:
    python scripts/setup.py
    python scripts/setup.py --output /etc/zscaler-oneapi.conf
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.panel import Panel
import questionary

from lib.conf_writer import DEFAULT_CONF_PATH, build_zidentity_url, test_credentials, write_conf

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Zscaler OneAPI configuration setup")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=f"Output path for conf file (default: {DEFAULT_CONF_PATH})",
    )
    args = parser.parse_args()

    console.print(
        Panel(
            "[bold cyan]Zscaler OneAPI — Configuration Setup[/bold cyan]",
            subtitle="Writes zscaler-oneapi.conf with chmod 600",
            border_style="cyan",
            padding=(0, 4),
        )
    )
    console.print()

    # --- Vanity subdomain ---
    subdomain = questionary.text(
        "Vanity subdomain:",
        instruction="e.g.  acme  →  https://acme.zslogin.net",
    ).ask()
    if not subdomain:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    subdomain = subdomain.strip().lower()
    console.print(f"  [dim]ZIdentity URL: {build_zidentity_url(subdomain)}[/dim]\n")

    # --- Client credentials ---
    client_id = questionary.text("Client ID:").ask()
    if not client_id:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    client_secret = questionary.password("Client Secret:").ask()
    if not client_secret:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # --- ZPA Customer ID (optional) ---
    customer_id = questionary.text(
        "ZPA Customer ID:",
        instruction="Press Enter to skip if not using ZPA",
    ).ask()

    # --- Output path ---
    conf_path = args.output or questionary.text(
        "Configuration file path:",
        default=DEFAULT_CONF_PATH,
    ).ask()
    if not conf_path:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    console.print()

    # --- Test credentials ---
    if questionary.confirm("Test credentials before writing?", default=True).ask():
        with console.status("Verifying credentials with ZIdentity..."):
            try:
                test_credentials(subdomain, client_id, client_secret)
                console.print("[green]✓ Credentials verified[/green]\n")
            except Exception as e:
                console.print(f"[red]✗ Credential test failed:[/red] {e}\n")
                if not questionary.confirm("Write configuration anyway?", default=False).ask():
                    console.print("[yellow]Aborted.[/yellow]")
                    return

    # --- Write file ---
    try:
        written_path = write_conf(
            path=conf_path,
            vanity_subdomain=subdomain,
            client_id=client_id,
            client_secret=client_secret,
            zpa_customer_id=customer_id or None,
        )
    except PermissionError:
        console.print(
            f"[red]✗ Permission denied writing to {conf_path}[/red]\n"
            "[yellow]Tip: run with sudo, or choose a path you own (e.g. ~/zscaler-oneapi.conf)[/yellow]"
        )
        return
    except Exception as e:
        console.print(f"[red]✗ Error writing file: {e}[/red]")
        return

    console.print(f"[green]✓ Configuration written:[/green]  {written_path}")
    console.print("[green]✓ Permissions:[/green]           600 (owner read/write only)")
    console.print(
        "\n[dim]To use with the acme.sh deploy hook:[/dim]\n"
        f"[cyan]  export DEPLOY_CONF={written_path}[/cyan]\n"
        "[cyan]  acme.sh --deploy -d '*.example.com' --deploy-hook /path/to/scripts/zpa/deploy.sh[/cyan]"
    )


if __name__ == "__main__":
    main()
