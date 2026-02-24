"""ZPA business logic layer.

Wraps ZPAClient with:
  - Audit logging for every mutating operation
  - Certificate tracking in the local database
  - Higher-level workflows (e.g. full certificate rotation)
"""

import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from db.database import get_session
from db.models import Certificate
from lib.zpa_client import ZPAClient
from services import audit_service


class ZPAService:
    def __init__(self, client: ZPAClient, tenant_id: Optional[int] = None):
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

        # Step 3 — update PRA Portals
        for portal in self.client.list_pra_portals():
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

    def list_applications(self, app_type: str = "BROWSER_ACCESS") -> List[Dict]:
        result = self.client.list_applications(app_type)
        audit_service.log(
            product="ZPA", operation="list_applications", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="application",
            details={"count": len(result), "app_type": app_type},
        )
        return result

    # ------------------------------------------------------------------
    # PRA Portal helpers
    # ------------------------------------------------------------------

    def list_pra_portals(self) -> List[Dict]:
        result = self.client.list_pra_portals()
        audit_service.log(
            product="ZPA", operation="list_pra_portals", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="pra_portal",
            details={"count": len(result) if isinstance(result, list) else None},
        )
        return result

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

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
        for portal in self.client.list_pra_portals():
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
