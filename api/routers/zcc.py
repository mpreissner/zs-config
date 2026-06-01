"""ZCC API router."""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()

# Password fields that must never appear in API responses or audit entries.
_PASSWORD_FIELDS = {
    "exitPassword", "zdxDisablePassword", "zdDisablePassword",
    "zpaDisablePassword", "zdpDisablePassword",
}


def _strip_passwords(obj: Any) -> Any:
    """Recursively remove password fields from a dict/list."""
    if isinstance(obj, dict):
        return {k: _strip_passwords(v) for k, v in obj.items() if k not in _PASSWORD_FIELDS}
    if isinstance(obj, list):
        return [_strip_passwords(i) for i in obj]
    return obj


def _derive_tunnel_mode(raw_fp: Optional[Dict]) -> str:
    """Derive tunnel mode string from forwarding profile raw_config."""
    if not raw_fp:
        return "Unknown"
    actions = raw_fp.get("forwardingProfileActions") or []
    if not actions:
        return "Unknown"
    first = actions[0] if isinstance(actions[0], dict) else {}
    if first.get("enablePacketTunnel") is True or first.get("enablePacketTunnel") == "true":
        return "Z-Tunnel 2.0"
    primary = first.get("primaryTransport", "")
    if primary == "PROXY" or first.get("systemProxy") is True:
        return "Proxy"
    return "Z-Tunnel 1.0"


def _extract_process_bypasses(raw_policy: Dict) -> List[Dict]:
    """Extract per-OS process-based bypass entries from a web_policy raw_config."""
    platform_keys = {
        "windowsPolicy": "windows",
        "macPolicy": "macos",
        "macosPolicy": "macos",
        "linuxPolicy": "linux",
        "iosPolicy": "ios",
        "androidPolicy": "android",
    }
    bypasses = []
    for pol_key, platform in platform_keys.items():
        sub = raw_policy.get(pol_key)
        if not isinstance(sub, dict):
            continue
        for field_name, field_val in sub.items():
            if "bypass" not in field_name.lower():
                continue
            items = field_val if isinstance(field_val, list) else [field_val]
            for item in items:
                if isinstance(item, dict):
                    proc = item.get("processName") or item.get("process_name") or item.get("name") or str(item)
                    bypasses.append({"processName": proc, "platform": platform})
                elif isinstance(item, str) and item:
                    bypasses.append({"processName": item, "platform": platform})
    return bypasses


