import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.menus import select_tenant

console = Console()


def main_menu():
    while True:
        choice = questionary.select(
            "Main Menu",
            choices=[
                questionary.Choice("  ZPA   Zscaler Private Access", value="zpa"),
                questionary.Choice("  ZIA   Zscaler Internet Access", value="zia"),
                questionary.Separator(),
                questionary.Choice("  Settings", value="settings"),
                questionary.Choice("  Audit Log", value="audit"),
                questionary.Separator(),
                questionary.Choice("  Exit", value="exit"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "zpa":
            from cli.menus.zpa_menu import zpa_menu
            zpa_menu()
        elif choice == "zia":
            from cli.menus.zia_menu import zia_menu
            zia_menu()
        elif choice == "settings":
            settings_menu()
        elif choice == "audit":
            audit_menu()
        elif choice in ("exit", None):
            console.print("[dim]Goodbye.[/dim]")
            break


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def settings_menu():
    while True:
        choice = questionary.select(
            "Settings",
            choices=[
                questionary.Choice("Manage Tenants", value="tenants"),
                questionary.Choice("Generate Encryption Key", value="genkey"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "tenants":
            tenant_management_menu()
        elif choice == "genkey":
            _generate_key()
        elif choice in ("back", None):
            break


def tenant_management_menu():
    while True:
        choice = questionary.select(
            "Manage Tenants",
            choices=[
                questionary.Choice("Add Tenant", value="add"),
                questionary.Choice("List Tenants", value="list"),
                questionary.Choice("Remove Tenant", value="remove"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "add":
            _add_tenant()
        elif choice == "list":
            _list_tenants()
        elif choice == "remove":
            _remove_tenant()
        elif choice in ("back", None):
            break


def _add_tenant():
    console.print("\n[bold]Add Tenant[/bold]")
    name = questionary.text("Friendly name (e.g. prod, staging):").ask()
    if not name:
        return

    zidentity_url = questionary.text(
        "ZIdentity URL:", placeholder="https://vanity.zslogin.net"
    ).ask()
    client_id = questionary.text("Client ID:").ask()
    client_secret = questionary.password("Client Secret:").ask()
    customer_id = questionary.text(
        "ZPA Customer ID (leave blank if not using ZPA):"
    ).ask()
    oneapi_url = questionary.text(
        "OneAPI Base URL:", default="https://api.zsapi.net"
    ).ask()
    notes = questionary.text("Notes (optional):").ask()

    if not all([name, zidentity_url, client_id, client_secret]):
        console.print("[red]Cancelled — required fields missing.[/red]")
        return

    try:
        from services.config_service import add_tenant
        add_tenant(
            name=name,
            zidentity_base_url=zidentity_url,
            client_id=client_id,
            client_secret=client_secret,
            oneapi_base_url=oneapi_url or "https://api.zsapi.net",
            zpa_customer_id=customer_id or None,
            notes=notes or None,
        )
        console.print(f"[green]✓ Tenant '[bold]{name}[/bold]' added.[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")


def _list_tenants():
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        return

    table = Table(title="Configured Tenants", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("ZIdentity URL")
    table.add_column("OneAPI URL")
    table.add_column("ZPA Customer ID")
    table.add_column("Notes")

    for t in tenants:
        table.add_row(
            t.name,
            t.zidentity_base_url,
            t.oneapi_base_url,
            t.zpa_customer_id or "[dim]—[/dim]",
            t.notes or "[dim]—[/dim]",
        )

    console.print(table)
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _remove_tenant():
    from services.config_service import deactivate_tenant, list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        return

    tenant = questionary.select(
        "Select tenant to remove:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()

    if not tenant:
        return

    confirmed = questionary.confirm(
        f"Remove tenant '[bold]{tenant.name}[/bold]'? This cannot be undone.", default=False
    ).ask()

    if confirmed:
        deactivate_tenant(tenant.name)
        console.print(f"[green]✓ Tenant '{tenant.name}' removed.[/green]")


def _generate_key():
    from services.config_service import generate_key

    key = generate_key()
    console.print(
        Panel(
            f"[bold yellow]{key}[/bold yellow]",
            title="Generated Encryption Key",
            subtitle="Set as ZSCALER_SECRET_KEY in your environment",
            border_style="yellow",
        )
    )
    console.print(
        "[dim]Add to ~/.zshrc or ~/.bashrc:[/dim]\n"
        f"[cyan]export ZSCALER_SECRET_KEY={key}[/cyan]"
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Audit Log
# ------------------------------------------------------------------

def audit_menu():
    from services import audit_service

    with console.status("Loading audit log..."):
        logs = audit_service.get_recent(limit=50)

    if not logs:
        console.print("[yellow]No audit log entries yet.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title="Audit Log (last 50 entries)", show_lines=False)
    table.add_column("Timestamp", style="dim", no_wrap=True)
    table.add_column("Product", style="cyan")
    table.add_column("Operation")
    table.add_column("Resource")
    table.add_column("Status")

    for entry in logs:
        status_style = "green" if entry.status == "SUCCESS" else "red"
        resource = f"{entry.resource_type or ''} {entry.resource_name or ''}".strip()
        table.add_row(
            entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            entry.product or "",
            entry.operation or "",
            resource or "[dim]—[/dim]",
            f"[{status_style}]{entry.status or ''}[/{status_style}]",
        )

    console.print(table)
    questionary.press_any_key_to_continue("Press any key to continue...").ask()
