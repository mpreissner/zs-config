"""ZPA business logic layer.

Wraps ZPAClient with:
  - Audit logging for every mutating operation
  - Certificate tracking in the local database
  - Higher-level workflows (e.g. full certificate rotation)
  - DB-first reads for all cached resource types
"""

import io
import csv
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from db.database import get_session
from db.models import Certificate, ZPAResource
from lib.zpa_client import ZPAClient
from services import audit_service


def _rule_order_key(n):
    """Sort key: positive integers ascending first, then negative integers descending.

    Positive/zero positions (user rules) come first in ascending order.
    Negative positions (system/default rules) come last in descending order.
    e.g. 1, 2, 3, ..., -1, -2, -3, ...
    """
    return (0, n) if n >= 0 else (1, -n)


def _db_list(tenant_id: int, resource_type: str, q: Optional[str] = None) -> List[Dict]:
    """Shared DB-first list helper. Returns raw_config rows with zpa_id and name at top level."""
    with get_session() as session:
        rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type=resource_type, is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        result = [{"zpa_id": r.zpa_id, "name": r.name, **(r.raw_config or {})} for r in rows]
    if q:
        result = [r for r in result if q.lower() in (r.get("name") or "").lower()]
    return result


class ZPAService:
    def __init__(self, client: Optional[ZPAClient] = None, tenant_id: Optional[int] = None):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Certificate rotation (primary workflow)
    # ------------------------------------------------------------------

    def rotate_certificate(self, cert_path: str, key_path: str, domain: str) -> Dict:
        """Full certificate rotation for a domain:

        1. Read cert + key files and combine into PEM blob
        2. Upload new certificate to ZPA
        3. Update all Browser Access app segments matching the domain
        4. Update all PRA Portals matching the domain
        5. Delete old certificates that are no longer referenced anywhere
        6. Record everything in the audit log + local certificate table

        Returns a summary dict suitable for display or logging.
        """
        with open(cert_path) as f:
            cert_data = f.read().strip()
        with open(key_path) as f:
            key_data = f.read().strip()

        combined_pem = cert_data + "\n" + key_data
        cert_name = f"{domain.replace('*.', 'wildcard-')}-{int(time.time())}"
        description = f"Auto-uploaded on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Step 1 — upload new cert
        new_cert = self.client.upload_certificate(cert_name, combined_pem, description)
        new_cert_id = new_cert["id"]

        audit_service.log(
            product="ZPA",
            operation="rotate_certificate",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="certificate",
            resource_id=new_cert_id,
            resource_name=cert_name,
            details={"domain": domain},
        )

        self._record_certificate(new_cert_id, cert_name, domain)

        domain_base = domain.replace("*.", "")
        old_cert_ids: Set[str] = set()
        updated: Dict[str, Set[str]] = {"apps": set(), "pra_portals": set()}

        # Step 2 — update Browser Access app segments
        for app in self.client.list_applications("BROWSER_ACCESS"):
            clientless = app.get("clientlessApps", [])
            if not self._domain_matches_any(clientless, domain_base):
                continue

            app_config = self.client.get_application(app["id"])
            for ca in app_config.get("clientlessApps", []):
                if self._domain_matches(ca.get("domain", ""), domain_base):
                    if old_id := ca.get("certificateId"):
                        old_cert_ids.add(str(old_id))
                    ca["certificateId"] = new_cert_id

            self.client.update_application(app["id"], app_config)
            updated["apps"].add(app["id"])

            audit_service.log(
                product="ZPA",
                operation="rotate_certificate",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                resource_type="application",
                resource_id=app["id"],
                resource_name=app["name"],
                details={"new_cert_id": new_cert_id, "domain": domain},
            )
            time.sleep(0.5)

        # Step 3 — update PRA Portals (use live API for real-time data during rotation)
        for portal in self._list_pra_portals_live():
            if portal.get("certificateId") in (None, 0):
                continue  # Zscaler-managed cert, skip
            if not self._domain_matches(portal.get("domain", ""), domain_base):
                continue

            old_id = portal.get("certificateId")
            if old_id:
                old_cert_ids.add(str(old_id))

            portal_config = self.client.get_pra_portal(portal["id"])
            portal_config["certificateId"] = new_cert_id
            self.client.update_pra_portal(portal["id"], portal_config)
            updated["pra_portals"].add(portal["id"])

            audit_service.log(
                product="ZPA",
                operation="rotate_certificate",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                resource_type="pra_portal",
                resource_id=portal["id"],
                resource_name=portal["name"],
                details={"new_cert_id": new_cert_id, "old_cert_id": old_id},
            )
            time.sleep(0.5)

        # Step 4 — clean up old certs no longer in use
        deleted = 0
        skipped = 0
        for old_id in old_cert_ids:
            if old_id == new_cert_id:
                continue
            if self._is_cert_in_use(old_id, exclude=updated):
                skipped += 1
            else:
                if self.client.delete_certificate(old_id):
                    deleted += 1
                    self._mark_certificate_replaced(old_id, new_cert_id)
                    audit_service.log(
                        product="ZPA",
                        operation="rotate_certificate",
                        action="DELETE",
                        status="SUCCESS",
                        tenant_id=self.tenant_id,
                        resource_type="certificate",
                        resource_id=old_id,
                        details={"replaced_by": new_cert_id},
                    )

        return {
            "new_cert_id": new_cert_id,
            "cert_name": cert_name,
            "apps_updated": len(updated["apps"]),
            "portals_updated": len(updated["pra_portals"]),
            "certs_deleted": deleted,
            "certs_skipped": skipped,
        }

    # ------------------------------------------------------------------
    # Certificate helpers
    # ------------------------------------------------------------------

    def list_certificates(self) -> List[Dict]:
        result = self.client.list_certificates()
        audit_service.log(
            product="ZPA", operation="list_certificates", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="certificate",
            details={"count": len(result)},
        )
        return result

    def list_certificates_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "certificate", q)
        audit_service.log(
            product="ZPA", operation="list_certificates", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="certificate",
            details={"count": len(result), "source": "db"},
        )
        return result

    def get_certificate(self, cert_id: str) -> Optional[Dict]:
        return self.client.get_certificate(cert_id)

    def delete_certificate(self, cert_id: str) -> bool:
        result = self.client.delete_certificate(cert_id)
        if result:
            audit_service.log(
                product="ZPA",
                operation="delete_certificate",
                action="DELETE",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                resource_type="certificate",
                resource_id=cert_id,
            )
        return result

    # ------------------------------------------------------------------
    # Application helpers
    # ------------------------------------------------------------------

    def get_application(self, app_id: str) -> Dict:
        result = self.client.get_application(app_id)
        audit_service.log(
            product="ZPA", operation="get_application", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="application",
            resource_id=app_id, resource_name=result.get("name"),
        )
        return result

    def create_application(self, **kwargs) -> Dict:
        result = self.client.create_application(**kwargs)
        audit_service.log(
            product="ZPA",
            operation="create_application",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="application",
            resource_id=result.get("id"),
            resource_name=result.get("name"),
        )
        return result

    def update_application(self, app_id: str, config: Dict) -> Dict:
        self.client.update_application(app_id, config)
        result = self.client.get_application(app_id)
        audit_service.log(
            product="ZPA",
            operation="update_application",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="application",
            resource_id=app_id,
            resource_name=config.get("name"),
        )
        return result

    def delete_application(self, app_id: str, app_name: str) -> bool:
        result = self.client.delete_application(app_id)
        audit_service.log(
            product="ZPA",
            operation="delete_application",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="application",
            resource_id=app_id,
            resource_name=app_name,
        )
        return result

    def set_application_enabled(self, app_id: str, enabled: bool) -> Dict:
        app = self.client.get_application(app_id)
        app["enabled"] = enabled
        # Strip plural port range keys that conflict with the SDK
        app.pop("tcp_port_ranges", None)
        app.pop("udp_port_ranges", None)
        self.client.update_application(app_id, app)
        result = self.client.get_application(app_id)
        audit_service.log(
            product="ZPA",
            operation="set_application_enabled",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="application",
            resource_id=app_id,
            resource_name=app.get("name"),
            details={"enabled": enabled},
        )
        return result

    def list_applications(self, app_type: str = "BROWSER_ACCESS") -> List[Dict]:
        result = self.client.list_applications(app_type)
        audit_service.log(
            product="ZPA", operation="list_applications", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="application",
            details={"count": len(result), "app_type": app_type},
        )
        return result

    def list_applications_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "application", q)
        audit_service.log(
            product="ZPA", operation="list_applications", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="application",
            details={"count": len(result), "source": "db"},
        )
        return result

    # ------------------------------------------------------------------
    # Segment groups (DB-first)
    # ------------------------------------------------------------------

    def list_segment_groups(self) -> List[Dict]:
        result = _db_list(self.tenant_id, "segment_group")
        audit_service.log(
            product="ZPA", operation="list_segment_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="segment_group",
            details={"count": len(result)},
        )
        return result

    def _list_segment_groups_live(self) -> List[Dict]:
        return self.client.list_segment_groups()

    # ------------------------------------------------------------------
    # Server groups (DB-first)
    # ------------------------------------------------------------------

    def list_server_groups(self) -> List[Dict]:
        result = _db_list(self.tenant_id, "server_group")
        audit_service.log(
            product="ZPA", operation="list_server_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="server_group",
            details={"count": len(result)},
        )
        return result

    def _list_server_groups_live(self) -> List[Dict]:
        return self.client.list_server_groups()

    # ------------------------------------------------------------------
    # App connectors (DB-first + mutations)
    # ------------------------------------------------------------------

    def list_app_connectors(self) -> List[Dict]:
        return self.list_connectors_from_db()

    def _list_app_connectors_live(self) -> List[Dict]:
        return self.client.list_connectors()

    def list_connectors_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "app_connector", q)
        audit_service.log(
            product="ZPA", operation="list_app_connectors", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="app_connector",
            details={"count": len(result)},
        )
        return result

    def set_connector_enabled(self, connector_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        connector_name = connector_id
        try:
            config = self.client.get_connector(connector_id)
            connector_name = config.get("name", connector_id)
            config["enabled"] = enabled
            self.client.update_connector(connector_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["app_connector"])
            row = self._get_db_row("app_connector", connector_id)
            audit_service.log(
                product="ZPA", operation="toggle_connector", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector",
                resource_id=connector_id, resource_name=connector_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_connector", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector",
                resource_id=connector_id, resource_name=connector_name,
                error_message=str(exc),
            )
            raise

    def rename_connector(self, connector_id: str, new_name: str) -> Dict:
        from services.zpa_import_service import ZPAImportService
        old_name = connector_id
        try:
            config = self.client.get_connector(connector_id)
            old_name = config.get("name", connector_id)
            config["name"] = new_name
            self.client.update_connector(connector_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["app_connector"])
            row = self._get_db_row("app_connector", connector_id)
            audit_service.log(
                product="ZPA", operation="rename_connector", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector",
                resource_id=connector_id, resource_name=new_name,
                details={"old_name": old_name, "new_name": new_name},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="rename_connector", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector",
                resource_id=connector_id, resource_name=old_name,
                error_message=str(exc),
            )
            raise

    def delete_connector(self, connector_id: str, connector_name: str) -> bool:  # TODO: test
        try:
            self.client.delete_connector(connector_id)
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="delete_connector", action="DELETE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector",
                resource_id=connector_id, resource_name=connector_name,
                error_message=str(exc),
            )
            raise
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="app_connector", zpa_id=connector_id)
                .first()
            )
            if rec:
                rec.is_deleted = True
        audit_service.log(
            product="ZPA", operation="delete_connector", action="DELETE",
            status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector",
            resource_id=connector_id, resource_name=connector_name,
        )
        return True

    # ------------------------------------------------------------------
    # Connector groups (DB-first + mutations)
    # ------------------------------------------------------------------

    def list_connector_groups_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "app_connector_group", q)
        audit_service.log(
            product="ZPA", operation="list_connector_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="app_connector_group",
            details={"count": len(result)},
        )
        return result

    def create_connector_group(self, name: str, description: Optional[str] = None) -> Dict:
        from services.zpa_import_service import ZPAImportService
        kwargs: Dict = {"name": name, "enabled": True}
        if description:
            kwargs["description"] = description
        try:
            result = self.client.create_connector_group(**kwargs)
            group_id = str(result.get("id", ""))
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["app_connector_group"])
            row = self._get_db_row("app_connector_group", group_id)
            audit_service.log(
                product="ZPA", operation="create_connector_group", action="CREATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector_group",
                resource_id=group_id, resource_name=name,
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="create_connector_group", action="CREATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector_group",
                resource_name=name, error_message=str(exc),
            )
            raise

    def set_connector_group_enabled(self, group_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        group_name = group_id
        try:
            config = self.client.get_connector_group(group_id)
            group_name = config.get("name", group_id)
            config["enabled"] = enabled
            self.client.update_connector_group(group_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["app_connector_group"])
            row = self._get_db_row("app_connector_group", group_id)
            audit_service.log(
                product="ZPA", operation="toggle_connector_group", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector_group",
                resource_id=group_id, resource_name=group_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_connector_group", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector_group",
                resource_id=group_id, resource_name=group_name,
                error_message=str(exc),
            )
            raise

    def delete_connector_group(self, group_id: str, group_name: str) -> bool:  # TODO: test
        try:
            self.client.delete_connector_group(group_id)
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="delete_connector_group", action="DELETE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="app_connector_group",
                resource_id=group_id, resource_name=group_name,
                error_message=str(exc),
            )
            raise
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="app_connector_group", zpa_id=group_id)
                .first()
            )
            if rec:
                rec.is_deleted = True
        audit_service.log(
            product="ZPA", operation="delete_connector_group", action="DELETE",
            status="SUCCESS", tenant_id=self.tenant_id, resource_type="app_connector_group",
            resource_id=group_id, resource_name=group_name,
        )
        return True

    # ------------------------------------------------------------------
    # Service edges (DB-first + enable/disable)
    # ------------------------------------------------------------------

    def list_service_edges(self) -> List[Dict]:
        return self.list_service_edges_from_db()

    def _list_service_edges_live(self) -> List[Dict]:
        return self.client.list_service_edges()

    def list_service_edges_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "service_edge", q)
        audit_service.log(
            product="ZPA", operation="list_service_edges", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="service_edge",
            details={"count": len(result)},
        )
        return result

    def set_service_edge_enabled(self, edge_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        edge_name = edge_id
        try:
            config = self.client.get_service_edge(edge_id)
            edge_name = config.get("name", edge_id)
            config["enabled"] = enabled
            self.client.update_service_edge(edge_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["service_edge"])
            row = self._get_db_row("service_edge", edge_id)
            audit_service.log(
                product="ZPA", operation="toggle_service_edge", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="service_edge",
                resource_id=edge_id, resource_name=edge_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_service_edge", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="service_edge",
                resource_id=edge_id, resource_name=edge_name,
                error_message=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # PRA Portals (DB-first + mutations)
    # ------------------------------------------------------------------

    def list_pra_portals(self) -> List[Dict]:
        return self.list_pra_portals_from_db()

    def _list_pra_portals_live(self) -> List[Dict]:
        return self.client.list_pra_portals()

    def list_pra_portals_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "pra_portal", q)
        audit_service.log(
            product="ZPA", operation="list_pra_portals", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="pra_portal",
            details={"count": len(result)},
        )
        return result

    def create_pra_portal(
        self,
        name: str,
        domain: str,
        certificate_id: str,
        enabled: bool = True,
        description: Optional[str] = None,
        user_notification_enabled: bool = False,
        user_notification: Optional[str] = None,
    ) -> Dict:
        from services.zpa_import_service import ZPAImportService
        kwargs: Dict = {
            "name": name,
            "domain": domain,
            "certificate_id": certificate_id,
            "enabled": enabled,
            "user_notification_enabled": user_notification_enabled,
        }
        if description:
            kwargs["description"] = description
        if user_notification:
            kwargs["user_notification"] = user_notification
        try:
            result = self.client.create_pra_portal(**kwargs)
            portal_id = str(result.get("id", ""))
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["pra_portal"])
            row = self._get_db_row("pra_portal", portal_id)
            audit_service.log(
                product="ZPA", operation="create_pra_portal", action="CREATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="pra_portal",
                resource_id=portal_id, resource_name=name,
                details={"domain": domain, "certificate_id": certificate_id},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="create_pra_portal", action="CREATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="pra_portal",
                resource_name=name, error_message=str(exc),
            )
            raise

    def set_pra_portal_enabled(self, portal_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        portal_name = portal_id
        try:
            config = self.client.get_pra_portal(portal_id)
            portal_name = config.get("name", portal_id)
            config["enabled"] = enabled
            self.client.update_pra_portal(portal_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["pra_portal"])
            row = self._get_db_row("pra_portal", portal_id)
            audit_service.log(
                product="ZPA", operation="toggle_pra_portal", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="pra_portal",
                resource_id=portal_id, resource_name=portal_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_pra_portal", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="pra_portal",
                resource_id=portal_id, resource_name=portal_name,
                error_message=str(exc),
            )
            raise

    def delete_pra_portal(self, portal_id: str, portal_name: str) -> bool:  # TODO: test
        try:
            self.client.delete_pra_portal(portal_id)
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="delete_pra_portal", action="DELETE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="pra_portal",
                resource_id=portal_id, resource_name=portal_name,
                error_message=str(exc),
            )
            raise
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="pra_portal", zpa_id=portal_id)
                .first()
            )
            if rec:
                rec.is_deleted = True
        audit_service.log(
            product="ZPA", operation="delete_pra_portal", action="DELETE",
            status="SUCCESS", tenant_id=self.tenant_id, resource_type="pra_portal",
            resource_id=portal_id, resource_name=portal_name,
        )
        return True

    # ------------------------------------------------------------------
    # User Portals (DB-first + mutations)
    # ------------------------------------------------------------------

    def list_user_portals_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "user_portal", q)
        audit_service.log(
            product="ZPA", operation="list_user_portals", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="user_portal",
            details={"count": len(result), "source": "db"},
        )
        return result

    def set_user_portal_enabled(self, portal_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        portal_name = portal_id
        try:
            config = self.client.get_user_portal(portal_id)
            portal_name = config.get("name", portal_id)
            config["enabled"] = enabled
            self.client.update_user_portal(portal_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["user_portal"])
            row = self._get_db_row("user_portal", portal_id)
            audit_service.log(
                product="ZPA", operation="toggle_user_portal", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="user_portal",
                resource_id=portal_id, resource_name=portal_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_user_portal", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="user_portal",
                resource_id=portal_id, resource_name=portal_name,
                error_message=str(exc),
            )
            raise

    def delete_user_portal(self, portal_id: str, portal_name: str) -> bool:
        try:
            self.client.delete_user_portal(portal_id)
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="delete_user_portal", action="DELETE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="user_portal",
                resource_id=portal_id, resource_name=portal_name,
                error_message=str(exc),
            )
            raise
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="user_portal", zpa_id=portal_id)
                .first()
            )
            if rec:
                rec.is_deleted = True
        audit_service.log(
            product="ZPA", operation="delete_user_portal", action="DELETE",
            status="SUCCESS", tenant_id=self.tenant_id, resource_type="user_portal",
            resource_id=portal_id, resource_name=portal_name,
        )
        return True

    # ------------------------------------------------------------------
    # PRA Consoles (DB-first + mutations)
    # ------------------------------------------------------------------

    def list_pra_consoles_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "pra_console", q)
        audit_service.log(
            product="ZPA", operation="list_pra_consoles", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="pra_console",
            details={"count": len(result)},
        )
        return result

    def set_pra_console_enabled(self, console_id: str, enabled: bool) -> Dict:
        from services.zpa_import_service import ZPAImportService
        console_name = console_id
        try:
            config = self.client.get_pra_console(console_id)
            console_name = config.get("name", console_id)
            config["enabled"] = enabled
            self.client.update_pra_console(console_id, config)
            ZPAImportService(self.client, self.tenant_id).run(resource_types=["pra_console"])
            row = self._get_db_row("pra_console", console_id)
            audit_service.log(
                product="ZPA", operation="toggle_pra_console", action="UPDATE",
                status="SUCCESS", tenant_id=self.tenant_id, resource_type="pra_console",
                resource_id=console_id, resource_name=console_name,
                details={"enabled": enabled},
            )
            return row
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="toggle_pra_console", action="UPDATE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="pra_console",
                resource_id=console_id, resource_name=console_name,
                error_message=str(exc),
            )
            raise

    def delete_pra_console(self, console_id: str, console_name: str) -> bool:  # TODO: test
        try:
            self.client.delete_pra_console(console_id)
        except Exception as exc:
            audit_service.log(
                product="ZPA", operation="delete_pra_console", action="DELETE",
                status="FAILURE", tenant_id=self.tenant_id, resource_type="pra_console",
                resource_id=console_id, resource_name=console_name,
                error_message=str(exc),
            )
            raise
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="pra_console", zpa_id=console_id)
                .first()
            )
            if rec:
                rec.is_deleted = True
        audit_service.log(
            product="ZPA", operation="delete_pra_console", action="DELETE",
            status="SUCCESS", tenant_id=self.tenant_id, resource_type="pra_console",
            resource_id=console_id, resource_name=console_name,
        )
        return True

    # ------------------------------------------------------------------
    # Access Policy (DB-first, read-only)
    # ------------------------------------------------------------------

    def list_access_policy_rules_from_db(self, q: Optional[str] = None) -> List[Dict]:
        with get_session() as session:
            rows = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="policy_access", is_deleted=False)
                .all()
            )
            result = [{"zpa_id": r.zpa_id, "name": r.name, **(r.raw_config or {})} for r in rows]
        if q:
            result = [r for r in result if q.lower() in (r.get("name") or "").lower()]
        result.sort(key=lambda r: _rule_order_key(int(r.get("rule_order") or 0)))
        return result

    def export_access_policy_csv(self) -> str:  # TODO: test
        """Export all access policy rules as a CSV string.

        Uses _decode_conditions from zpa_policy_service for condition decoding.
        Column order matches CSV_FIELDNAMES from zpa_policy_service.
        """
        from services.zpa_policy_service import CSV_FIELDNAMES, _decode_conditions

        # Build scim_group_map from DB for SCIM_GROUP condition resolution
        with get_session() as session:
            all_idps = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="idp", is_deleted=False)
                .all()
            )
            idp_id_to_name: Dict[str, str] = {r.zpa_id: (r.name or "") for r in all_idps}

            all_scim_grps = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="scim_group", is_deleted=False)
                .all()
            )
            scim_group_map: Dict[str, Tuple[str, str]] = {}
            for rec in all_scim_grps:
                cfg = rec.raw_config or {}
                idp_id_val = str(cfg.get("idp_id") or cfg.get("idpId") or "")
                idp_n = idp_id_to_name.get(idp_id_val, "")
                if rec.zpa_id and rec.name:
                    scim_group_map[rec.zpa_id] = (idp_n, rec.name)

            rows = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type="policy_access", is_deleted=False)
                .all()
            )
            rules = [{"zpa_id": r.zpa_id, "name": r.name, **(r.raw_config or {})} for r in rows]

        rules.sort(key=lambda r: _rule_order_key(int(r.get("rule_order") or 0)))

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for rule in rules:
            decoded = _decode_conditions(rule, scim_group_map=scim_group_map)
            row_dict = {
                "id": rule.get("zpa_id", ""),
                "name": rule.get("name", ""),
                "action": (rule.get("action") or "").upper(),
                "description": rule.get("description", ""),
                "rule_order": rule.get("rule_order", ""),
                **decoded,
            }
            writer.writerow(row_dict)
        return output.getvalue()

    # ------------------------------------------------------------------
    # Identity (DB-only reads)
    # ------------------------------------------------------------------

    def list_saml_attributes_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "saml_attribute", q)
        audit_service.log(
            product="ZPA", operation="list_saml_attributes", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="saml_attribute",
            details={"count": len(result)},
        )
        return result

    def list_scim_attributes_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "scim_attribute", q)
        audit_service.log(
            product="ZPA", operation="list_scim_attributes", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="scim_attribute",
            details={"count": len(result)},
        )
        return result

    def list_scim_groups_from_db(self, q: Optional[str] = None) -> List[Dict]:
        result = _db_list(self.tenant_id, "scim_group", q)
        audit_service.log(
            product="ZPA", operation="list_scim_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="scim_group",
            details={"count": len(result)},
        )
        return result

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _get_db_row(self, resource_type: str, zpa_id: str) -> Dict:
        """Fetch a single row from the ZPAResource table and return it as a dict."""
        with get_session() as session:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self.tenant_id, resource_type=resource_type, zpa_id=zpa_id)
                .first()
            )
            if rec:
                return {"zpa_id": rec.zpa_id, "name": rec.name, **(rec.raw_config or {})}
        return {"zpa_id": zpa_id}

    @staticmethod
    def _domain_matches(domain: str, base: str) -> bool:
        d = domain.replace("*.", "")
        return d == base or d.endswith("." + base)

    def _domain_matches_any(self, clientless_apps: List[Dict], base: str) -> bool:
        return any(self._domain_matches(ca.get("domain", ""), base) for ca in clientless_apps)

    def _is_cert_in_use(self, cert_id: str, exclude: Dict[str, Set[str]]) -> bool:
        for app in self.client.list_applications("BROWSER_ACCESS"):
            if app["id"] in exclude.get("apps", set()):
                continue
            for ca in app.get("clientlessApps", []):
                if str(ca.get("certificateId", "")) == cert_id:
                    return True
        for portal in self._list_pra_portals_live():
            if portal["id"] in exclude.get("pra_portals", set()):
                continue
            if str(portal.get("certificateId", "")) == cert_id:
                return True
        return False

    def _record_certificate(self, zpa_cert_id: str, name: str, domain: str) -> None:
        if self.tenant_id is None:
            return
        try:
            with get_session() as session:
                cert = Certificate(
                    tenant_id=self.tenant_id,
                    zpa_cert_id=zpa_cert_id,
                    name=name,
                    domain=domain,
                )
                session.add(cert)
        except Exception:
            pass  # DB tracking is best-effort; never fail the main operation

    def _mark_certificate_replaced(self, old_zpa_id: str, new_zpa_id: str) -> None:
        if self.tenant_id is None:
            return
        try:
            with get_session() as session:
                old = session.query(Certificate).filter_by(
                    tenant_id=self.tenant_id, zpa_cert_id=old_zpa_id, is_active=True
                ).first()
                new = session.query(Certificate).filter_by(
                    tenant_id=self.tenant_id, zpa_cert_id=new_zpa_id
                ).first()
                if old:
                    old.is_active = False
                    if new:
                        old.replaced_by_id = new.id
        except Exception:
            pass