def _build_traffic_profile(
    raw_policy: Dict,
    raw_fp: Optional[Dict],
    zia_pac_file_id: Optional[int] = None,
    zia_pac_file_name: Optional[str] = None,
    predefined_ip_bypasses: Optional[List[Dict]] = None,
    custom_ip_bypasses: Optional[List[Dict]] = None,
    app_service_bypasses: Optional[List[Dict]] = None,
) -> Dict:
    """Pure function: build a TrafficProfile dict from two raw_config dicts."""
    pe = raw_policy.get("policyExtension") or {}

    # Forwarding profile info
    fp_name = raw_fp.get("name") if raw_fp else None
    fp_id = str(raw_policy.get("forwardingProfileId", "")) or None
    tunnel_mode = _derive_tunnel_mode(raw_fp)

    # PAC config
    pac_url = raw_policy.get("pac_url") or raw_policy.get("pacUrl") or None
    fp_pac_url = None
    enable_pac = False
    custom_pac_len = None
    if raw_fp:
        actions = raw_fp.get("forwardingProfileActions") or []
        if actions and isinstance(actions[0], dict):
            first = actions[0]
            spd = first.get("systemProxyData") or {}
            fp_pac_url = spd.get("pacURL") or None
            enable_pac = bool(spd.get("enablePAC"))
            custom_pac = first.get("customPac")
            if custom_pac:
                custom_pac_len = len(str(custom_pac))

    pac = {
        "url": pac_url,
        "profilePacUrl": fp_pac_url,
        "customPacContent": custom_pac_len,
        "enablePac": enable_pac,
        "ziaPacFileId": zia_pac_file_id,
        "ziaPacFileName": zia_pac_file_name,
    }

    # Port bypasses
    port_bypasses = []
    for pb in (pe.get("sourcePortBasedBypasses") or []):
        if isinstance(pb, dict):
            port_bypasses.append({
                "port": str(pb.get("port", "")),
                "protocol": str(pb.get("protocol", pb.get("proto", ""))),
            })

    # VPN gateway bypasses
    vpn_bypasses = []
    for gw in (pe.get("vpnGateways") or []):
        if isinstance(gw, str):
            vpn_bypasses.append({"gateway": gw})
        elif isinstance(gw, dict):
            vpn_bypasses.append({"gateway": gw.get("gateway") or gw.get("domain") or str(gw)})

    # Tunnel routes (IPv4 + IPv6)
    tunnel_routes = []
    for cidr in (pe.get("packetTunnelIncludeList") or []):
        tunnel_routes.append({"cidr": cidr, "direction": "include", "ipVersion": "ipv4"})
    for cidr in (pe.get("packetTunnelExcludeList") or []):
        tunnel_routes.append({"cidr": cidr, "direction": "exclude", "ipVersion": "ipv4"})
    for cidr in (pe.get("packetTunnelIncludeListForIPv6") or []):
        tunnel_routes.append({"cidr": cidr, "direction": "include", "ipVersion": "ipv6"})
    for cidr in (pe.get("packetTunnelExcludeListForIPv6") or []):
        tunnel_routes.append({"cidr": cidr, "direction": "exclude", "ipVersion": "ipv6"})

    # DNS routes
    dns_routes = []
    for suffix in (pe.get("packetTunnelDnsIncludeList") or []):
        dns_routes.append({"suffix": suffix, "direction": "include"})
    for suffix in (pe.get("packetTunnelDnsExcludeList") or []):
        dns_routes.append({"suffix": suffix, "direction": "exclude"})

    # Process bypasses extracted from platform sub-policies
    process_bypasses = _extract_process_bypasses(raw_policy)

    # Trusted networks from forwarding profile
    trusted_networks: List[str] = []
    if raw_fp:
        trusted_networks = raw_fp.get("trustedNetworks") or []

    # Strip password fields from rawPolicySnippet
    raw_snippet = _strip_passwords(pe)

    # Forwarding profile raw snippet
    raw_fp_snippet = _strip_passwords(raw_fp) if raw_fp else None

    return {
        "policyId": str(raw_policy.get("id", "")),
        "policyName": raw_policy.get("name", ""),
        "active": bool(raw_policy.get("active")),
        "tunnelMode": tunnel_mode,
        "forwardingProfileName": fp_name,
        "forwardingProfileId": fp_id,
        "pac": pac,
        "processBypasses": process_bypasses,
        "portBypasses": port_bypasses,
        "vpnGatewayBypasses": vpn_bypasses,
        "predefinedIpBypasses": predefined_ip_bypasses or [],
        "customIpBypasses": custom_ip_bypasses or [],
        "appServiceBypasses": app_service_bypasses or [],
        "tunnelRoutes": tunnel_routes,
        "dnsRoutes": dns_routes,
        "tunnelZappTraffic": bool(raw_policy.get("tunnelZappTraffic")),
        "trustedNetworks": trusted_networks,
        "rawPolicySnippet": raw_snippet,
        "rawForwardingSnippet": raw_fp_snippet,
    }


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
# Configuration resources — DB-first reads
# ------------------------------------------------------------------

def _db_resources(tenant_name: str, user: AuthUser, resource_type: str) -> List[Dict]:
    """Return raw_config dicts from ZCCResource for the given resource_type."""
    from db.database import get_session
    from db.models import ZCCResource
    from api.dependencies import check_tenant_access
    from services.config_service import get_tenant as _get_tenant

    t = _get_tenant(tenant_name)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(t.id, user)

    with get_session() as session:
        rows = (
            session.query(ZCCResource)
            .filter_by(tenant_id=t.id, resource_type=resource_type, is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        return [row.raw_config for row in rows if row.raw_config]


def _normalize_name(record: Dict, *candidate_keys: str) -> Dict:
    """Add a 'name' key from the first non-empty candidate field, if not already present."""
    if record.get("name"):
        return record
    for key in candidate_keys:
        val = record.get(key)
        if val:
            return {**record, "name": val}
    return record


@router.get("/{tenant}/trusted-networks")
def list_trusted_networks(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "trusted_network")
    return [_normalize_name(r, "networkName") for r in rows]


@router.get("/{tenant}/forwarding-profiles")
def list_forwarding_profiles(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "forwarding_profile")


@router.get("/{tenant}/web-policies")
def list_web_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "web_policy")


@router.get("/{tenant}/web-app-services")
def list_web_app_services(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "web_app_service")
    return [_normalize_name(r, "appName") for r in rows]


@router.get("/{tenant}/admin-roles")
def list_admin_roles(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "admin_role")
    return [_normalize_name(r, "roleName") for r in rows]


@router.get("/{tenant}/fail-open-policies")
def list_fail_open_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "fail_open_policy")


@router.get("/{tenant}/web-privacy")
def get_web_privacy(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "web_privacy")
    return rows[0] if rows else {}


@router.get("/{tenant}/ip-apps/predefined")
def list_ip_apps_predefined(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "ip_app_predefined")
    return [_normalize_name(r, "appName") for r in rows]


