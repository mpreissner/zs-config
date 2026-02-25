import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zia_client

console = Console()


def zia_menu():
    client, tenant = get_zia_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZIA",
            choices=[
                questionary.Choice("Activation", value="activation"),
                questionary.Choice("URL Lookup", value="url_lookup"),
                questionary.Choice("URL Categories    [coming soon]", value="url_cats"),
                questionary.Choice("URL Filter Rules  [coming soon]", value="url_rules"),
                questionary.Choice("Users             [coming soon]", value="users"),
                questionary.Choice("Locations         [coming soon]", value="locations"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "activation":
            _activation_menu(client, tenant)
        elif choice == "url_lookup":
            _url_lookup(client, tenant)
        elif choice in ("url_cats", "url_rules", "users", "locations"):
            console.print("[yellow]Coming soon.[/yellow]")
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Activation
# ------------------------------------------------------------------

def _activation_menu(client, tenant):
    from services.zia_service import ZIAService
    service = ZIAService(client, tenant_id=tenant.id)
    while True:
        render_banner()
        with console.status("Checking activation status..."):
            try:
                status = service.get_activation_status()
            except Exception as e:
                console.print(f"[red]✗ Could not fetch status: {e}[/red]")
                return

        state = status.get("status", "UNKNOWN")
        state_colour = "green" if state == "ACTIVE" else "yellow"
        console.print(f"\nActivation status: [{state_colour}][bold]{state}[/bold][/{state_colour}]")

        choice = questionary.select(
            "Activation",
            choices=[
                questionary.Choice("Activate Pending Changes", value="activate"),
                questionary.Choice("Refresh Status", value="refresh"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "activate":
            _activate(client, tenant)
        elif choice == "refresh":
            continue
        elif choice in ("back", None):
            break


def _activate(client, tenant):
    confirmed = questionary.confirm(
        "Activate all pending ZIA configuration changes?", default=True
    ).ask()
    if not confirmed:
        return

    from services.zia_service import ZIAService

    service = ZIAService(client, tenant_id=tenant.id)
    with console.status("Activating..."):
        try:
            result = service.activate()
            state = result.get("status", "UNKNOWN") if result else "UNKNOWN"
            console.print(f"[green]✓ Activation complete — status: {state}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Activation failed: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# URL Lookup
# ------------------------------------------------------------------

def _url_lookup(client, tenant):
    from services.zia_service import ZIAService
    service = ZIAService(client, tenant_id=tenant.id)

    console.print("\n[bold]URL Category Lookup[/bold]")
    console.print("[dim]Enter URLs to look up (one per line, blank line to submit).[/dim]\n")

    urls = []
    while True:
        url = questionary.text("URL (blank to submit):").ask()
        if not url:
            break
        urls.append(url.strip())

    if not urls:
        return

    with console.status("Looking up URLs..."):
        try:
            results = service.url_lookup(urls)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    table = Table(title="URL Lookup Results", show_lines=False)
    table.add_column("URL")
    table.add_column("Category")

    for r in results:
        categories = ", ".join(r.get("urlClassifications", [])) or "[dim]Uncategorised[/dim]"
        table.add_row(r.get("url", ""), categories)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())
