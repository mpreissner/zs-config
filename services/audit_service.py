"""Audit logging service.

Every operation performed through this toolset is recorded here, providing:
  - Compliance trail for change management
  - Troubleshooting history (what changed, when, by which tenant)
  - Redeployment reference (query the log to reconstruct what was applied)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from db.database import get_session
from db.models import AuditLog


def log(
    product: str,
    operation: str,
    action: str,
    status: str,
    tenant_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Write an audit log entry. Fire-and-forget — errors are silently swallowed
    so a logging failure never breaks the operation being audited."""
    try:
        with get_session() as session:
            entry = AuditLog(
                tenant_id=tenant_id,
                timestamp=datetime.utcnow(),
                product=product,
                operation=operation,
                action=action,
                status=status,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                resource_name=str(resource_name) if resource_name else None,
                details=details,
                error_message=error_message,
            )
            session.add(entry)
    except Exception:
        pass  # Never let audit failures surface to the caller


def get_recent(
    tenant_id: Optional[int] = None,
    product: Optional[str] = None,
    limit: int = 100,
) -> List[AuditLog]:
    """Return recent audit log entries, newest first."""
    with get_session() as session:
        q = session.query(AuditLog)
        if tenant_id is not None:
            q = q.filter(AuditLog.tenant_id == tenant_id)
        if product is not None:
            q = q.filter(AuditLog.product == product)
        return q.order_by(AuditLog.timestamp.desc()).limit(limit).all()


def get_by_resource(
    resource_type: str,
    resource_id: str,
    tenant_id: Optional[int] = None,
) -> List[AuditLog]:
    """Return all log entries for a specific resource (e.g. a certificate ID)."""
    with get_session() as session:
        q = session.query(AuditLog).filter(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == resource_id,
        )
        if tenant_id is not None:
            q = q.filter(AuditLog.tenant_id == tenant_id)
        return q.order_by(AuditLog.timestamp.desc()).all()
