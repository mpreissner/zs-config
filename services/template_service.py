"""ZIA Template service.

A template is a sanitised ZIA snapshot with tenant-specific and reference-only
resource types stripped out.  Templates are global (not tied to any single tenant)
and can be applied to any target tenant via ZIAPushService.

Usage:
    from db.database import get_session
    from services.template_service import (
        create_template_from_snapshot,
        preview_template_from_snapshot,
        list_templates,
        get_template,
        delete_template,
    )

    with get_session() as session:
        tmpl = create_template_from_snapshot(
            snapshot_id=42,
            source_tenant_id=1,
            name="Corp Baseline Q2",
            description="Quarterly policy baseline",
            session=session,
        )
    # audit events must be written after the session closes (SQLite write-lock rule)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from db.models import RestorePoint, ZIATemplate


# Resource types stripped when creating a template.
# Includes both tenant-specific types (locations, VPN creds, etc.) and
# reference-only types that are not pushable.
TEMPLATE_STRIP_TYPES: set = {
    # Tenant-specific — encode public IPs, PSKs, or physical topology
    "location",
    "sublocation",
    "vpn_credential",
    "static_ip",
    "gre_tunnel",
    "pac_file",
    # Reference-only — imported for ID remapping; not pushable
    "location_lite",
    "location_group",
    "device_group",
    "network_app",
    "cloud_app_policy",
    "cloud_app_ssl_policy",
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    "cloud_app_instance",
}

# Human-readable reason strings for the stripped types (for preview display).
_STRIP_REASONS: Dict[str, str] = {
    "location":            "Encodes public IP addresses and VPN credential references",
    "sublocation":         "Child of a location; IP-topology-specific",
    "vpn_credential":      "Contains FQDN + pre-shared key unique to source network",
    "static_ip":           "Public IP registered with ZIA; unique to source network",
    "gre_tunnel":          "References source public IPs; entirely topology-specific",
    "pac_file":            "May reference internal hostnames or proxy IPs",
    "location_lite":       "Reference-only — imported for ID remapping, not pushable",
    "location_group":      "Reference-only — read-only in SDK",
    "device_group":        "Reference-only — predefined OS/platform groups",
    "network_app":         "Reference-only — system-defined, read-only",
    "cloud_app_policy":    "Reference data, not policy",
    "cloud_app_ssl_policy":"Reference data, not policy",
    "user":                "Identity data, not portable across tenants",
    "group":               "Identity data, not portable across tenants",
    "department":          "Identity data, not portable across tenants",
    "admin_user":          "Admin accounts are tenant-specific",
    "admin_role":          "Admin roles are tenant-specific",
    "cloud_app_instance":  "Reference-only — tenant-specific cloud app instance IDs",
}


def _strip_snapshot(
    resources: Dict[str, List[dict]],
) -> Tuple[Dict[str, List[dict]], List[str], List[str]]:
    """Separate portable from tenant-specific resources.

    Returns:
        (kept_resources, stripped_type_names, included_type_names)
    """
    kept: Dict[str, List[dict]] = {}
    stripped_types: List[str] = []
    included_types: List[str] = []

    for rtype, entries in resources.items():
        if rtype in TEMPLATE_STRIP_TYPES:
            stripped_types.append(rtype)
        else:
            kept[rtype] = entries
            included_types.append(rtype)

    return kept, sorted(stripped_types), sorted(included_types)


def _load_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    session: Session,
) -> RestorePoint:
    """Load and validate a ZIA RestorePoint."""
    snap = session.query(RestorePoint).filter_by(
        id=snapshot_id, tenant_id=source_tenant_id, product="ZIA"
    ).first()
    if snap is None:
        raise LookupError(f"ZIA snapshot {snapshot_id} not found for tenant {source_tenant_id}")
    return snap


def preview_template_from_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    session: Session,
) -> Dict:
    """Compute the included/stripped resource breakdown without writing to DB.

    Returns a dict suitable for the API preview response:
        {
            "included": [{"resource_type": str, "count": int}],
            "stripped": [{"resource_type": str, "count": int, "reason": str}],
        }
    """
    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    resources = snap.snapshot.get("resources", {})
    kept, stripped_types, included_types = _strip_snapshot(resources)

    included = [
        {"resource_type": rt, "count": len(kept.get(rt, []))}
        for rt in included_types
    ]
    stripped = []
    for rt in stripped_types:
        count = len(resources.get(rt, []))
        stripped.append({
            "resource_type": rt,
            "count": count,
            "reason": _STRIP_REASONS.get(rt, "Tenant-specific or reference-only"),
        })

    return {"included": included, "stripped": stripped}


def create_template_from_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    name: str,
    description: Optional[str],
    session: Session,
) -> ZIATemplate:
    """Create a ZIATemplate from an existing ZIA RestorePoint.

    Strips tenant-specific and reference-only resource types before saving.

    Raises:
        LookupError: Snapshot not found or not a ZIA snapshot for that tenant.
        ValueError: Template name already taken (409 equivalent).
        ValueError: No portable resources remain after stripping (422 equivalent).

    The caller is responsible for writing audit events AFTER the session closes
    (SQLite write-lock rule — do not call audit_service.log() inside this block).
    """
    # Check for duplicate name before loading the snapshot
    existing = session.query(ZIATemplate).filter_by(name=name).first()
    if existing is not None:
        raise ValueError(f"duplicate_name:A template with this name already exists")

    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    resources = snap.snapshot.get("resources", {})
    kept, stripped_types, _ = _strip_snapshot(resources)

    # Count portable resources
    resource_count = sum(len(v) for v in kept.values())
    if resource_count == 0:
        stripped_summary = ", ".join(stripped_types) if stripped_types else "all types"
        raise ValueError(
            f"no_portable_resources:Snapshot has no portable resources after stripping "
            f"tenant-specific types ({stripped_summary})"
        )

    now = datetime.utcnow()
    tmpl = ZIATemplate(
        name=name,
        description=description,
        source_tenant_id=source_tenant_id,
        source_snapshot_id=snapshot_id,
        created_at=now,
        updated_at=now,
        resource_count=resource_count,
        stripped_types=stripped_types,
        snapshot=kept,
    )
    session.add(tmpl)
    session.flush()   # populate tmpl.id without committing
    return tmpl


def list_templates(session: Session) -> List[ZIATemplate]:
    """Return all ZIATemplate rows, newest first."""
    return (
        session.query(ZIATemplate)
        .order_by(ZIATemplate.created_at.desc())
        .all()
    )


def get_template(template_id: int, session: Session) -> ZIATemplate:
    """Return a single ZIATemplate by ID.

    Raises:
        LookupError: Template not found.
    """
    tmpl = session.get(ZIATemplate, template_id)
    if tmpl is None:
        raise LookupError(f"Template {template_id} not found")
    return tmpl


def delete_template(template_id: int, session: Session) -> None:
    """Delete a ZIATemplate by ID.

    Raises:
        LookupError: Template not found.
    """
    tmpl = session.get(ZIATemplate, template_id)
    if tmpl is None:
        raise LookupError(f"Template {template_id} not found")
    session.delete(tmpl)
