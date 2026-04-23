"""ZIA API router."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.schemas.zia import UrlLookupRequest
from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zia_service import ZIAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

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
def get_activation_status(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the current ZIA activation status."""
    return _get_service(tenant, user).get_activation_status()


@router.post("/{tenant}/activation/activate")
def activate(tenant: str, user: AuthUser = Depends(require_admin)):
    """Activate all pending ZIA configuration changes."""
    try:
        return _get_service(tenant, user).activate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories")
def list_url_categories(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL categories (lite)."""
    return _get_service(tenant, user).list_url_categories()


@router.post("/{tenant}/url-lookup")
def url_lookup(tenant: str, req: UrlLookupRequest, user: AuthUser = Depends(require_auth)):
    """Look up category classifications for a list of URLs."""
    try:
        return _get_service(tenant, user).url_lookup(req.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Filtering Rules
# ------------------------------------------------------------------

@router.get("/{tenant}/url-filtering-rules")
def list_url_filtering_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL filtering rules."""
    return _get_service(tenant, user).list_url_filtering_rules()


# ------------------------------------------------------------------
# Users / Locations / Departments / Groups
# ------------------------------------------------------------------

@router.get("/{tenant}/users")
def list_users(tenant: str, name: str = None, user: AuthUser = Depends(require_auth)):
    """List ZIA users, optionally filtered by name."""
    return _get_service(tenant, user).list_users(name=name)


@router.get("/{tenant}/locations")
def list_locations(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA locations (lite)."""
    return _get_service(tenant, user).list_locations()


@router.get("/{tenant}/departments")
def list_departments(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA departments."""
    return _get_service(tenant, user).list_departments()


@router.get("/{tenant}/groups")
def list_groups(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA groups."""
    return _get_service(tenant, user).list_groups()


# ------------------------------------------------------------------
# Allow / Deny Lists
# ------------------------------------------------------------------

@router.get("/{tenant}/allowlist")
def get_allowlist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA allowlist (whitelist URLs)."""
    return _get_service(tenant, user).get_allowlist()


@router.get("/{tenant}/denylist")
def get_denylist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA denylist (blacklist URLs)."""
    return _get_service(tenant, user).get_denylist()


class AllowlistUpdateRequest(BaseModel):
    whitelistUrls: List[str]


class DenylistUpdateRequest(BaseModel):
    blacklistUrls: List[str]


@router.put("/{tenant}/allowlist")
def update_allowlist(tenant: str, body: AllowlistUpdateRequest, user: AuthUser = Depends(require_admin)):
    """Replace the ZIA allowlist."""
    try:
        return _get_service(tenant, user).update_allowlist(body.whitelistUrls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/denylist")
def update_denylist(tenant: str, body: DenylistUpdateRequest, user: AuthUser = Depends(require_admin)):
    """Replace the ZIA denylist."""
    try:
        return _get_service(tenant, user).update_denylist(body.blacklistUrls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories — CRUD
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories/{category_id}")
def get_url_category(tenant: str, category_id: str, user: AuthUser = Depends(require_auth)):
    """Get a single URL category by ID."""
    try:
        return _get_service(tenant, user).get_url_category(category_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/url-categories")
def create_url_category(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Create a custom URL category."""
    try:
        return _get_service(tenant, user).create_url_category(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/url-categories/{category_id}")
def update_url_category(tenant: str, category_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Update a custom URL category."""
    try:
        return _get_service(tenant, user).update_url_category(category_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Filtering Rules — CRUD + state toggle
# ------------------------------------------------------------------

@router.post("/{tenant}/url-filtering-rules")
def create_url_filtering_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Create a URL filtering rule."""
    try:
        return _get_service(tenant, user).create_url_filtering_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/url-filtering-rules/{rule_id}")
def update_url_filtering_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Update a URL filtering rule."""
    try:
        return _get_service(tenant, user).update_url_filtering_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/url-filtering-rules/{rule_id}")
def delete_url_filtering_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_admin)):
    """Delete a URL filtering rule."""
    try:
        _get_service(tenant, user).delete_url_filtering_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RuleStateRequest(BaseModel):
    state: str


@router.patch("/{tenant}/url-filtering-rules/{rule_id}/state")
def patch_url_filtering_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_admin)
):
    """Toggle the enabled/disabled state of a URL filtering rule."""
    try:
        svc = _get_service(tenant, user)
        from lib.zia_client import ZIAClient as _ZIAClient  # noqa: F401 — ensure client is importable
        rule = svc.client.get_url_filtering_rule(rule_id) if hasattr(svc, "client") else {}
        rule["state"] = body.state
        return svc.update_url_filtering_rule(rule_id, rule)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# ZIA Users — CRUD
# ------------------------------------------------------------------

@router.get("/{tenant}/users/{user_id}")
def get_zia_user(tenant: str, user_id: str, user: AuthUser = Depends(require_auth)):
    """Get a single ZIA user by ID."""
    try:
        return _get_service(tenant, user).get_user(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/users")
def create_zia_user(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Create a ZIA user."""
    try:
        return _get_service(tenant, user).create_user(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/users/{user_id}")
def update_zia_user(tenant: str, user_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_admin)):
    """Update a ZIA user."""
    try:
        return _get_service(tenant, user).update_user(user_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/users/{user_id}")
def delete_zia_user(tenant: str, user_id: str, user: AuthUser = Depends(require_admin)):
    """Delete a ZIA user."""
    try:
        _get_service(tenant, user).delete_user(user_id)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
