"""Update checker — silently checks GitHub releases for a newer zs-config version on startup."""

import re
import sys
from typing import Optional

import requests
from rich.console import Console
from rich.panel import Panel

import questionary

from services.update_notify_service import DEPLOY_ONELINER, fetch_latest_version

CHANGELOG_URL = "https://raw.githubusercontent.com/mpreissner/zs-config/main/CHANGELOG.md"
REQUEST_TIMEOUT = 4          # version check (GitHub API)
CHANGELOG_TIMEOUT = 10       # changelog fetch (raw.githubusercontent.com — can be slower)

console = Console()


def _parse_ver(v: str) -> tuple:
    v = v.lstrip("v")
    return tuple(int(x) for x in v.split("."))


def _fetch_changelog() -> Optional[str]:
    try:
        resp = requests.get(CHANGELOG_URL, timeout=CHANGELOG_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _extract_changelog_sections(changelog: str, from_ver: str, to_ver: str) -> str:
    pattern = re.compile(r"^## \[(\d+[\.\d]+)\]", re.MULTILINE)
    matches = list(pattern.finditer(changelog))

    from_parsed = _parse_ver(from_ver)
    to_parsed = _parse_ver(to_ver)

    sections = []
    for i, match in enumerate(matches):
        ver_str = match.group(1)
        try:
            ver = _parse_ver(ver_str)
        except ValueError:
            continue
        if from_parsed < ver <= to_parsed:
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog)
            section = changelog[start:end].strip()
            section = re.sub(r"\n+---\s*$", "", section).strip()
            sections.append(section)

    return "\n\n---\n\n".join(sections)


def check_for_updates() -> bool:
    """Check GitHub releases for a newer zs-config version.

    zs-config ships as a container deployment only, so there is nothing to
    upgrade in place — the prompt shows the changelog and the redeploy command.

    Returns True if an update was found, False otherwise.  Callers use the
    return value to decide whether to skip downstream checks (e.g. plugin
    updates) until next launch.
    """
    from cli.banner import VERSION

    latest = fetch_latest_version(timeout=REQUEST_TIMEOUT)
    if latest is None:
        return False

    try:
        if _parse_ver(latest) <= _parse_ver(VERSION):
            return False
    except Exception:
        return False

    console.print(
        Panel(
            f"Update available: v{VERSION} → v{latest}",
            border_style="yellow",
        )
    )

    changelog = _fetch_changelog()
    if changelog is None:
        console.print("[dim]Could not fetch changelog (network timeout).[/dim]")
    elif changelog:
        sections = _extract_changelog_sections(changelog, VERSION, latest)
        if sections:
            questionary.press_any_key_to_continue("Press any key to view changelog...").ask()
            from rich.markdown import Markdown
            from cli.scroll_view import render_rich_to_lines, scroll_view
            scroll_view(render_rich_to_lines(Markdown(sections)))

    console.print(
        Panel(
            "To update, re-run the deployment script on your Docker host:\n\n"
            f"  {DEPLOY_ONELINER}\n\n"
            "Or, if you already have the repo cloned:\n\n"
            "  ./deploy.sh main",
            border_style="yellow",
        )
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()
    return True


def check_plugin_updates() -> None:
    """Check the plugin manifest for newer versions of installed plugins.

    Skipped entirely if:
    - No plugins are installed
    - No GitHub token is present
    - The manifest cannot be fetched

    Runs silently when everything is current.
    """
    from lib.plugin_manager import get_installed_plugins, fetch_manifest, install_plugin, effective_install_url
    from lib.github_auth import get_token
    from rich.table import Table

    # Skip if no plugins installed
    installed = get_installed_plugins()
    if not installed:
        return

    # Skip if not authenticated
    if not get_token():
        return

    # Fetch manifest — skip silently on any error
    manifest_plugins, error = fetch_manifest()
    if error or not manifest_plugins:
        return

    # Build map of package → manifest entry for installed packages
    installed_map = {p["package"]: p for p in installed if not p.get("error")}
    manifest_map  = {p["package"]: p for p in manifest_plugins}

    updates = []
    for pkg, inst in installed_map.items():
        manifest = manifest_map.get(pkg)
        if not manifest:
            continue
        avail_ver = manifest.get("version", "")
        inst_ver  = inst.get("version", "")
        try:
            if avail_ver and _parse_ver(avail_ver) > _parse_ver(inst_ver):
                updates.append({
                    "display_name": manifest.get("display_name", pkg),
                    "package":      pkg,
                    "installed":    inst_ver,
                    "available":    avail_ver,
                    "install_url":  effective_install_url(manifest),
                })
        except Exception:
            continue

    if not updates:
        return

    # Show what's available
    table = Table(show_header=True, show_lines=False, box=None, padding=(0, 2))
    table.add_column("Plugin")
    table.add_column("Installed")
    table.add_column("Available")
    for u in updates:
        table.add_row(u["display_name"], u["installed"], f"[green]{u['available']}[/green]")

    noun = "update" if len(updates) == 1 else "updates"
    console.print(
        Panel(
            table,
            title=f"[yellow]Plugin {noun} available[/yellow]",
            border_style="yellow",
        )
    )

    answer = questionary.confirm(
        f"Update {len(updates)} plugin {noun} now?",
        default=True,
    ).ask()

    if not answer:
        console.print("[dim]Skipping plugin updates.[/dim]")
        return

    any_updated = False
    for u in updates:
        with console.status(f"[cyan]Updating {u['display_name']}...[/cyan]"):
            ok, msg = install_plugin(u["install_url"])
        if ok:
            console.print(f"[green]✓ {u['display_name']} updated to v{u['available']}[/green]")
            any_updated = True
        else:
            console.print(f"[red]✗ {u['display_name']} update failed:[/red] {msg}")

    if any_updated:
        console.print(
            Panel(
                "[green]Plugin update complete.[/green] zs-config will now exit — "
                "please re-launch to load the updated plugin(s).",
                border_style="green",
            )
        )
        questionary.press_any_key_to_continue("Press any key to exit...").ask()
        sys.exit(0)
