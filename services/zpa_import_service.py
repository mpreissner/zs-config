"""ZPA config import service.

Pulls the current configuration from ZPA via the API and stores each resource
as a ZPAResource row.  Unchanged resources (same config_hash) are skipped so
re-runs are fast.  A SyncLog row records the outcome of every run.

Usage:
    service = ZPAImportService(client, tenant_id=tenant.id)

    # With a progress callback (receives (resource_type, count, total_types)):
    def on_progress(resource_type, count, total):
        print(f"{resource_type}: {count}/{total}")

    service.run(progress_callback=on_progress)
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from db.database import get_session
from db.models import SyncLog, ZPAResource
from lib.rate_limiter import ZPA_READ_LIMITER


@dataclass
class ResourceDef:
    """Describes one ZPA resource type to import."""
    resource_type: str          # key stored in zpa_resources.resource_type
    list_method: str            # name of ZPAClient method that returns a list
    id_field: str = "id"        # JSON field containing the ZPA resource ID
    name_field: str = "name"    # JSON field containing a human-readable name
    list_args: dict = field(default_factory=dict)  # extra kwargs for list_method


# All resource types we import.  Order doesn't matter.
RESOURCE_DEFINITIONS: List[ResourceDef] = [
    ResourceDef("application",          "list_applications"),
    ResourceDef("segment_group",        "list_segment_groups"),
    ResourceDef("server_group",         "list_server_groups"),
    ResourceDef("app_connector_group",  "list_connector_groups"),
    ResourceDef("app_connector",        "list_connectors"),
    ResourceDef("pra_portal",           "list_pra_portals"),
    ResourceDef("pra_credential",       "list_credentials"),
    ResourceDef("idp",                  "list_idp"),
    ResourceDef("saml_attribute",       "list_saml_attributes"),
    ResourceDef("scim_group",           "_scim_groups_all"),  # handled specially in _fetch
    ResourceDef("microtenant",          "list_microtenants"),
    ResourceDef("enrollment_cert",      "list_enrollment_certificates"),
    ResourceDef("policy_access",        "list_policy_rules", list_args={"policy_type": "ACCESS_POLICY"}),
    ResourceDef("policy_timeout",       "list_policy_rules", list_args={"policy_type": "TIMEOUT_POLICY"}),
    ResourceDef("policy_forwarding",    "list_policy_rules", list_args={"policy_type": "CLIENT_FORWARDING_POLICY"}),
    ResourceDef("policy_inspection",    "list_policy_rules", list_args={"policy_type": "INSPECTION_POLICY"}),
    ResourceDef("policy_isolation",     "list_policy_rules", list_args={"policy_type": "ISOLATION_POLICY"}),
    ResourceDef("certificate",          "list_certificates"),
]


def _hash(obj) -> str:
    """Return SHA-256 hex digest of a JSON-serialised object."""
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class ZPAImportService:
    def __init__(self, client, tenant_id: int):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        resource_types: Optional[List[str]] = None,
    ) -> SyncLog:
        """Import ZPA config into the database.

        Args:
            progress_callback: Called after each resource type is fetched.
                Signature: callback(resource_type: str, done: int, total: int)
            resource_types: If given, only import these resource_type values.

        Returns:
            The completed SyncLog ORM object.
        """
        defs = [d for d in RESOURCE_DEFINITIONS
                if resource_types is None or d.resource_type in resource_types]
        total = len(defs)

        with get_session() as session:
            sync = SyncLog(
                tenant_id=self.tenant_id,
                product="ZPA",
                status="RUNNING",
            )
            session.add(sync)
            session.flush()
            sync_id = sync.id

        # Capture run start once so _upsert and _mark_deleted use the same
        # timestamp — rows written this run get synced_at == run_start, and
        # _mark_deleted looks for synced_at < run_start to find stale rows.
        run_start = datetime.utcnow()

        synced = updated = deleted = 0
        errors = []

        for idx, defn in enumerate(defs, start=1):
            try:
                records = self._fetch(defn)
            except Exception as exc:
                errors.append(f"{defn.resource_type}: {exc}")
                if progress_callback:
                    progress_callback(defn.resource_type, idx, total)
                continue

            s, u = self._upsert(defn, records, run_start)
            synced += s
            updated += u

            if progress_callback:
                progress_callback(defn.resource_type, idx, total)

        # Mark any resource no longer returned by the API as deleted
        deleted = self._mark_deleted(resource_types, run_start)

        final_status = "FAILED" if len(errors) == total else (
            "PARTIAL" if errors else "SUCCESS"
        )

        with get_session() as session:
            sync = session.get(SyncLog, sync_id)
            sync.completed_at = datetime.utcnow()
            sync.status = final_status
            sync.resources_synced = synced
            sync.resources_updated = updated
            sync.resources_deleted = deleted
            sync.error_message = "\n".join(errors) if errors else None

        # Return a detached copy
        with get_session() as session:
            return session.get(SyncLog, sync_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch(self, defn: ResourceDef) -> list:
        """Call the appropriate ZPAClient list method with rate limiting."""
        if defn.list_method == "_scim_groups_all":
            return self._fetch_scim_groups_all()
        ZPA_READ_LIMITER.acquire()
        method = getattr(self.client, defn.list_method)
        result = method(**defn.list_args) if defn.list_args else method()
        return result or []

    def _fetch_scim_groups_all(self) -> list:
        """Fetch SCIM groups across all IdPs, rate-limiting each call."""
        ZPA_READ_LIMITER.acquire()
        idps = self.client.list_idp()
        groups = []
        for idp in idps:
            idp_id = str(idp.get("id", ""))
            if not idp_id:
                continue
            ZPA_READ_LIMITER.acquire()
            try:
                groups.extend(self.client.list_scim_groups(idp_id) or [])
            except Exception:
                pass
        return groups

    def _upsert(self, defn: ResourceDef, records: list, run_start: datetime):
        """Insert or update ZPAResource rows for the fetched records.

        Returns (synced_count, updated_count).
        """
        synced = updated = 0

        with get_session() as session:
            for record in records:
                if not isinstance(record, dict):
                    continue
                zpa_id = str(record.get(defn.id_field, ""))
                if not zpa_id:
                    continue

                new_hash = _hash(record)
                name = record.get(defn.name_field) or ""

                existing = (
                    session.query(ZPAResource)
                    .filter_by(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zpa_id=zpa_id,
                    )
                    .first()
                )

                if existing is None:
                    session.add(ZPAResource(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zpa_id=zpa_id,
                        name=name,
                        raw_config=record,
                        config_hash=new_hash,
                        synced_at=run_start,
                        is_deleted=False,
                    ))
                    synced += 1
                else:
                    # Always update synced_at; only update data when changed
                    existing.synced_at = run_start
                    existing.is_deleted = False
                    if existing.config_hash != new_hash:
                        existing.name = name
                        existing.raw_config = record
                        existing.config_hash = new_hash
                        updated += 1
                    synced += 1

        return synced, updated

    def _mark_deleted(self, resource_types: Optional[List[str]], run_start: datetime) -> int:
        """Mark rows not touched in this sync run as deleted.

        Rows written during this run have synced_at == run_start.  Any row
        with synced_at < run_start was not returned by the API this time.
        """
        deleted = 0
        type_filter = resource_types or [d.resource_type for d in RESOURCE_DEFINITIONS]

        with get_session() as session:
            stale = (
                session.query(ZPAResource)
                .filter(
                    ZPAResource.tenant_id == self.tenant_id,
                    ZPAResource.resource_type.in_(type_filter),
                    ZPAResource.is_deleted == False,
                    ZPAResource.synced_at < run_start,
                )
                .all()
            )
            for row in stale:
                row.is_deleted = True
                deleted += 1

        return deleted
