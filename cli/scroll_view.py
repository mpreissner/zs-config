"""Full-screen scrollable content viewer using prompt_toolkit.

prompt_toolkit is already installed as a questionary dependency, so no
extra packages are needed.  The viewer uses the alternate screen buffer
(full_screen=True) so the original terminal state is restored on exit.
"""

import shutil
from io import StringIO
from typing import List

from rich.console import Console as RichConsole


def render_rich_to_lines(renderable, width: int = 0) -> List[str]:
    """Render any Rich renderable to a list of ANSI-encoded strings."""
    if not width:
        width = shutil.get_terminal_size().columns
    buf = StringIO()
    cap = RichConsole(file=buf, width=width, force_terminal=True, highlight=False)
    cap.print(renderable)
    return buf.getvalue().splitlines()


def scroll_view(lines: List[str], header_ansi: str = "") -> None:
    """Display lines in a full-screen viewer with a pinned header.

    Keybindings:
        ↑ / k          scroll up one line
        ↓ / j          scroll down one line
        PageUp         scroll up half a page
        PageDown       scroll down half a page
        g / Home       jump to top
        G / End        jump to bottom
        q / Ctrl+C     exit
    """
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    cols, rows = shutil.get_terminal_size()
    header_height = len(header_ansi.rstrip("\n").splitlines()) if header_ansi else 0
    status_height = 1
    content_height = max(1, rows - header_height - status_height)

    total = len(lines)
    max_offset = max(0, total - content_height)
    offset = [0]

    kb = KeyBindings()

    @kb.add("q")
    @kb.add("c-c")
    def _quit(event):
        event.app.exit()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        if offset[0] > 0:
            offset[0] -= 1

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        if offset[0] < max_offset:
            offset[0] += 1

    @kb.add("pagedown")
    @kb.add("space")
    def _pgdn(event):
        offset[0] = min(max_offset, offset[0] + content_height // 2)

    @kb.add("pageup")
    def _pgup(event):
        offset[0] = max(0, offset[0] - content_height // 2)

    @kb.add("g")
    @kb.add("home")
    def _top(event):
        offset[0] = 0

    @kb.add("G")
    @kb.add("end")
    def _bottom(event):
        offset[0] = max_offset

    def _get_content():
        visible = lines[offset[0]: offset[0] + content_height]
        # Pad with blank lines so the status bar doesn't jump when content
        # is shorter than the window.
        if len(visible) < content_height:
            visible = visible + [""] * (content_height - len(visible))
        return ANSI("\n".join(visible))

    def _get_status():
        end = min(offset[0] + content_height, total)
        pct = round(end / total * 100) if total else 100
        return (
            f"  ↑↓ j k  PgDn/PgUp  g/G top/bottom  q quit"
            f"        {offset[0] + 1}–{end} of {total}  ({pct}%)"
        )

    panes: list = []
    if header_height:
        panes.append(
            Window(
                content=FormattedTextControl(ANSI(header_ansi)),
                height=header_height,
                dont_extend_height=True,
            )
        )
    panes.append(
        Window(
            content=FormattedTextControl(_get_content),
            height=content_height,
            dont_extend_height=True,
        )
    )
    panes.append(
        Window(
            content=FormattedTextControl(_get_status),
            height=status_height,
            style="class:statusbar",
            dont_extend_height=True,
        )
    )

    app = Application(
        layout=Layout(HSplit(panes)),
        key_bindings=kb,
        full_screen=True,
        style=Style.from_dict({"statusbar": "reverse bold"}),
        mouse_support=False,
    )
    app.run()
