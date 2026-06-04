"""ZCC Configuration Snapshot and Restore service."""

import hashlib
import json
import logging
from typing import Dict, List, Optional

from db.database import get_session
from db.models import ZCCResource, ZCCSnapshot, ZCCSnapshotItem
from services import audit_service

logger = logging.getLogger(__name__)

_PASSWORD_FIELDS = {
    "exitPassword", "zdxDisablePassword", "zdDisablePassword",
    "zpaDisablePassword", "zdpDisablePassword",
}

_RESTORE_STRATEGIES = {
    "trusted_network":    "full_crud",
    "forwarding_profile": "update_only",
    "web_policy":         "update_only",
    "fail_open_policy":   "update_by_id",
    "web_privacy":        "singleton",
    "device_cleanup":     "singleton",
    "entitlement_zpa":    "singleton",
    "entitlement_zdx":    "singleton",
}

_SKIP_TYPES = {
    "device",
    "web_app_service",
    "ip_app_custom",
    "ip_app_predefined",
    "process_app",
    "admin_user",
    "admin_role",
    "company_info",
    "application_profile",
}

_RESTORABLE_TYPES = set(_RESTORE_STRATEGIES.keys())

_RESTORE_ORDER = [
    "trusted_network",
    "forwarding_profile",
    "web_policy",
    "fail_open_policy",
    "web_privacy",
    "device_cleanup",
    "entitlement_zpa",
    "entitlement_zdx",
]


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _strip_passwords(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _PASSWORD_FIELDS}


