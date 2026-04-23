"""ZCC API router."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zcc_client import ZCCClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zcc_service import ZCCService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
        govcloud=bool(tenant.govcloud),
    )
    client = ZCCClient(auth, tenant.oneapi_base_url, tenant.zia_cloud, tenant.zia_tenant_id)
    return ZCCService(client, tenant_id=tenant.id)


class DeviceRemoveRequest(BaseModel):
    udids: List[str]
    os_type: int


# ------------------------------------------------------------------
# Devices
# ------------------------------------------------------------------

@router.get("/{tenant}/devices")
def list_devices(
    tenant: str,
    username: Optional[str] = None,
    os_type: Optional[int] = None,
    page_size: int = 500,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.list_devices(username=username, os_type=os_type, page_size=page_size)


@router.delete("/{tenant}/devices/remove")
def remove_devices(
    tenant: str,
    body: DeviceRemoveRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.remove_device(udid_list=body.udids, os_type=body.os_type)


@router.delete("/{tenant}/devices/force-remove")
def force_remove_devices(
    tenant: str,
    body: DeviceRemoveRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.force_remove_device(udid_list=body.udids, os_type=body.os_type)


@router.get("/{tenant}/devices/otp/{udid}")
def get_device_otp(
    tenant: str,
    udid: str,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.get_otp(udid=udid)


# ------------------------------------------------------------------
# Configuration resources
# ------------------------------------------------------------------

@router.get("/{tenant}/trusted-networks")
def list_trusted_networks(tenant: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_trusted_networks()


@router.get("/{tenant}/forwarding-profiles")
def list_forwarding_profiles(tenant: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_forwarding_profiles()


@router.get("/{tenant}/web-policies")
def list_web_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_web_policies()


@router.get("/{tenant}/web-app-services")
def list_web_app_services(tenant: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_web_app_services()
