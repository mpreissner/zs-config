"""Plugin manager TUI — accessed via Ctrl+\\ from the main menu.

Not listed in the main menu.  Allows authenticated users to browse
available plugins from the private manifest repo and install/uninstall them.
"""

import sys

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner

console = Console()


def plugin_menu() -> None:
    while True:
        render_banner()

        from lib.github_auth import get_token, is_authenticated, verify_token
        from lib.plugin_manager import (
            get_installed_plugins, get_plugin_channel, get_plugin_branch_overrides,
        )

        installed  = get_installed_plugins()
        channel    = get_plugin_channel()
        overrides  = get_plugin_branch_overrides()

        # ── Auth status header ────────────────────────────────────────────
        token = get_token()
        if token:
            valid, username = verify_token(token)
            if valid:
                auth_line = f"[green]● Authenticated as [bold]{username}[/bold][/green]"
            else:
                auth_line = f"[yellow]● Token invalid ({username}) — please re-authenticate[/yellow]"
                valid = False
        else:
            auth_line = "[dim]● Not authenticated[/dim]"
            valid = False

        if channel == "dev":
            channel_line = "[yellow]⚠  Channel: [bold]dev[/bold] — pre-release builds active[/yellow]"
        else:
            channel_line = "[dim]Channel: stable[/dim]"

        if overrides:
            override_lines = "\n".join(
                f"[magenta]⚙  {pkg} branch override: [bold]{branch}[/bold][/magenta]"
                for pkg, branch in sorted(overrides.items())
            )
            override_line = "\n" + override_lines
        else:
            override_line = ""

        console.print(Panel(
            auth_line + "\n" + channel_line + override_line,
            title="Plugin Manager",
            border_style="cyan",
        ))

        # ── Installed plugins summary ─────────────────────────────────────
        if installed:
            table = Table(show_header=True, box=None, padding=(0, 2))
            table.add_column("Plugin",  style="bold cyan")
            table.add_column("Package", style="dim")
            table.add_column("Version", style="dim")
            table.add_column("Status")
            for p in installed:
                status = "[red]load error[/red]" if p.get("error") else "[green]active[/green]"
                table.add_row(p["name"], p["package"], p["version"], status)
            console.print(table)
        else:
            console.print("[dim]  No plugins installed.[/dim]\n")

        # ── Menu choices ──────────────────────────────────────────────────
        choices = []
        if valid:
            choices.append(questionary.Choice("  Browse available plugins", value="browse"))
        if installed:
            choices.append(questionary.Choice("  Uninstall a plugin",       value="uninstall"))
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  Switch plugin channel",        value="channel"))
        choices.append(questionary.Separator())
        if valid:
            choices.append(questionary.Choice("  Log out of GitHub",        value="logout"))
        else:
            choices.append(questionary.Choice("  Log in with GitHub",       value="login"))
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  ← Back",                       value="back"))

        q = questionary.select("Plugin Manager", choices=choices)

        # Inject Ctrl+] binding for the hidden per-plugin branch override.
        from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
        _branch_kb = KeyBindings()

        @_branch_kb.add("c-]")
        def _branch_toggle_key(event):
            event.app.exit(result="__branch_toggle__")

        app = q.application
        app.key_bindings = merge_key_bindings(
            [app.key_bindings or KeyBindings(), _branch_kb]
        )
        action = app.run()

        if action == "browse":
            _browse_plugins()
        elif action == "install":
            _install_plugin_by_url()
        elif action == "uninstall":
            _uninstall_plugin(installed)
        elif action == "channel":
            _switch_channel(channel)
        elif action == "login":
            _login()
        elif action == "logout":
            _logout()
        elif action == "__branch_toggle__":
            _branch_override_menu(installed, overrides)
        elif action in ("back", None):
            break


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _login() -> None:
    from lib.github_auth import authenticate, is_authenticated

    if is_authenticated():
        console.print("[yellow]Already authenticated. Log out first to switch accounts.[/yellow]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    console.print()
    console.print("[bold]GitHub Authentication[/bold]")
    console.print(
        "[dim]A browser window will open. Complete authentication there "
        "(including MFA if required), then return here.[/dim]\n"
    )

    messages = []

    def _progress(msg: str) -> None:
        messages.append(msg)
        console.print(f"  {msg}")

    with console.status("[cyan]Waiting for GitHub authorization...[/cyan]"):
        success, message = authenticate(progress_callback=_progress)

    if success:
        console.print(f"\n[green]✓ {message}[/green]")
    else:
        console.print(f"\n[red]✗ {message}[/red]")

    questionary.press_any_key_to_continue("Press any key...").ask()


def _logout() -> None:
    from lib.github_auth import logout

    confirmed = questionary.confirm(
        "Log out of GitHub? Installed plugins will continue to work.",
        default=False,
    ).ask()
    if confirmed:
        logout()
        console.print("[green]✓ Logged out.[/green]")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _switch_channel(current: str) -> None:
    from lib.plugin_manager import set_plugin_channel

    target = "stable" if current == "dev" else "dev"

    console.print()
    if target == "dev":
        console.print(
            Panel(
                "[yellow][bold]Warning — dev channel[/bold]\n\n"
                "Dev builds are pre-release and may contain incomplete features, "
                "breaking changes, or unexpected behaviour.\n\n"
                "Do not use dev builds in production environments.[/yellow]",
                border_style="yellow",
            )
        )

    confirmed = questionary.confirm(
        f"Switch plugin channel from '{current}' to '{target}'?",
        default=False,
    ).ask()

    if not confirmed:
        return

    set_plugin_channel(target)
    console.print(f"[green]✓ Plugin channel set to [bold]{target}[/bold].[/green]\n")

    from cli.update_checker import check_plugin_updates
    check_plugin_updates()
    questionary.press_any_key_to_continue("Press any key...").ask()


def _browse_plugins() -> None:
    from lib.plugin_manager import fetch_manifest, get_installed_plugins, install_plugin

    console.print()
    with console.status("[cyan]Fetching available plugins...[/cyan]"):
        available, error = fetch_manifest()

    if error:
        console.print(f"[red]✗ {error}[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    if not available:
        console.print("[yellow]No plugins available in the manifest.[/yellow]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    installed_packages = {p["package"] for p in get_installed_plugins()}

    # ── Display available plugins ─────────────────────────────────────────
    table = Table(title="Available Plugins", show_lines=True)
    table.add_column("Plugin",      style="bold cyan")
    table.add_column("Description")
    table.add_column("Version")
    table.add_column("Status")
    for p in available:
        status = (
            "[green]installed[/green]"
            if p.get("package") in installed_packages
            else "[dim]not installed[/dim]"
        )
        table.add_row(
            p.get("display_name") or p.get("name", ""),
            p.get("description", ""),
            p.get("version", ""),
            status,
        )
    console.print(table)
    console.print()

    # ── Offer install for any not yet installed ───────────────────────────
    not_installed = [
        p for p in available
        if p.get("package") not in installed_packages
    ]
    if not not_installed:
        console.print("[green]All available plugins are already installed.[/green]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    choices = [
        questionary.Choice(
            f"{p.get('display_name') or p.get('name')}  —  {p.get('description', '')}",
            value=p,
        )
        for p in not_installed
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("← Cancel", value="__cancel__"))

    plugin = questionary.select("Select a plugin to install:", choices=choices).ask()
    if not plugin or plugin == "__cancel__":
        return

    _do_install(plugin)


def _do_install(plugin: dict) -> None:
    from lib.plugin_manager import install_plugin, effective_install_url

    install_url = effective_install_url(plugin) if plugin.get("install_url") else None
    if not install_url:
        console.print("[red]✗ No install URL in manifest entry.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    name = plugin.get("display_name") or plugin.get("name", "plugin")
    console.print(f"\nInstalling [bold]{name}[/bold]...")
    console.print(f"[dim]  {install_url}[/dim]\n")

    with console.status(f"[cyan]Running pip install...[/cyan]"):
        success, message = install_plugin(install_url)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print(
            Panel(
                "[green]Plugin installed.[/green] zs-config will now exit — "
                "please re-launch to activate the new plugin.",
                border_style="green",
            )
        )
        questionary.press_any_key_to_continue("Press any key to exit...").ask()
        sys.exit(0)
    else:
        console.print(f"[red]✗ Installation failed:[/red]\n{message}")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _install_plugin_by_url() -> None:
    """Fallback: install directly from a git URL (no manifest needed)."""
    url = questionary.text(
        "Enter pip-compatible install URL:",
        instruction="e.g. git+ssh://git@github.com/org/repo.git#subdirectory=plugin_name",
    ).ask()
    if not url:
        return
    _do_install({"install_url": url, "name": url})


def _branch_override_menu(installed: list[dict], overrides: dict) -> None:
    """Secret Ctrl+] handler: set or clear a branch override for any installed plugin."""
    from lib.plugin_manager import (
        fetch_manifest, install_plugin,
        set_plugin_branch_override, url_for_branch,
    )

    if not installed:
        console.print("\n[yellow]No plugins installed.[/yellow]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    console.print()
    console.print(Panel(
        "Set a branch override to install a plugin from a specific git branch.\n"
        "The plugin will be reinstalled from that branch and zs-config will restart.",
        border_style="magenta",
        title="Developer — Branch Override",
    ))

    # ── Step 1: pick a plugin ─────────────────────────────────────────────
    plugin_choices = []
    for p in installed:
        pkg = p["package"]
        current = overrides.get(pkg)
        label = f"{p['name']}  [{pkg}]"
        if current:
            label += f"  (override: {current})"
        plugin_choices.append(questionary.Choice(label, value=p))
    plugin_choices.append(questionary.Choice("← Cancel", value=None))

    selected = questionary.select(
        "Select plugin to override:",
        choices=plugin_choices,
        use_indicator=True,
    ).ask()
    if not selected:
        return

    pkg = selected["package"]
    current_override = overrides.get(pkg)

    # ── Step 2: branch input or clear ────────────────────────────────────
    action_choices = [
        questionary.Choice("Enter a branch name", value="set"),
    ]
    if current_override:
        action_choices.append(questionary.Choice(
            f"Clear override (revert to channel default)", value="clear"
        ))
    action_choices.append(questionary.Choice("← Cancel", value=None))

    action = questionary.select(
        f"Branch override for {pkg}:",
        choices=action_choices,
        use_indicator=True,
    ).ask()
    if not action:
        return

    if action == "clear":
        target_branch = None
    else:
        target_branch = questionary.text(
            "Branch name:",
            default=current_override or "",
        ).ask()
        if not target_branch or not target_branch.strip():
            return
        target_branch = target_branch.strip()

    # ── Step 3: fetch manifest, resolve URL, reinstall ────────────────────
    console.print()
    with console.status("[cyan]Fetching manifest...[/cyan]"):
        available, error = fetch_manifest()

    if error:
        console.print(f"[red]✗ {error}[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    plugin_entry = next(
        (p for p in (available or []) if p.get("package") == pkg),
        None,
    )
    if not plugin_entry:
        console.print(f"[red]✗ {pkg} not found in manifest.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    base_url = plugin_entry.get("install_url_dev") or plugin_entry.get("install_url", "")
    if not base_url:
        console.print(f"[red]✗ No install URL in manifest for {pkg}.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    if target_branch is None:
        # Clearing: reinstall from the channel default URL
        from lib.plugin_manager import effective_install_url
        install_url = effective_install_url(plugin_entry)
        action_label = "channel default"
    else:
        install_url = url_for_branch(base_url, target_branch)
        action_label = target_branch

    confirmed = questionary.confirm(
        f"Reinstall {pkg} from '{action_label}' and restart?",
        default=False,
    ).ask()
    if not confirmed:
        return

    console.print(f"[dim]  {install_url}[/dim]\n")
    with console.status(f"[cyan]Installing {pkg} @ {action_label}...[/cyan]"):
        success, message = install_plugin(install_url)

    if success:
        set_plugin_branch_override(pkg, target_branch)  # None clears the override
        console.print(f"[green]✓ {message}[/green]")
        console.print(Panel(
            f"[green]{pkg} switched to [bold]{action_label}[/bold].[/green] "
            "zs-config will now exit — please re-launch to activate the update.",
            border_style="green",
        ))
        questionary.press_any_key_to_continue("Press any key to exit...").ask()
        sys.exit(0)
    else:
        console.print(f"[red]✗ Installation failed:[/red]\n{message}")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _uninstall_plugin(installed: list[dict]) -> None:
    from lib.plugin_manager import uninstall_plugin

    choices = [
        questionary.Choice(f"{p['name']}  ({p['package']} {p['version']})", value=p)
        for p in installed
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("← Cancel", value="__cancel__"))

    plugin = questionary.select("Select plugin to uninstall:", choices=choices).ask()
    if not plugin or plugin == "__cancel__":
        return

    confirmed = questionary.confirm(
        f"Uninstall '{plugin['name']}'? This cannot be undone without reinstalling.",
        default=False,
    ).ask()
    if not confirmed:
        return

    with console.status(f"[cyan]Uninstalling {plugin['package']}...[/cyan]"):
        success, message = uninstall_plugin(plugin["package"])

    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print("[dim]Restart zs-config to fully remove the plugin.[/dim]")
    else:
        console.print(f"[red]✗ {message}[/red]")

    questionary.press_any_key_to_continue("Press any key...").ask()
