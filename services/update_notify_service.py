"""Update notification service — checks PyPI daily and sends SMTP alert when a new version is available."""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

PYPI_URL = "https://pypi.org/pypi/zs-config/json"
CHANGELOG_URL = "https://github.com/mpreissner/zs-config/blob/main/CHANGELOG.md"
DEPLOY_ONELINER = "curl -fsSL https://raw.githubusercontent.com/mpreissner/zs-config/main/deploy.sh | bash"

_REQUEST_TIMEOUT = 5


def _parse_ver(v: str) -> tuple:
    v = v.lstrip("v")
    return tuple(int(x) for x in v.split("."))


def _fetch_latest_version() -> Optional[str]:
    try:
        import requests
        resp = requests.get(PYPI_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception:
        return None


def _send_email(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    to_addr: str,
    use_tls: bool,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr or username
    msg["To"] = to_addr
    msg.set_content(body)

    if use_tls:
        ctx = ssl.create_default_context()
        # Try STARTTLS first (port 587), fall back to implicit TLS (port 465)
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                if username:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ctx)
                if username:
                    s.login(username, password)
                s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            if username:
                s.login(username, password)
            s.send_message(msg)


def send_test_email(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    to_addr: str,
    use_tls: bool,
) -> None:
    """Send a test email to confirm SMTP settings work. Raises on failure."""
    from cli.banner import VERSION
    _send_email(
        host=host,
        port=port,
        username=username,
        password=password,
        from_addr=from_addr,
        to_addr=to_addr,
        use_tls=use_tls,
        subject="zs-config: SMTP test",
        body=(
            f"SMTP is configured correctly for zs-config.\n\n"
            f"Running version: v{VERSION}\n\n"
            f"You will receive a message like this when a new version is available."
        ),
    )


def check_and_notify() -> None:
    """Check PyPI for a new version and send an email alert if one is found and notifications are enabled."""
    from db.database import get_setting
    from cli.banner import VERSION

    if get_setting("update_notify_enabled") != "true":
        return

    to_addr = get_setting("update_notify_email") or ""
    host = get_setting("smtp_host") or ""
    if not to_addr or not host:
        return

    latest = _fetch_latest_version()
    if latest is None:
        return

    try:
        if _parse_ver(latest) <= _parse_ver(VERSION):
            return
    except Exception:
        return

    try:
        port = int(get_setting("smtp_port") or "587")
    except ValueError:
        port = 587

    username = get_setting("smtp_username") or ""
    password = get_setting("smtp_password") or ""
    from_addr = get_setting("smtp_from_address") or username
    use_tls = get_setting("smtp_tls") != "false"

    body = (
        f"A new version of zs-config is available.\n\n"
        f"  Current version : v{VERSION}\n"
        f"  Latest version  : v{latest}\n\n"
        f"To update, re-run the deployment script on your Docker host:\n\n"
        f"  {DEPLOY_ONELINER}\n\n"
        f"Or, if you already have the repo cloned:\n\n"
        f"  ./deploy.sh main\n\n"
        f"Changelog: {CHANGELOG_URL}\n"
    )

    try:
        _send_email(
            host=host,
            port=port,
            username=username,
            password=password,
            from_addr=from_addr,
            to_addr=to_addr,
            use_tls=use_tls,
            subject=f"zs-config update available: v{VERSION} → v{latest}",
            body=body,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Update notification email failed: %s", exc)
