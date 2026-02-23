"""ZIA API router."""

from fastapi import APIRouter, HTTPException

from api.schemas.zia import UrlLookupRequest

router = APIRouter()


def _get_service(tenant_name: str):
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zia_service import ZIAService

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    client = ZIAClient(auth, tenant.oneapi_base_url)
    return ZIAService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Activation
# ------------------------------------------------------------------

@router.get("/{tenant}/activation/status")
def get_activation_status(tenant: str):
    """Get the current ZIA activation status."""
    return _get_service(tenant).get_activation_status()


@router.post("/{tenant}/activation/activate")
def activate(tenant: str):
    """Activate all pending ZIA configuration changes."""
    try:
        return _get_service(tenant).activate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories")
def list_url_categories(tenant: str):
    """List all URL categories (lite)."""
    return _get_service(tenant).list_url_categories()


@router.post("/{tenant}/url-lookup")
def url_lookup(tenant: str, req: UrlLookupRequest):
    """Look up category classifications for a list of URLs."""
    try:
        return _get_service(tenant).url_lookup(req.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Users / Locations
# ------------------------------------------------------------------

@router.get("/{tenant}/users")
def list_users(tenant: str, name: str = None):
    """List ZIA users, optionally filtered by name."""
    return _get_service(tenant).list_users(name=name)


@router.get("/{tenant}/locations")
def list_locations(tenant: str):
    """List ZIA locations (lite)."""
    return _get_service(tenant).list_locations()