class ZCCSnapshotService:
    def __init__(self, client, tenant_id: int):
        self.client = client
        self.tenant_id = tenant_id

    def create_snapshot(self, label: str, note: Optional[str] = None) -> ZCCSnapshot:
        snapshot_id = None
        resource_count = 0

        with get_session() as session:
            resources = (
                session.query(ZCCResource)
                .filter_by(tenant_id=self.tenant_id, is_deleted=False)
                .all()
            )
            snapshot = ZCCSnapshot(
                tenant_id=self.tenant_id,
                label=label,
                note=note,
            )
            session.add(snapshot)
            session.flush()

            items = []
            for res in resources:
                item = ZCCSnapshotItem(
                    snapshot_id=snapshot.id,
                    resource_type=res.resource_type,
                    zcc_id=res.zcc_id,
                    name=res.name,
                    raw_config=res.raw_config,
                )
                session.add(item)
                items.append(item)

            snapshot.resource_count = len(items)
            resource_count = len(items)
            snapshot_id = snapshot.id

        audit_service.log(
            product="ZCC",
            operation="zcc_snapshot",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="snapshot",
            resource_id=str(snapshot_id),
            resource_name=label,
            details={"resource_count": resource_count},
        )

        with get_session() as session:
            return session.get(ZCCSnapshot, snapshot_id)

    def list_snapshots(self) -> List[ZCCSnapshot]:
        with get_session() as session:
            return (
                session.query(ZCCSnapshot)
                .filter_by(tenant_id=self.tenant_id)
                .order_by(ZCCSnapshot.created_at.desc())
                .all()
            )

    def delete_snapshot(self, snapshot_id: int) -> None:
        label = None

        with get_session() as session:
            snapshot = session.get(ZCCSnapshot, snapshot_id)
            if not snapshot or snapshot.tenant_id != self.tenant_id:
                raise ValueError("snapshot not found")
            label = snapshot.label
            session.delete(snapshot)

        audit_service.log(
            product="ZCC",
            operation="zcc_snapshot",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="snapshot",
            resource_id=str(snapshot_id),
            resource_name=label,
        )

    def diff_snapshot(self, snapshot_id: int) -> List[dict]:
        with get_session() as session:
            snapshot = session.get(ZCCSnapshot, snapshot_id)
            if not snapshot or snapshot.tenant_id != self.tenant_id:
                raise ValueError("snapshot not found")

            snap_items = (
                session.query(ZCCSnapshotItem)
                .filter_by(snapshot_id=snapshot_id)
                .all()
            )
            live_rows = (
                session.query(ZCCResource)
                .filter_by(tenant_id=self.tenant_id, is_deleted=False)
                .all()
            )

            snap_by_type: Dict[str, List] = {}
            for item in snap_items:
                snap_by_type.setdefault(item.resource_type, []).append(item)

            live_by_type: Dict[str, List] = {}
            for row in live_rows:
                live_by_type.setdefault(row.resource_type, []).append(row)

            all_types = set(snap_by_type) | set(live_by_type)
            results = []

            for rtype in sorted(all_types):
                snap_list = snap_by_type.get(rtype, [])
                live_list = live_by_type.get(rtype, [])

                snap_map = {item.zcc_id: _hash(item.raw_config) for item in snap_list}
                live_map = {row.zcc_id: _hash(row.raw_config) for row in live_list}

                snap_ids = set(snap_map)
                live_ids = set(live_map)

                added_since = len(live_ids - snap_ids)
                removed_since = len(snap_ids - live_ids)
                both = snap_ids & live_ids
                changed_since = sum(1 for zid in both if snap_map[zid] != live_map[zid])
                unchanged = sum(1 for zid in both if snap_map[zid] == live_map[zid])

                results.append({
                    "resource_type": rtype,
                    "added_since": added_since,
                    "removed_since": removed_since,
                    "changed_since": changed_since,
                    "unchanged": unchanged,
                    "restorable": rtype in _RESTORABLE_TYPES,
                })

        return results

    def restore_snapshot(
        self,
        snapshot_id: int,
        resource_types: Optional[List[str]] = None,
        dry_run: bool = False,
        target_client=None,
        target_tenant_id: Optional[int] = None,
    ) -> dict:
        effective_client = target_client if target_client is not None else self.client
        cross_tenant = target_client is not None

        with get_session() as session:
            snapshot = session.get(ZCCSnapshot, snapshot_id)
            if not snapshot or snapshot.tenant_id != self.tenant_id:
                raise ValueError("snapshot not found")

            snap_items = (
                session.query(ZCCSnapshotItem)
                .filter_by(snapshot_id=snapshot_id)
                .all()
            )
            items_by_type: Dict[str, List] = {}
            for item in snap_items:
                items_by_type.setdefault(item.resource_type, []).append({
                    "zcc_id": item.zcc_id,
                    "name": item.name,
                    "raw_config": dict(item.raw_config) if item.raw_config else {},
                })

        results: List[dict] = []

        for rtype in _RESTORE_ORDER:
            if resource_types is not None and rtype not in resource_types:
                continue
            if rtype not in items_by_type:
                continue
            if rtype in _SKIP_TYPES:
                continue

            strategy = _RESTORE_STRATEGIES.get(rtype)
            if not strategy:
                continue

            snap_list = items_by_type[rtype]

            if strategy == "full_crud":
                self._restore_full_crud(
                    rtype, snap_list, effective_client, cross_tenant, dry_run, results
                )
            elif strategy == "update_only":
                self._restore_update_only(
                    rtype, snap_list, effective_client, cross_tenant, dry_run, results
                )
            elif strategy == "update_by_id":
                self._restore_update_by_id(
                    rtype, snap_list, effective_client, cross_tenant, dry_run, results
                )
            elif strategy == "singleton":
                self._restore_singleton(
                    rtype, snap_list, effective_client, dry_run, results
                )

        summary = {
            "created":      sum(1 for r in results if r["action"] == "created"      and r["success"]),
            "updated":      sum(1 for r in results if r["action"] == "updated"      and r["success"]),
            "deleted":      sum(1 for r in results if r["action"] == "deleted"      and r["success"]),
            "skipped":      sum(1 for r in results if r["action"] == "skipped"),
            "failed":       sum(1 for r in results if not r["success"] and r["action"] != "unrestorable"),
            "unrestorable": sum(1 for r in results if r["action"] == "unrestorable"),
        }

        pending_audit = []
        for r in results:
            pending_audit.append({
                "product": "ZCC",
                "operation": "zcc_restore",
                "action": r["action"].upper(),
                "status": "SUCCESS" if r["success"] else "FAILURE",
                "tenant_id": self.tenant_id,
                "resource_type": r["resource_type"],
                "resource_id": r["zcc_id"],
                "resource_name": r["name"],
                "details": {
                    "snapshot_id": snapshot_id,
                    "dry_run": dry_run,
                    "target_tenant_id": target_tenant_id,
                    "reason": r["reason"],
                },
                "error_message": r["reason"] if not r["success"] else None,
            })

        if pending_audit:
            audit_service.log_many(pending_audit)

        return {"dry_run": dry_run, "results": results, "summary": summary}

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _restore_full_crud(self, rtype, snap_list, client, cross_tenant, dry_run, results):
        try:
            live_list = client.list_trusted_networks()
        except Exception as exc:
            for item in snap_list:
                results.append({
                    "resource_type": rtype,
                    "action": "failed",
                    "name": item["name"],
                    "zcc_id": item["zcc_id"],
                    "success": False,
                    "reason": f"failed to load live state: {exc}",
                })
            return

        def _get_name(cfg):
            return cfg.get("network_name") or cfg.get("networkName") or ""

        live_by_id = {str(r.get("id", "")): r for r in live_list if r.get("id")}
        live_by_name = {_get_name(r): r for r in live_list if _get_name(r)}
        snap_names = {_get_name(item["raw_config"]) for item in snap_list}

        for item in snap_list:
            cfg = dict(item["raw_config"])
            name = _get_name(cfg) or item["name"]
            zcc_id = item["zcc_id"]

            live_match = None
            if not cross_tenant:
                live_match = live_by_id.get(zcc_id) or live_by_name.get(name)
            else:
                live_match = live_by_name.get(name)

            if live_match is not None:
                payload = dict(cfg)
                for fld in ("active", "companyId", "tenantId"):
                    payload.pop(fld, None)
                payload["id"] = live_match.get("id")

                if dry_run:
                    results.append({
                        "resource_type": rtype,
                        "action": "updated",
                        "name": name,
                        "zcc_id": zcc_id,
                        "success": True,
                        "reason": None,
                    })
                else:
                    try:
                        client.update_trusted_network(**payload)
                        results.append({
                            "resource_type": rtype,
                            "action": "updated",
                            "name": name,
                            "zcc_id": zcc_id,
                            "success": True,
                            "reason": None,
                        })
                    except Exception as exc:
                        logger.debug("trusted_network update failed", exc_info=True)
                        results.append({
                            "resource_type": rtype,
                            "action": "updated",
                            "name": name,
                            "zcc_id": zcc_id,
                            "success": False,
                            "reason": str(exc),
                        })
            else:
                payload = dict(cfg)
                for fld in ("id", "active", "companyId", "tenantId"):
                    payload.pop(fld, None)

                if dry_run:
                    results.append({
                        "resource_type": rtype,
                        "action": "created",
                        "name": name,
                        "zcc_id": zcc_id,
                        "success": True,
                        "reason": None,
                    })
                else:
                    try:
                        client.create_trusted_network(**payload)
                        results.append({
                            "resource_type": rtype,
                            "action": "created",
                            "name": name,
                            "zcc_id": zcc_id,
                            "success": True,
                            "reason": None,
                        })
                    except Exception as exc:
                        logger.debug("trusted_network create failed", exc_info=True)
                        results.append({
                            "resource_type": rtype,
                            "action": "created",
                            "name": name,
                            "zcc_id": zcc_id,
                            "success": False,
                            "reason": str(exc),
                        })

        for live_item in live_list:
            live_name = _get_name(live_item)
            if live_name and live_name not in snap_names:
                live_id = live_item.get("id")
                if dry_run:
                    results.append({
                        "resource_type": rtype,
                        "action": "deleted",
                        "name": live_name,
                        "zcc_id": str(live_id) if live_id else None,
                        "success": True,
                        "reason": None,
                    })
                else:
                    try:
                        client.delete_trusted_network(live_id)
                        results.append({
                            "resource_type": rtype,
                            "action": "deleted",
                            "name": live_name,
                            "zcc_id": str(live_id) if live_id else None,
                            "success": True,
                            "reason": None,
                        })
                    except Exception as exc:
                        logger.debug("trusted_network delete failed", exc_info=True)
                        results.append({
                            "resource_type": rtype,
                            "action": "deleted",
                            "name": live_name,
                            "zcc_id": str(live_id) if live_id else None,
                            "success": False,
                            "reason": str(exc),
                        })

    def _restore_update_only(self, rtype, snap_list, client, cross_tenant, dry_run, results):
        try:
            if rtype == "forwarding_profile":
                live_list = client.list_forwarding_profiles()
            else:
                live_list = client.list_web_policies()
        except Exception as exc:
            for item in snap_list:
                results.append({
                    "resource_type": rtype,
                    "action": "failed",
                    "name": item["name"],
                    "zcc_id": item["zcc_id"],
                    "success": False,
                    "reason": f"failed to load live state: {exc}",
                })
            return

        live_by_id = {str(r.get("id", "")): r for r in live_list if r.get("id")}
        live_by_name = {str(r.get("name", "")): r for r in live_list if r.get("name")}

        for item in snap_list:
            cfg = dict(item["raw_config"])
            name = item["name"] or cfg.get("name") or ""
            zcc_id = item["zcc_id"]

            if rtype == "web_policy":
                cfg = _strip_passwords(cfg)

            live_match = None
            if not cross_tenant:
                live_match = live_by_id.get(zcc_id) or live_by_name.get(name)
            else:
                live_match = live_by_name.get(name)

            if live_match is None:
                results.append({
                    "resource_type": rtype,
                    "action": "unrestorable",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": False,
                    "reason": "no create API available",
                })
                continue

            payload = dict(cfg)
            payload["id"] = live_match.get("id")

            if dry_run:
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": True,
                    "reason": None,
                })
                continue

            try:
                if rtype == "forwarding_profile":
                    client.update_forwarding_profile(**payload)
                else:
                    client.edit_web_policy(**payload)
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": True,
                    "reason": None,
                })
            except Exception as exc:
                logger.debug("%s update failed", rtype, exc_info=True)
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": False,
                    "reason": str(exc),
                })

    def _restore_update_by_id(self, rtype, snap_list, client, cross_tenant, dry_run, results):
        try:
            live_list = client.list_fail_open_policies()
        except Exception as exc:
            for item in snap_list:
                results.append({
                    "resource_type": rtype,
                    "action": "failed",
                    "name": item["name"],
                    "zcc_id": item["zcc_id"],
                    "success": False,
                    "reason": f"failed to load live state: {exc}",
                })
            return

        live_by_id = {str(r.get("id", "")): r for r in live_list if r.get("id")}

        def _device_type(cfg):
            return cfg.get("deviceType") or cfg.get("device_type") or ""

        live_by_device_type = {_device_type(r): r for r in live_list if _device_type(r)}

        for item in snap_list:
            cfg = dict(item["raw_config"])
            name = item["name"] or str(cfg.get("id", ""))
            zcc_id = item["zcc_id"]

            live_match = None
            if not cross_tenant:
                live_match = live_by_id.get(zcc_id)
            else:
                live_match = live_by_device_type.get(_device_type(cfg))

            if live_match is None:
                results.append({
                    "resource_type": rtype,
                    "action": "unrestorable",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": False,
                    "reason": "no match by id/device_type in target tenant",
                })
                continue

            payload = dict(cfg)
            payload["id"] = live_match.get("id")

            if dry_run:
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": True,
                    "reason": None,
                })
                continue

            try:
                client.update_fail_open_policy(**payload)
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": True,
                    "reason": None,
                })
            except Exception as exc:
                logger.debug("fail_open_policy update failed", exc_info=True)
                results.append({
                    "resource_type": rtype,
                    "action": "updated",
                    "name": name,
                    "zcc_id": zcc_id,
                    "success": False,
                    "reason": str(exc),
                })

    def _restore_singleton(self, rtype, snap_list, client, dry_run, results):
        if not snap_list:
            return

        item = snap_list[0]
        cfg = dict(item["raw_config"])
        cfg.pop("id", None)
        name = item["name"]
        zcc_id = item["zcc_id"]

        if dry_run:
            results.append({
                "resource_type": rtype,
                "action": "updated",
                "name": name,
                "zcc_id": zcc_id,
                "success": True,
                "reason": None,
            })
            return

        try:
            if rtype == "web_privacy":
                client.set_web_privacy(**cfg)
            elif rtype == "device_cleanup":
                client.set_device_cleanup(**cfg)
            elif rtype == "entitlement_zpa":
                client.update_zpa_entitlements(cfg)
            elif rtype == "entitlement_zdx":
                client.update_zdx_entitlements(cfg)
            results.append({
                "resource_type": rtype,
                "action": "updated",
                "name": name,
                "zcc_id": zcc_id,
                "success": True,
                "reason": None,
            })
        except Exception as exc:
            logger.debug("%s singleton update failed", rtype, exc_info=True)
            results.append({
                "resource_type": rtype,
                "action": "updated",
                "name": name,
                "zcc_id": zcc_id,
                "success": False,
                "reason": str(exc),
            })
