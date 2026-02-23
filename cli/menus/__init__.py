"""Shared helpers for CLI menus — tenant selection and client factory."""

from typing import Optional, Tuple

import questionary
from rich.console import Console

console = Console()


def select_tenant():
    """Prompt the user to select a tenant. Returns None if none are configured."""
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print(
            "[yellow]No tenants configured.[/yellow] "
            "Go to [bold]Settings → Manage Tenants → Add Tenant[/bold] first."
        )
        return None
    if len(tenants) == 1:
        return tenants[0]
    return questionary.select(
        "Select tenant:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()


def get_zpa_client(tenant=None):
    """Return (ZPAClient, tenant) or (None, None) if setup is incomplete."""
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None
    if not tenant.zpa_customer_id:
        console.print(f"[red]Tenant '{tenant.name}' has no ZPA Customer ID configured.[/red]")
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZPAClient(auth, tenant.zpa_customer_id, tenant.oneapi_base_url), tenant


def get_zia_client(tenant=None):
    """Return (ZIAClient, tenant) or (None, None) if setup is incomplete."""
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZIAClient(auth, tenant.oneapi_base_url), tenant
