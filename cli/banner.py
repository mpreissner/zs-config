"""Z-Config banner — logo, version, and screen-clear/redraw helper.

Call render_banner() at the top of every menu loop instead of a bare
console.clear() so the logo is always visible above the prompt.
"""

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

VERSION = "0.0.1"

# Generate the logo once at import time using pyfiglet (slant font).
# Falls back to the hand-drawn art if pyfiglet isn't installed.
try:
    import pyfiglet
    _LOGO_TEXT = pyfiglet.figlet_format("Z-Config", font="slant").rstrip()
except Exception:
    _LOGO_TEXT = (
        " _____        ____             __ _\n"
        "|__  /  ___  / ___|___  _ __  / _(_) __ _\n"
        "  / /  |___|| |   / _ \\| '_ \\| |_| |/ _` |\n"
        " / /__      | |__| (_) | | | |  _| | (_| |\n"
        "/____|       \\____\\___/|_| |_|_| |_|\\__, |\n"
        "                                      |___/"
    )


def render_banner() -> None:
    """Clear the screen and redraw the Z-Config logo panel.

    The subtitle shows the active tenant name when one is selected.
    """
    from cli.session import get_active_tenant

    console.clear()

    tenant = get_active_tenant()
    subtitle = (
        f"Active: {tenant.name}  |  v{VERSION}  |  Zscaler OneAPI Automation"
        if tenant
        else f"v{VERSION}  |  Zscaler OneAPI Automation"
    )

    _lines = _LOGO_TEXT.split("\n")
    _w = max(len(l) for l in _lines)
    _logo = "\n".join(l.ljust(_w) for l in _lines)

    console.print(
        Panel(
            Align(Text(_logo, style="bold cyan", no_wrap=True), align="center"),
            subtitle=subtitle,
            border_style="cyan",
            padding=(0, 4),
        )
    )
