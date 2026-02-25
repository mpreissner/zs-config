"""ZPA Application Segment service.

Business logic for listing, searching, creating, and bulk-importing
application segments. No CLI concerns — returns plain data structures.
"""

import csv
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from db.database import get_session
from db.models import ZPAResource
from services import audit_service


# ---------------------------------------------------------------------------
# CSV template rows (minimal + full)
# ---------------------------------------------------------------------------

TEMPLATE_ROWS = [
    {
        "name": "MyApp-Minimal",
        "domain_names": "app.example.com;api.example.com",
        "segment_group": "My Segment Group",
        "server_groups": "My Server Group",
        "tcp_ports": "443",
        "udp_ports": "",
        "description": "",
        "enabled": "true",
        "app_type": "BROWSER_ACCESS",
        "bypass_type": "NEVER",
        "double_encrypt": "false",
        "health_check_type": "DEFAULT",
        "health_reporting": "ON_ACCESS",
        "icmp_access_type": "NONE",
        "passive_health_enabled": "true",
        "is_cname_enabled": "true",
        "select_connector_close_to_app": "false",
    },
    {
        "name": "MyApp-Full",
        "domain_names": "full.example.com;*.full.example.com",
        "segment_group": "My Segment Group",
        "server_groups": "Server Group A;Server Group B",
        "tcp_ports": "80;443;8080-8090",
        "udp_ports": "53",
        "description": "Full example row with all columns",
        "enabled": "true",
        "app_type": "BROWSER_ACCESS",
        "bypass_type": "NEVER",
        "double_encrypt": "false",
        "health_check_type": "DEFAULT",
        "health_reporting": "ON_ACCESS",
        "icmp_access_type": "NONE",
        "passive_health_enabled": "true",
        "is_cname_enabled": "true",
        "select_connector_close_to_app": "false",
    },
]

CSV_FIELDNAMES = list(TEMPLATE_ROWS[0].keys())

# Required columns — rows missing these (or blank) fail validation
_REQUIRED = {"name", "domain_names", "segment_group", "server_groups"}


# ---------------------------------------------------------------------------
# BulkCreateResult
# ---------------------------------------------------------------------------

@dataclass
class BulkCreateResult:
    created: int = 0
    failed: int = 0
    skipped: int = 0
    rows_detail: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv(path: str) -> List[Dict]:
    """Read and validate a CSV file of application segment rows.

    Returns a list of row dicts.  Raises ValueError if any required fields
    are missing or both tcp_ports and udp_ports are blank.
    """
    errors: List[str] = []
    rows: List[Dict] = []

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):  # row 1 = header
            row_errors = []

            for col in _REQUIRED:
                if not row.get(col, "").strip():
                    row_errors.append(f"'{col}' is required")

            if not row.get("tcp_ports", "").strip() and not row.get("udp_ports", "").strip():
                row_errors.append("at least one of 'tcp_ports' or 'udp_ports' must be non-empty")

            if row_errors:
                name = row.get("name", f"row {i}")
                errors.append(f"Row {i} ({name!r}): {'; '.join(row_errors)}")
            else:
                rows.append(dict(row))

    if errors:
        raise ValueError("CSV validation failed:\n" + "\n".join(errors))

    return rows


# ---------------------------------------------------------------------------
# Port parsing
# ---------------------------------------------------------------------------

def _parse_ports(port_str: str) -> List[Dict[str, str]]:
    """Convert a port string to SDK-compatible port range dicts.

    Examples:
        "80"               → [{"from": "80",   "to": "80"}]
        "8080-8090"        → [{"from": "8080", "to": "8090"}]
        "80;443;8080-8090" → [{"from": "80", "to": "80"},
                               {"from": "443", "to": "443"},
                               {"from": "8080", "to": "8090"}]
    """
    if not port_str or not port_str.strip():
        return []
    result = []
    for entry in port_str.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "-" in entry:
            parts = entry.split("-", 1)
            result.append({"from": parts[0].strip(), "to": parts[1].strip()})
        else:
            result.append({"from": entry, "to": entry})
    return result


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

