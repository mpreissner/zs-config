"""Terraform export endpoints — generate .tf files from imported ZIA / ZPA config."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.dependencies import AuthUser, check_tenant_access, require_user
from db.database import get_session
from db.models import TenantConfig

router = APIRouter(prefix="/api/v1/tenants", tags=["Terraform"])


def _check_access(tenant_id: int, user: AuthUser) -> str:
    """Verify access and return the tenant name."""
    check_tenant_access(tenant_id, user)
    with get_session() as session:
        t = session.get(TenantConfig, tenant_id)
        if not t or not t.is_active:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return t.name


def _tf_response(hcl: str, tenant_name: str, product: str) -> Response:
    from services.terraform_export_service import _slug

    return Response(
        content=hcl,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{_slug(tenant_name)}_{product}.tf"'
        },
    )


@router.get("/{tenant_id}/terraform/zia")
def export_terraform_zia(tenant_id: int, user: AuthUser = Depends(require_user)):
    from services.terraform_export_service import generate_zia

    tenant_name = _check_access(tenant_id, user)
    return _tf_response(generate_zia(tenant_id), tenant_name, "zia")


@router.get("/{tenant_id}/terraform/zpa")
def export_terraform_zpa(tenant_id: int, user: AuthUser = Depends(require_user)):
    from services.terraform_export_service import generate_zpa

    tenant_name = _check_access(tenant_id, user)
    return _tf_response(generate_zpa(tenant_id), tenant_name, "zpa")
