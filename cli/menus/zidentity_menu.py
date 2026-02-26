from datetime import datetime, timedelta, timezone

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zidentity_client

console = Console()


def zidentity_menu():
    client, tenant = get_zidentity_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZIdentity",
            choices=[
                questionary.Choice("Users", value="users"),
                questionary.Choice("Groups", value="groups"),
                questionary.Choice("API Clients", value="api_clients"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "users":
            users_menu(client, tenant)
        elif choice == "groups":
            groups_menu(client, tenant)
        elif choice == "api_clients":
            api_clients_menu(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

def users_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Users",
            choices=[
                questionary.Choice("List Users", value="list"),
                questionary.Choice("Search Users", value="search"),
                questionary.Choice("User Details", value="details"),
                questionary.Separator(),
                questionary.Choice("Reset Password", value="reset_pw"),
                questionary.Choice("Set Password", value="set_pw"),
                questionary.Choice("Skip MFA", value="skip_mfa"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_users(client, tenant)
        elif choice == "search":
            _search_users(client, tenant)
        elif choice == "details":
            _user_details(client, tenant)
        elif choice == "reset_pw":
            _reset_password(client, tenant)
        elif choice == "set_pw":
            _set_password(client, tenant)
        elif choice == "skip_mfa":
            _skip_mfa(client, tenant)
        elif choice in ("back", None):
            break


def _list_users(client, tenant, search_kwargs=None):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    with console.status("Fetching users..."):
        try:
            users = service.list_users(**(search_kwargs or {}))
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not users:
        console.print("[yellow]No users found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZIdentity Users ({len(users)} found)", show_lines=False)
    table.add_column("Login Name", style="cyan")
    table.add_column("Display Name")
    table.add_column("Email")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for u in users:
        status = u.get("status", "")
        status_style = "green" if status == "ACTIVE" else "yellow" if status else "dim"
        table.add_row(
            u.get("loginName") or u.get("login_name") or "—",
            u.get("displayName") or u.get("display_name") or "—",
            u.get("primaryEmail") or u.get("primary_email") or "—",
            f"[{status_style}]{status}[/{status_style}]" if status else "[dim]—[/dim]",
            str(u.get("id", "—")),
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_users(client, tenant):
    console.print("\n[bold]Search Users[/bold]")
    console.print("[dim]Fill in one or more fields; leave blank to skip.[/dim]\n")

    login_name = questionary.text("Login name (partial match):").ask()
    display_name = questionary.text("Display name (partial match):").ask()
    primary_email = questionary.text("Email (partial match):").ask()

    kwargs = {}
    if login_name:
        kwargs["login_name"] = login_name.strip()
    if display_name:
        kwargs["display_name"] = display_name.strip()
    if primary_email:
        kwargs["primary_email"] = primary_email.strip()

    if not kwargs:
        return

    _list_users(client, tenant, search_kwargs=kwargs)


def _pick_user(client, tenant, prompt="Select user:"):
    """List users and let the operator pick one. Returns the user dict or None."""
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    search = questionary.text("Search (login name / email, blank to list all):").ask()
    if search is None:
        return None

    kwargs = {}
    if search.strip():
        if "@" in search:
            kwargs["primary_email"] = search.strip()
        else:
            kwargs["login_name"] = search.strip()

    with console.status("Fetching users..."):
        try:
            users = service.list_users(**kwargs)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return None

    if not users:
        console.print("[yellow]No users found.[/yellow]")
        return None

    choices = [
        questionary.Choice(
            f"{u.get('loginName') or u.get('login_name', '?')}  "
            f"({u.get('displayName') or u.get('display_name', '')})",
            value=u,
        )
        for u in users
    ]
    return questionary.select(prompt, choices=choices).ask()


def _user_details(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    user = _pick_user(client, tenant, prompt="Select user to view:")
    if not user:
        return

    user_id = str(user.get("id", ""))

    with console.status("Fetching full details..."):
        try:
            full = service.get_user(user_id)
            groups = service.list_user_groups(user_id)
            svc_ent = service.get_service_entitlement(user_id)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    # Profile panel
    field_map = [
        ("loginName",     "Login Name"),
        ("displayName",   "Display Name"),
        ("firstName",     "First Name"),
        ("lastName",      "Last Name"),
        ("primaryEmail",  "Primary Email"),
        ("secondaryEmail","Secondary Email"),
        ("status",        "Status"),
        ("department",    "Department"),
        ("id",            "ID"),
    ]
    lines = []
    for key, label in field_map:
        val = full.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            val = val.get("name") or str(val)
        style = ""
        if key == "status":
            style = "green" if val == "ACTIVE" else "yellow"
            val = f"[{style}]{val}[/{style}]"
        lines.append(f"[bold]{label:<20}[/bold]{val}")
    console.print(Panel("\n".join(lines), title="User Profile", border_style="cyan"))

    # Groups
    if groups:
        g_table = Table(show_header=True, show_lines=False, box=None)
        g_table.add_column("Group Name", style="cyan")
        g_table.add_column("ID", style="dim")
        for g in groups:
            g_table.add_row(
                g.get("name") or g.get("displayName") or "—",
                str(g.get("id", "—")),
            )
        console.print(Panel(g_table, title=f"Groups ({len(groups)})", border_style="dim"))

    # Service entitlements
    if svc_ent:
        ent_lines = []
        for svc, val in svc_ent.items():
            if isinstance(val, bool):
                colour = "green" if val else "dim"
                ent_lines.append(f"[bold]{svc:<24}[/bold][{colour}]{val}[/{colour}]")
        if ent_lines:
            console.print(Panel("\n".join(ent_lines), title="Service Entitlements", border_style="dim"))

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _reset_password(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Reset Password[/bold]")
    console.print("[dim]Triggers a password reset for the selected user.[/dim]\n")

    user = _pick_user(client, tenant, prompt="Select user:")
    if not user:
        return

    login = user.get("loginName") or user.get("login_name", "?")
    confirmed = questionary.confirm(
        f"Send password reset for [bold]{login}[/bold]?", default=True
    ).ask()
    if not confirmed:
        return

    with console.status("Sending reset..."):
        try:
            service.reset_password(str(user["id"]), login)
            console.print(f"[green]✓ Password reset triggered for {login}[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _set_password(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Set Password[/bold]")
    console.print("[dim]Sets a specific password for the selected user.[/dim]\n")

    user = _pick_user(client, tenant, prompt="Select user:")
    if not user:
        return

    login = user.get("loginName") or user.get("login_name", "?")
    password = questionary.password(f"New password for {login}:").ask()
    if not password:
        return

    reset_on_login = questionary.confirm(
        "Require password change on next login?", default=True
    ).ask()

    with console.status("Setting password..."):
        try:
            service.update_password(str(user["id"]), login, password, reset_on_login)
            console.print(f"[green]✓ Password updated for {login}[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _skip_mfa(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Skip MFA[/bold]")
    console.print("[dim]Bypasses MFA for the selected user until a specified time.[/dim]\n")

    user = _pick_user(client, tenant, prompt="Select user:")
    if not user:
        return

    login = user.get("loginName") or user.get("login_name", "?")

    duration = questionary.select(
        "Skip MFA for how long?",
        choices=[
            questionary.Choice("1 hour", value=1),
            questionary.Choice("4 hours", value=4),
            questionary.Choice("8 hours", value=8),
            questionary.Choice("24 hours", value=24),
            questionary.Choice("72 hours (3 days)", value=72),
        ],
    ).ask()
    if duration is None:
        return

    until_dt = datetime.now(timezone.utc) + timedelta(hours=duration)
    until_ts = int(until_dt.timestamp())
    until_str = until_dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")

    confirmed = questionary.confirm(
        f"Skip MFA for [bold]{login}[/bold] until {until_str}?", default=True
    ).ask()
    if not confirmed:
        return

    with console.status("Applying MFA bypass..."):
        try:
            service.skip_mfa(str(user["id"]), login, until_ts)
            console.print(
                f"[green]✓ MFA skipped for {login} until {until_str}[/green]"
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Groups
# ------------------------------------------------------------------

def groups_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Groups",
            choices=[
                questionary.Choice("List Groups", value="list"),
                questionary.Choice("Search Groups", value="search"),
                questionary.Choice("Group Members", value="members"),
                questionary.Separator(),
                questionary.Choice("Add User to Group", value="add_user"),
                questionary.Choice("Remove User from Group", value="remove_user"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_groups(client, tenant)
        elif choice == "search":
            _search_groups(client, tenant)
        elif choice == "members":
            _group_members(client, tenant)
        elif choice == "add_user":
            _add_user_to_group(client, tenant)
        elif choice == "remove_user":
            _remove_user_from_group(client, tenant)
        elif choice in ("back", None):
            break


def _list_groups(client, tenant, name=None):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    exclude_dynamic = questionary.confirm(
        "Exclude dynamic groups?", default=False
    ).ask()

    with console.status("Fetching groups..."):
        try:
            groups = service.list_groups(name=name, exclude_dynamic=exclude_dynamic)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not groups:
        console.print("[yellow]No groups found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZIdentity Groups ({len(groups)} found)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Type")
    table.add_column("ID", style="dim")

    for g in groups:
        g_type = "Dynamic" if g.get("isDynamic") or g.get("is_dynamic") else "Static"
        table.add_row(
            g.get("name") or "—",
            g.get("description") or "[dim]—[/dim]",
            g_type,
            str(g.get("id", "—")),
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_groups(client, tenant):
    name = questionary.text("Group name (partial match):").ask()
    if not name:
        return
    _list_groups(client, tenant, name=name.strip())


def _pick_group(client, tenant, prompt="Select group:"):
    """List groups and let the operator pick one. Returns the group dict or None."""
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    search = questionary.text("Search group name (blank to list all):").ask()
    if search is None:
        return None

    with console.status("Fetching groups..."):
        try:
            groups = service.list_groups(name=search.strip() or None)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return None

    if not groups:
        console.print("[yellow]No groups found.[/yellow]")
        return None

    choices = [
        questionary.Choice(
            g.get("name") or str(g.get("id", "?")),
            value=g,
        )
        for g in groups
    ]
    return questionary.select(prompt, choices=choices).ask()


def _group_members(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    group = _pick_group(client, tenant, prompt="Select group to view members:")
    if not group:
        return

    group_id = str(group.get("id", ""))
    group_name = group.get("name", group_id)

    with console.status(f"Fetching members of '{group_name}'..."):
        try:
            members = service.list_group_members(group_id)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not members:
        console.print(f"[yellow]No members in '{group_name}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(
        title=f"Members of '{group_name}' ({len(members)} total)",
        show_lines=False,
    )
    table.add_column("Login Name", style="cyan")
    table.add_column("Display Name")
    table.add_column("Email")
    table.add_column("ID", style="dim")

    for m in members:
        table.add_row(
            m.get("loginName") or m.get("login_name") or "—",
            m.get("displayName") or m.get("display_name") or "—",
            m.get("primaryEmail") or m.get("primary_email") or "—",
            str(m.get("id", "—")),
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _add_user_to_group(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Add User to Group[/bold]\n")

    console.print("[dim]Step 1: Select group[/dim]")
    group = _pick_group(client, tenant, prompt="Select group:")
    if not group:
        return

    console.print("\n[dim]Step 2: Select user[/dim]")
    user = _pick_user(client, tenant, prompt="Select user to add:")
    if not user:
        return

    group_name = group.get("name", str(group.get("id")))
    login = user.get("loginName") or user.get("login_name", "?")

    confirmed = questionary.confirm(
        f"Add [bold]{login}[/bold] to [bold]{group_name}[/bold]?", default=True
    ).ask()
    if not confirmed:
        return

    with console.status("Adding user..."):
        try:
            service.add_user_to_group(
                str(group["id"]), group_name, str(user["id"]), login
            )
            console.print(f"[green]✓ {login} added to {group_name}[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _remove_user_from_group(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Remove User from Group[/bold]\n")

    group = _pick_group(client, tenant, prompt="Select group:")
    if not group:
        return

    group_id = str(group.get("id", ""))
    group_name = group.get("name", group_id)

    with console.status(f"Fetching members of '{group_name}'..."):
        try:
            members = service.list_group_members(group_id)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not members:
        console.print(f"[yellow]No members in '{group_name}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(
            f"{m.get('loginName') or m.get('login_name', '?')}  "
            f"({m.get('displayName') or m.get('display_name', '')})",
            value=m,
        )
        for m in members
    ]
    user = questionary.select("Select user to remove:", choices=choices).ask()
    if not user:
        return

    login = user.get("loginName") or user.get("login_name", "?")
    confirmed = questionary.confirm(
        f"Remove [bold]{login}[/bold] from [bold]{group_name}[/bold]?", default=False
    ).ask()
    if not confirmed:
        return

    with console.status("Removing user..."):
        try:
            service.remove_user_from_group(
                group_id, group_name, str(user["id"]), login
            )
            console.print(f"[green]✓ {login} removed from {group_name}[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# API Clients
# ------------------------------------------------------------------

def api_clients_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "API Clients",
            choices=[
                questionary.Choice("List API Clients", value="list"),
                questionary.Choice("Search API Clients", value="search"),
                questionary.Choice("Client Details & Secrets", value="details"),
                questionary.Separator(),
                questionary.Choice("Add Secret", value="add_secret"),
                questionary.Choice("Delete Secret", value="delete_secret"),
                questionary.Separator(),
                questionary.Choice("Delete API Client", value="delete_client"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_api_clients(client, tenant)
        elif choice == "search":
            _search_api_clients(client, tenant)
        elif choice == "details":
            _api_client_details(client, tenant)
        elif choice == "add_secret":
            _add_secret(client, tenant)
        elif choice == "delete_secret":
            _delete_secret(client, tenant)
        elif choice == "delete_client":
            _delete_api_client(client, tenant)
        elif choice in ("back", None):
            break


def _list_api_clients(client, tenant, name=None):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    with console.status("Fetching API clients..."):
        try:
            clients = service.list_api_clients(name=name)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not clients:
        console.print("[yellow]No API clients found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"API Clients ({len(clients)} found)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Description")
    table.add_column("ID", style="dim")

    for c in clients:
        status = c.get("status", "")
        style = "green" if status == "ACTIVE" else "yellow" if status else "dim"
        table.add_row(
            c.get("name") or "—",
            f"[{style}]{status}[/{style}]" if status else "[dim]—[/dim]",
            c.get("description") or "[dim]—[/dim]",
            str(c.get("id", "—")),
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_api_clients(client, tenant):
    name = questionary.text("Client name (partial match):").ask()
    if not name:
        return
    _list_api_clients(client, tenant, name=name.strip())


def _pick_api_client(client, tenant, prompt="Select API client:"):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    search = questionary.text("Search client name (blank to list all):").ask()
    if search is None:
        return None

    with console.status("Fetching API clients..."):
        try:
            clients = service.list_api_clients(name=search.strip() or None)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return None

    if not clients:
        console.print("[yellow]No API clients found.[/yellow]")
        return None

    choices = [
        questionary.Choice(c.get("name") or str(c.get("id", "?")), value=c)
        for c in clients
    ]
    return questionary.select(prompt, choices=choices).ask()


def _api_client_details(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    api_client = _pick_api_client(client, tenant, prompt="Select client to view:")
    if not api_client:
        return

    client_id = str(api_client.get("id", ""))

    with console.status("Fetching details and secrets..."):
        try:
            full = service.get_api_client(client_id)
            secrets = service.get_api_client_secrets(client_id)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    # Profile panel
    field_map = [
        ("name",                "Name"),
        ("status",              "Status"),
        ("description",         "Description"),
        ("accessTokenLifeTime", "Token Lifetime (s)"),
        ("id",                  "ID"),
    ]
    lines = []
    for key, label in field_map:
        val = full.get(key)
        if val is None:
            continue
        if key == "status":
            colour = "green" if val == "ACTIVE" else "yellow"
            val = f"[{colour}]{val}[/{colour}]"
        lines.append(f"[bold]{label:<24}[/bold]{val}")

    # Scopes
    scopes = []
    for res in (full.get("clientResources") or []):
        scopes.extend(res.get("selectedScopes") or [])
    if scopes:
        lines.append(f"[bold]{'Scopes':<24}[/bold]{', '.join(scopes)}")

    console.print(Panel("\n".join(lines), title="API Client Details", border_style="cyan"))

    # Secrets
    secret_list = secrets.get("secrets") or (secrets if isinstance(secrets, list) else [])
    if secret_list:
        s_table = Table(show_header=True, show_lines=False, box=None)
        s_table.add_column("Secret ID", style="dim")
        s_table.add_column("Expires At")
        for s in secret_list:
            s_table.add_row(
                str(s.get("id", "—")),
                s.get("expiresAt") or "[dim]never[/dim]",
            )
        console.print(Panel(s_table, title=f"Secrets ({len(secret_list)})", border_style="dim"))
    else:
        console.print("[dim]No secrets configured for this client.[/dim]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _add_secret(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Add Secret[/bold]\n")

    api_client = _pick_api_client(client, tenant, prompt="Select API client:")
    if not api_client:
        return

    client_name = api_client.get("name", str(api_client.get("id")))
    client_id = str(api_client.get("id", ""))

    expires = questionary.select(
        "Secret expiry:",
        choices=[
            questionary.Choice("No expiry", value=None),
            questionary.Choice("90 days", value=90),
            questionary.Choice("180 days", value=180),
            questionary.Choice("365 days", value=365),
        ],
    ).ask()

    expires_at = None
    if expires:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=expires)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

    with console.status("Adding secret..."):
        try:
            result = service.add_api_client_secret(client_id, client_name, expires_at)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    secret_val = result.get("secret") or result.get("clientSecret")
    if secret_val:
        console.print(
            Panel(
                f"[bold yellow]{secret_val}[/bold yellow]",
                title="New Client Secret",
                subtitle="[red]Copy this now — it will not be shown again[/red]",
                border_style="yellow",
            )
        )
    else:
        console.print("[green]✓ Secret added.[/green]")
        if result:
            console.print(f"[dim]{result}[/dim]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_secret(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Delete Secret[/bold]\n")

    api_client = _pick_api_client(client, tenant, prompt="Select API client:")
    if not api_client:
        return

    client_id = str(api_client.get("id", ""))
    client_name = api_client.get("name", client_id)

    with console.status("Fetching secrets..."):
        try:
            secrets = service.get_api_client_secrets(client_id)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    secret_list = secrets.get("secrets") or (secrets if isinstance(secrets, list) else [])
    if not secret_list:
        console.print("[yellow]No secrets found for this client.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(
            f"ID: {s.get('id', '?')}  expires: {s.get('expiresAt') or 'never'}",
            value=s,
        )
        for s in secret_list
    ]
    secret = questionary.select("Select secret to delete:", choices=choices).ask()
    if not secret:
        return

    confirmed = questionary.confirm(
        f"Delete secret [bold]{secret.get('id')}[/bold] from [bold]{client_name}[/bold]?",
        default=False,
    ).ask()
    if not confirmed:
        return

    with console.status("Deleting secret..."):
        try:
            service.delete_api_client_secret(client_id, client_name, str(secret["id"]))
            console.print("[green]✓ Secret deleted.[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_api_client(client, tenant):
    from services.zidentity_service import ZIdentityService
    service = ZIdentityService(client, tenant_id=tenant.id)

    console.print("\n[bold]Delete API Client[/bold]\n")

    api_client = _pick_api_client(client, tenant, prompt="Select client to delete:")
    if not api_client:
        return

    client_id = str(api_client.get("id", ""))
    client_name = api_client.get("name", client_id)

    confirmed = questionary.confirm(
        f"[red]Permanently delete[/red] API client [bold]{client_name}[/bold]?",
        default=False,
    ).ask()
    if not confirmed:
        return

    with console.status("Deleting client..."):
        try:
            service.delete_api_client(client_id, client_name)
            console.print(f"[green]✓ API client '{client_name}' deleted.[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()