def resolve_dependencies(
    tenant_id: int,
    rows: List[Dict],
) -> Tuple[List[Dict], Dict[str, List[str]]]:
    """Look up segment_group and server_group IDs from the local DB cache.

    Returns (rows_with_ids, missing) where:
      - rows_with_ids: input rows annotated with '_segment_group_id' and
        '_server_group_ids' keys when found
      - missing: {"segment_group": [...names...], "server_group": [...names...]}
    """
    missing: Dict[str, List[str]] = {"segment_group": [], "server_group": []}

    # Collect all unique names to resolve
    seg_group_names = {r["segment_group"].strip() for r in rows}
    srv_group_names: set = set()
    for r in rows:
        for sg in r["server_groups"].split(";"):
            sg = sg.strip()
            if sg:
                srv_group_names.add(sg)

    seg_group_map: Dict[str, str] = {}
    srv_group_map: Dict[str, str] = {}

    with get_session() as session:
        for name in seg_group_names:
            rec = (
                session.query(ZPAResource)
                .filter_by(
                    tenant_id=tenant_id,
                    resource_type="segment_group",
                    name=name,
                    is_deleted=False,
                )
                .first()
            )
            if rec:
                seg_group_map[name] = rec.zpa_id
            elif name not in missing["segment_group"]:
                missing["segment_group"].append(name)

        for name in srv_group_names:
            rec = (
                session.query(ZPAResource)
                .filter_by(
                    tenant_id=tenant_id,
                    resource_type="server_group",
                    name=name,
                    is_deleted=False,
                )
                .first()
            )
            if rec:
                srv_group_map[name] = rec.zpa_id
            elif name not in missing["server_group"]:
                missing["server_group"].append(name)

    # Annotate rows with resolved IDs
    enriched: List[Dict] = []
    for row in rows:
        r = dict(row)
        sg_name = row["segment_group"].strip()
        r["_segment_group_id"] = seg_group_map.get(sg_name)

        srv_ids = []
        for sg in row["server_groups"].split(";"):
            sg = sg.strip()
            if sg and sg in srv_group_map:
                srv_ids.append(srv_group_map[sg])
        r["_server_group_ids"] = srv_ids
        enriched.append(r)

    return enriched, missing


# ---------------------------------------------------------------------------
# Create missing groups
# ---------------------------------------------------------------------------

def create_missing_groups(client, tenant_id: int, missing: Dict[str, List[str]]) -> Dict:
    """Create missing segment groups and/or server groups via the API.

    Returns {"created": [...], "failed": [...], "warnings": [...]}
    """
    created: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    for name in missing.get("segment_group", []):
        try:
            result = client.create_segment_group(name=name, enabled=True)
            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="SUCCESS",
                tenant_id=tenant_id,
                resource_type="segment_group",
                resource_id=str(result.get("id", "")),
                resource_name=name,
            )
            created.append(f"segment_group:{name}")
        except Exception as exc:
            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="FAILURE",
                tenant_id=tenant_id,
                resource_type="segment_group",
                resource_name=name,
                error_message=str(exc),
            )
            failed.append(f"segment_group:{name} — {exc}")

    for name in missing.get("server_group", []):
        try:
            result = client.create_server_group(name=name, enabled=True)
            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="SUCCESS",
                tenant_id=tenant_id,
                resource_type="server_group",
                resource_id=str(result.get("id", "")),
                resource_name=name,
            )
            created.append(f"server_group:{name}")
            warnings.append(
                f"'{name}' created with no connector groups — assign in the ZPA portal."
            )
        except Exception as exc:
            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="FAILURE",
                tenant_id=tenant_id,
                resource_type="server_group",
                resource_name=name,
                error_message=str(exc),
            )
            failed.append(f"server_group:{name} — {exc}")

    # Re-sync segment_group and server_group from API into local DB cache
    if created:
        from services.zpa_import_service import ZPAImportService
        ZPAImportService(client, tenant_id).run(
            resource_types=["segment_group", "server_group"]
        )

    return {"created": created, "failed": failed, "warnings": warnings}


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def dry_run(tenant_id: int, rows: List[Dict]) -> List[Dict]:
    """Tag each row with a status: READY, MISSING_DEPENDENCY, or INVALID.

    No API calls are made.  Returns the enriched row list.
    """
    enriched, missing = resolve_dependencies(tenant_id, rows)
    missing_seg = set(missing.get("segment_group", []))
    missing_srv = set(missing.get("server_group", []))

    result: List[Dict] = []
    for row in enriched:
        r = dict(row)
        issues = []

        sg_name = row["segment_group"].strip()
        if sg_name in missing_seg:
            issues.append(f"segment_group '{sg_name}' not found in DB")

        for sg in row["server_groups"].split(";"):
            sg = sg.strip()
            if sg and sg in missing_srv:
                issues.append(f"server_group '{sg}' not found in DB")

        if issues:
            r["_status"] = "MISSING_DEPENDENCY"
            r["_issues"] = issues
        else:
            r["_status"] = "READY"
            r["_issues"] = []

        result.append(r)

    return result


