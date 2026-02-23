"""ZPA API router.

Each endpoint resolves a tenant, builds the ZPA client, and delegates to
the ZPAService layer — the same layer used by the CLI and headless scripts.
"""

from fastapi import APIRouter, HTTPException

from api.schemas.zpa import CertificateRotateRequest

router = APIRouter()


def _get_service(tenant_name: str):
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zpa_service import ZPAService

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    if not tenant.zpa_customer_id:
        raise HTTPException(status_code=400, detail=f"Tenant '{tenant_name}' has no ZPA Customer ID")

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    client = ZPAClient(auth, tenant.zpa_customer_id, tenant.oneapi_base_url)
    return ZPAService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Certificates
# ------------------------------------------------------------------

@router.get("/{tenant}/certificates")
def list_certificates(tenant: str):
    """List all certificates for a ZPA tenant."""
    return _get_service(tenant).list_certificates()


@router.delete("/{tenant}/certificates/{cert_id}")
def delete_certificate(tenant: str, cert_id: str):
    """Delete a certificate by ID."""
    success = _get_service(tenant).delete_certificate(cert_id)
    return {"deleted": success}


@router.post("/{tenant}/certificates/rotate")
def rotate_certificate(tenant: str, req: CertificateRotateRequest):
    """Rotate a certificate for a domain.

    Uploads the new cert, updates all matching Browser Access apps and PRA
    portals, then deletes the old cert if no longer referenced.
    """
    try:
        result = _get_service(tenant).rotate_certificate(
            req.cert_path, req.key_path, req.domain
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Applications
# ------------------------------------------------------------------

@router.get("/{tenant}/applications")
def list_applications(tenant: str, app_type: str = "BROWSER_ACCESS"):
    """List application segments, optionally filtered by type."""
    return _get_service(tenant).list_applications(app_type)


# ------------------------------------------------------------------
# PRA Portals
# ------------------------------------------------------------------

@router.get("/{tenant}/pra-portals")
def list_pra_portals(tenant: str):
    """List all PRA portals."""
    return _get_service(tenant).list_pra_portals()
