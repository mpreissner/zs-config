import questionary
from rich.console import Console
from rich.table import Table

from cli.menus import get_zpa_client

console = Console()


def zpa_menu():
    client, tenant = get_zpa_client()
    if client is None:
        return

    console.print(f"[dim]Connected: [bold]{tenant.name}[/bold][/dim]")

    while True:
        choice = questionary.select(
            "ZPA",
            choices=[
                questionary.Choice("Certificate Management", value="certs"),
                questionary.Choice("Application Segments  [coming soon]", value="apps"),
                questionary.Choice("PRA Portals           [coming soon]", value="pra"),
                questionary.Choice("Connectors            [coming soon]", value="connectors"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "certs":
            cert_menu(client, tenant)
        elif choice in ("apps", "pra", "connectors"):
            console.print("[yellow]Coming soon.[/yellow]")
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Certificate Management
# ------------------------------------------------------------------

def cert_menu(client, tenant):
    while True:
        choice = questionary.select(
            "Certificate Management",
            choices=[
                questionary.Choice("List Certificates", value="list"),
                questionary.Choice("Rotate Certificate for Domain", value="rotate"),
                questionary.Choice("Delete Certificate", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_certificates(client)
        elif choice == "rotate":
            _rotate_certificate(client, tenant)
        elif choice == "delete":
            _delete_certificate(client, tenant)
        elif choice in ("back", None):
            break


def _list_certificates(client):
    with console.status("Fetching certificates..."):
        try:
            certs = client.list_certificates()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    if not certs:
        console.print("[yellow]No certificates found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZPA Certificates ({len(certs)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Expiry")

    for c in certs:
        table.add_row(
            str(c.get("id", "")),
            c.get("name", ""),
            c.get("status", ""),
            c.get("issuedTo", "") or "[dim]—[/dim]",
        )

    console.print(table)
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _rotate_certificate(client, tenant):
    console.print("\n[bold]Rotate Certificate for Domain[/bold]")
    console.print("[dim]This will upload a new cert and update all matching apps and PRA portals.[/dim]\n")

    domain = questionary.text("Domain (e.g. *.example.com):").ask()
    if not domain:
        return

    cert_path = questionary.path("Path to certificate PEM file:").ask()
    key_path = questionary.path("Path to private key PEM file:").ask()

    if not all([cert_path, key_path]):
        return

    confirmed = questionary.confirm(
        f"Rotate certificate for [bold]{domain}[/bold]?", default=True
    ).ask()
    if not confirmed:
        return

    from services.zpa_service import ZPAService

    service = ZPAService(client, tenant_id=tenant.id)

    with console.status(f"Rotating certificate for {domain}..."):
        try:
            result = service.rotate_certificate(cert_path, key_path, domain)
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            return

    console.print(f"\n[green]✓ Certificate rotation complete[/green]")
    console.print(f"  New cert:    [bold]{result['cert_name']}[/bold] (ID: {result['new_cert_id']})")
    console.print(f"  Apps updated:    {result['apps_updated']}")
    console.print(f"  Portals updated: {result['portals_updated']}")
    console.print(f"  Old certs deleted: {result['certs_deleted']}")

    if result["apps_updated"] + result["portals_updated"] == 0:
        console.print(
            f"\n[yellow]⚠ No resources matched domain '{domain}'. "
            "Certificate was uploaded but not assigned.[/yellow]"
        )

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_certificate(client, tenant):
    with console.status("Fetching certificates..."):
        try:
            certs = client.list_certificates()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    if not certs:
        console.print("[yellow]No certificates found.[/yellow]")
        return

    cert = questionary.select(
        "Select certificate to delete:",
        choices=[
            questionary.Choice(
                f"{c.get('name', 'unnamed')}  [dim](ID: {c.get('id')})[/dim]",
                value=c,
            )
            for c in certs
        ],
    ).ask()

    if not cert:
        return

    confirmed = questionary.confirm(
        f"Delete [bold]{cert.get('name')}[/bold]? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    from services.zpa_service import ZPAService

    service = ZPAService(client, tenant_id=tenant.id)
    try:
        service.delete_certificate(str(cert["id"]))
        console.print(f"[green]✓ Certificate deleted.[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()