@router.get("/{tenant}/ip-apps/custom")
def list_ip_apps_custom(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "ip_app_custom")
    return [_normalize_name(r, "appName") for r in rows]


@router.get("/{tenant}/process-apps")
def list_process_apps(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "process_app")
    return [_normalize_name(r, "appName") for r in rows]


# ------------------------------------------------------------------
# Traffic Profile
# ------------------------------------------------------------------

@router.get("/{tenant}/traffic-profile/{policy_id}")
def get_traffic_profile(
    tenant: str,
    policy_id: str,
    user: AuthUser = Depends(require_auth),
):
    from db.database import get_session
    from db.models import ZCCResource, ZIAResource
    from api.dependencies import check_tenant_access
    from services.config_service import get_tenant as _get_tenant

    t = _get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    with get_session() as session:
        policy_row = (
            session.query(ZCCResource)
            .filter_by(tenant_id=t.id, resource_type="web_policy",
                       zcc_id=policy_id, is_deleted=False)
            .first()
        )
        if not policy_row:
            raise HTTPException(status_code=404, detail="App profile not found")

        raw_policy = policy_row.raw_config or {}
        fp_id = str(raw_policy.get("forwardingProfileId", ""))
        fp_row = None
        if fp_id:
            fp_row = (
                session.query(ZCCResource)
                .filter_by(tenant_id=t.id, resource_type="forwarding_profile",
                           zcc_id=fp_id, is_deleted=False)
                .first()
            )
        raw_fp = fp_row.raw_config if fp_row else None

        # Cross-reference PAC URL against ZIA pac_file resources
        pac_url = raw_policy.get("pac_url") or raw_policy.get("pacUrl") or ""
        zia_pac_file_id = None
        zia_pac_file_name = None
        if pac_url:
            zia_pac_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=t.id, resource_type="pac_file", is_deleted=False)
                .all()
            )
            for pac_row in zia_pac_rows:
                rc = pac_row.raw_config or {}
                row_url = rc.get("pac_url") or rc.get("pacUrl") or rc.get("url") or ""
                if row_url and row_url == pac_url:
                    zia_pac_file_id = pac_row.zia_id
                    zia_pac_file_name = pac_row.name
                    break

        # Resolve bypassAppIds → ip_app_predefined DB records
        bypass_app_ids = {str(i) for i in (raw_policy.get("bypassAppIds") or [])}
        bypass_custom_ids = {str(i) for i in (raw_policy.get("bypassCustomAppIds") or [])}
        app_service_ids = {str(i) for i in (raw_policy.get("appServiceIds") or [])}

        def _resolve_ip_apps(resource_type: str, id_set: set, source: str) -> List[Dict]:
            if not id_set:
                return []
            rows = (
                session.query(ZCCResource)
                .filter(
                    ZCCResource.tenant_id == t.id,
                    ZCCResource.resource_type == resource_type,
                    ZCCResource.is_deleted == False,  # noqa: E712
                    ZCCResource.zcc_id.in_(id_set),
                )
                .all()
            )
            result = []
            for row in rows:
                rc = row.raw_config or {}
                blob = rc.get("appDataBlob") or []
                blob_v6 = rc.get("appDataBlobV6") or []
                result.append({
                    "id": row.zcc_id,
                    "appName": rc.get("appName") or row.name or row.zcc_id,
                    "cidrs": blob if isinstance(blob, list) else [blob],
                    "cidrsV6": blob_v6 if isinstance(blob_v6, list) else [blob_v6],
                    "source": source,
                })
            return result

        predefined_ip_bypasses = _resolve_ip_apps("ip_app_predefined", bypass_app_ids, "predefined")
        custom_ip_bypasses = _resolve_ip_apps("ip_app_custom", bypass_custom_ids, "custom")

        app_service_bypasses: List[Dict] = []
        if app_service_ids:
            svc_rows = (
                session.query(ZCCResource)
                .filter(
                    ZCCResource.tenant_id == t.id,
                    ZCCResource.resource_type == "web_app_service",
                    ZCCResource.is_deleted == False,  # noqa: E712
                    ZCCResource.zcc_id.in_(app_service_ids),
                )
                .all()
            )
            for row in svc_rows:
                rc = row.raw_config or {}
                proc_names = rc.get("processNames") or rc.get("appProcessNames") or []
                app_service_bypasses.append({
                    "id": row.zcc_id,
                    "appName": rc.get("appName") or row.name or row.zcc_id,
                    "processNames": proc_names if isinstance(proc_names, list) else [proc_names],
                })

    return _build_traffic_profile(
        raw_policy, raw_fp, zia_pac_file_id, zia_pac_file_name,
        predefined_ip_bypasses, custom_ip_bypasses, app_service_bypasses,
    )
