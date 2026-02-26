import os
from datetime import datetime

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zcc_client
from lib.zcc_client import OS_TYPE_LABELS, REGISTRATION_STATE_LABELS

console = Console()

_OS_CHOICES = [questionary.Choice(label, value=val) for val, label in OS_TYPE_LABELS.items()]
_OS_CHOICES_ALL = [questionary.Choice("All OS types", value=None)] + _OS_CHOICES

_REG_STATE_CHOICES_FILTER = [
    questionary.Choice("All (except Removed)", value=None),
    questionary.Choice("Registered", value=1),
    questionary.Choice("Removal Pending", value=3),
    questionary.Choice("Unregistered", value=4),
    questionary.Choice("Removed", value=5),
    questionary.Choice("Quarantined", value=6),
]


def zcc_menu():
    client, tenant = get_zcc_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZCC  Zscaler Client Connector",
            choices=[
                questionary.Choice("Devices", value="devices"),
                questionary.Separator(),
                questionary.Choice("OTP Lookup", value="otp"),
                questionary.Choice("App Profile Passwords", value="passwords"),
                questionary.Separator(),
                questionary.Choice("Export Devices CSV", value="export_devices"),
                questionary.Choice("Export Service Status CSV", value="export_status"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "devices":
            devices_menu(client, tenant)
        elif choice == "otp":
            _otp_lookup(client, tenant)
        elif choice == "passwords":
            _password_lookup(client, tenant)
        elif choice == "export_devices":
            _export_devices(client, tenant)
        elif choice == "export_status":
            _export_service_status(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Devices submenu
# ------------------------------------------------------------------

def devices_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Devices",
            choices=[
                questionary.Choice("List Devices", value="list"),
                questionary.Choice("Search by Username", value="search"),
                questionary.Choice("Device Details", value="details"),
                questionary.Separator(),
                questionary.Choice("Soft Remove Device", value="remove"),
                questionary.Choice("Force Remove Device", value="force_remove"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_devices(client, tenant)
        elif choice == "search":
            _search_devices(client, tenant)
        elif choice == "details":
            _device_details(client, tenant)
        elif choice == "remove":
            _remove_device(client, tenant, force=False)
        elif choice == "force_remove":
            _remove_device(client, tenant, force=True)
        elif choice in ("back", None):
            break


def _list_devices(client, tenant, username=None, os_type=None):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    if os_type is None and username is None:
        os_type = questionary.select(
            "Filter by OS type:", choices=_OS_CHOICES_ALL
        ).ask()

    with console.status("Fetching devices..."):
        try:
            devices = service.list_devices(username=username, os_type=os_type)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(
        title=f"ZCC Devices ({len(devices)} found)",
        show_lines=False,
    )
    table.add_column("Username", style="cyan")
    table.add_column("Device Name")
    table.add_column("OS", no_wrap=True)
    table.add_column("ZCC Version")
    table.add_column("Status")
    table.add_column("UDID", style="dim")

    for d in devices:
        os_int = d.get("osType") or d.get("os_type")
        reg_int = d.get("registrationState") or d.get("registration_state")
        os_str = OS_TYPE_LABELS.get(os_int, str(os_int) if os_int else "—")
        reg_str = REGISTRATION_STATE_LABELS.get(reg_int, str(reg_int) if reg_int else "—")
        reg_style = "green" if reg_int == 1 else ("yellow" if reg_int == 3 else "dim")
        table.add_row(
            d.get("userName") or d.get("username") or "—",
            d.get("deviceName") or d.get("device_name") or "—",
            os_str,
            d.get("zcClientConnectorVersion") or d.get("zc_client_connector_version") or "—",
            f"[{reg_style}]{reg_str}[/{reg_style}]",
            d.get("udid") or "—",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_devices(client, tenant):
    username = questionary.text("Username to search:").ask()
    if not username:
        return
    _list_devices(client, tenant, username=username.strip())


def _device_details(client, tenant):
    console.print("\n[bold]Device Details[/bold]")
    lookup = questionary.select(
        "Look up by:",
        choices=[
            questionary.Choice("Username", value="username"),
            questionary.Choice("UDID", value="udid"),
        ],
    ).ask()
    if not lookup:
        return

    value = questionary.text(f"Enter {lookup}:").ask()
    if not value:
        return

    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    with console.status("Fetching device details..."):
        try:
            kwargs = {"username": value.strip()} if lookup == "username" else {"udid": value.strip()}
            details = service.get_device_details(**kwargs)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not details:
        console.print("[yellow]No device found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Render as a key-value panel
    lines = []
    field_map = [
        ("userName", "Username"),
        ("deviceName", "Device Name"),
        ("osType", "OS"),
        ("zcClientConnectorVersion", "ZCC Version"),
        ("registrationState", "Status"),
        ("udid", "UDID"),
        ("owner", "Owner"),
        ("lastSeen", "Last Seen"),
        ("city", "City"),
        ("countryCode", "Country"),
        ("tunnelVersion", "Tunnel Version"),
    ]
    for key, label in field_map:
        raw = details.get(key)
        if raw is None:
            continue
        if key == "osType":
            raw = OS_TYPE_LABELS.get(raw, str(raw))
        elif key == "registrationState":
            raw = REGISTRATION_STATE_LABELS.get(raw, str(raw))
        lines.append(f"[bold]{label:<22}[/bold]{raw}")

    console.print(Panel("\n".join(lines), title="Device Details", border_style="cyan"))
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _remove_device(client, tenant, force: bool = False):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    op_label = "Force Remove" if force else "Soft Remove"
    console.print(f"\n[bold]{op_label} Device[/bold]")

    if force:
        console.print(
            "[yellow]Force remove permanently removes the device from the portal.\n"
            "Only Registered or Removal Pending devices can be force-removed.[/yellow]\n"
        )
    else:
        console.print(
            "[dim]Soft remove marks the device as Removal Pending. "
            "The ZCC client will be unenrolled on next connection.[/dim]\n"
        )

    by = questionary.select(
        "Target by:",
        choices=[
            questionary.Choice("Username (removes all devices for user)", value="username"),
            questionary.Choice("UDID (removes specific device)", value="udid"),
        ],
    ).ask()
    if not by:
        return

    value = questionary.text(f"Enter {by}:").ask()
    if not value:
        return
    value = value.strip()

    warning = (
        f"[red]Force remove[/red] {by} [bold]{value}[/bold]?"
        if force else
        f"Soft remove {by} [bold]{value}[/bold]?"
    )
    confirmed = questionary.confirm(warning, default=False).ask()
    if not confirmed:
        return

    kwargs = {"username": value} if by == "username" else {"udids": [value]}

    with console.status(f"{op_label} in progress..."):
        try:
            if force:
                result = service.force_remove_device(**kwargs)
            else:
                result = service.remove_device(**kwargs)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ {op_label} submitted.[/green]")
    if result:
        console.print(f"[dim]{result}[/dim]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# OTP Lookup
# ------------------------------------------------------------------

def _otp_lookup(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]OTP Lookup[/bold]")
    console.print(
        "[dim]One-time passwords are unique, single-use, and tied to a specific device UDID.[/dim]\n"
    )

    udid = questionary.text("Device UDID:").ask()
    if not udid:
        return

    with console.status("Fetching OTP..."):
        try:
            result = service.get_otp(udid=udid.strip())
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    otp = result.get("otp") or result.get("OTP") or str(result)
    console.print(
        Panel(
            f"[bold yellow]{otp}[/bold yellow]",
            title="One-Time Password",
            subtitle="[red]Single-use — do not share via insecure channels[/red]",
            border_style="yellow",
        )
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# App Profile Password Lookup
# ------------------------------------------------------------------

def _password_lookup(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]App Profile Passwords[/bold]")
    console.print("[dim]Returns the profile passwords assigned to a user on a given OS.[/dim]\n")

    username = questionary.text("Username:").ask()
    if not username:
        return

    os_type = questionary.select("OS type:", choices=_OS_CHOICES).ask()
    if os_type is None:
        return

    with console.status("Fetching passwords..."):
        try:
            result = service.get_passwords(username=username.strip(), os_type=os_type)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not result:
        console.print("[yellow]No password profile found for that user/OS combination.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    password_fields = [
        ("exitPass",        "Exit Password"),
        ("logoutPass",      "Logout Password"),
        ("uninstallPass",   "Uninstall Password"),
        ("zadDisablePass",  "ZAD Disable"),
        ("zdpDisablePass",  "ZDP Disable"),
        ("zdxDisablePass",  "ZDX Disable"),
        ("ziaDisablePass",  "ZIA Disable"),
        ("zpaDisablePass",  "ZPA Disable"),
    ]

    lines = []
    for key, label in password_fields:
        val = result.get(key)
        if val:
            lines.append(f"[bold]{label:<20}[/bold][yellow]{val}[/yellow]")

    if not lines:
        console.print("[yellow]No passwords set in this profile.[/yellow]")
    else:
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Passwords — {username} / {OS_TYPE_LABELS[os_type]}",
                border_style="yellow",
            )
        )

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# CSV Exports
# ------------------------------------------------------------------

def _export_devices(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]Export Devices CSV[/bold]\n")

    os_types = questionary.checkbox(
        "Filter by OS type (space to select, none = all):",
        choices=_OS_CHOICES,
    ).ask()

    reg_types = questionary.checkbox(
        "Filter by registration state (space to select, none = all):",
        choices=[
            questionary.Choice("Registered", value=1),
            questionary.Choice("Removal Pending", value=3),
            questionary.Choice("Unregistered", value=4),
            questionary.Choice("Removed", value=5),
            questionary.Choice("Quarantined", value=6),
        ],
    ).ask()

    default_path = os.path.expanduser(
        f"~/zcc-devices-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    filename = questionary.text("Save to:", default=default_path).ask()
    if not filename:
        return

    with console.status("Downloading..."):
        try:
            service.download_devices_csv(
                filename=filename,
                os_types=os_types or None,
                registration_types=reg_types or None,
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Saved to {filename}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _export_service_status(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]Export Service Status CSV[/bold]\n")

    os_types = questionary.checkbox(
        "Filter by OS type (space to select, none = all):",
        choices=_OS_CHOICES,
    ).ask()

    reg_types = questionary.checkbox(
        "Filter by registration state (space to select, none = all):",
        choices=[
            questionary.Choice("Registered", value=1),
            questionary.Choice("Removal Pending", value=3),
            questionary.Choice("Unregistered", value=4),
            questionary.Choice("Removed", value=5),
            questionary.Choice("Quarantined", value=6),
        ],
    ).ask()

    default_path = os.path.expanduser(
        f"~/zcc-service-status-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    filename = questionary.text("Save to:", default=default_path).ask()
    if not filename:
        return

    with console.status("Downloading..."):
        try:
            service.download_service_status_csv(
                filename=filename,
                os_types=os_types or None,
                registration_types=reg_types or None,
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Saved to {filename}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()