# ---------------------------------------------------------------------------
# Bulk create
# ---------------------------------------------------------------------------

def bulk_create(
    client,
    tenant_id: int,
    rows: List[Dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> BulkCreateResult:
    """Create application segments for READY rows.

    Args:
        client: ZPAClient instance
        tenant_id: local DB tenant ID
        rows: dry_run()-annotated rows (must have '_status', '_segment_group_id', etc.)
        progress_callback: called as (done, total) after each row

    Returns:
        BulkCreateResult with created/failed/skipped counts and per-row detail.
    """
    result = BulkCreateResult()
    ready_rows = [r for r in rows if r.get("_status") == "READY"]
    skipped_rows = [r for r in rows if r.get("_status") != "READY"]
    result.skipped = len(skipped_rows)
    total = len(ready_rows)

    for i, row in enumerate(ready_rows, start=1):
        name = row.get("name", "")
        try:
            payload: Dict[str, Any] = {
                "name": name,
                "domain_names": [
                    d.strip() for d in row["domain_names"].split(";") if d.strip()
                ],
                "segment_group_id": row["_segment_group_id"],
                "server_groups": [{"id": sid} for sid in row.get("_server_group_ids", [])],
                "enabled": row.get("enabled", "true").lower() not in ("false", "0", "no"),
            }

            tcp = _parse_ports(row.get("tcp_ports", ""))
            udp = _parse_ports(row.get("udp_ports", ""))
            if tcp:
                payload["tcp_port_ranges"] = tcp
            if udp:
                payload["udp_port_ranges"] = udp

            if row.get("description"):
                payload["description"] = row["description"]
            if row.get("app_type"):
                payload["app_type"] = row["app_type"]
            if row.get("bypass_type"):
                payload["bypass_type"] = row["bypass_type"]
            if row.get("health_check_type"):
                payload["health_check_type"] = row["health_check_type"]
            if row.get("health_reporting"):
                payload["health_reporting"] = row["health_reporting"]
            if row.get("icmp_access_type"):
                payload["icmp_access_type"] = row["icmp_access_type"]

            for bool_field in (
                "double_encrypt",
                "passive_health_enabled",
                "is_cname_enabled",
                "select_connector_close_to_app",
            ):
                val = row.get(bool_field, "")
                if val:
                    payload[bool_field] = val.lower() not in ("false", "0", "no")

            created = client.create_application(**payload)
            app_id = str(created.get("id", ""))

            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="SUCCESS",
                tenant_id=tenant_id,
                resource_type="application",
                resource_id=app_id,
                resource_name=name,
            )

            result.rows_detail.append({
                "name": name,
                "status": "CREATED",
                "id": app_id,
                "error": None,
            })
            result.created += 1

        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZPA",
                operation="bulk_create_segments",
                action="CREATE",
                status="FAILURE",
                tenant_id=tenant_id,
                resource_type="application",
                resource_name=name,
                error_message=error_msg,
            )
            result.rows_detail.append({
                "name": name,
                "status": "FAILED",
                "id": None,
                "error": error_msg,
            })
            result.failed += 1

        if progress_callback:
            progress_callback(i, total)

    # Add skipped rows to detail
    for row in skipped_rows:
        result.rows_detail.append({
            "name": row.get("name", ""),
            "status": f"SKIPPED ({row.get('_status', 'UNKNOWN')})",
            "id": None,
            "error": "; ".join(row.get("_issues", [])),
        })

    return result
