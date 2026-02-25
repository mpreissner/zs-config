"""ZIA business logic layer.

Wraps ZIAClient with audit logging and higher-level workflows.

IMPORTANT: ZIA requires explicit activation after config changes.
Use the auto_activate=True parameter (default) to activate automatically,
or call activate() manually when batching multiple changes.
"""

from typing import Dict, List, Optional

from lib.zia_client import ZIAClient
from services import audit_service


class ZIAService:
    def __init__(self, client: ZIAClient, tenant_id: Optional[int] = None):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def get_activation_status(self) -> Dict:
        result = self.client.get_activation_status()
        audit_service.log(
            product="ZIA", operation="get_activation_status", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="configuration",
            details={"status": result.get("status")},
        )
        return result

    def activate(self) -> Dict:
        """Commit all pending ZIA configuration changes."""
        result = self.client.activate()
        audit_service.log(
            product="ZIA",
            operation="activate",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="configuration",
            details=result,
        )
        return result

    # ------------------------------------------------------------------
    # URL Categories
    # ------------------------------------------------------------------

    def list_url_categories(self) -> List[Dict]:
        result = self.client.list_url_categories_lite()
        audit_service.log(
            product="ZIA", operation="list_url_categories", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            details={"count": len(result)},
        )
        return result

    def get_url_category(self, category_id: str) -> Dict:
        result = self.client.get_url_category(category_id)
        audit_service.log(
            product="ZIA", operation="get_url_category", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            resource_id=category_id, resource_name=result.get("name"),
        )
        return result

    def create_url_category(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_url_category(config)
        audit_service.log(
            product="ZIA",
            operation="create_url_category",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_category",
            resource_id=result.get("id"),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        return result

    def update_url_category(self, category_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.update_url_category(category_id, config)
        audit_service.log(
            product="ZIA",
            operation="update_url_category",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_category",
            resource_id=category_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        return result

    def url_lookup(self, urls: List[str]) -> List[Dict]:
        """Look up the category classifications for a list of URLs."""
        result = self.client.url_lookup(urls)
        audit_service.log(
            product="ZIA", operation="url_lookup", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url",
            details={"urls": urls},
        )
        return result

    # ------------------------------------------------------------------
    # URL Filtering Rules
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        result = self.client.list_url_filtering_rules()
        audit_service.log(
            product="ZIA", operation="list_url_filtering_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_filtering_rule",
            details={"count": len(result)},
        )
        return result

    def create_url_filtering_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_url_filtering_rule(config)
        audit_service.log(
            product="ZIA",
            operation="create_url_filtering_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_filtering_rule",
            resource_id=result.get("id"),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        return result

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def list_users(self, name: Optional[str] = None) -> List[Dict]:
        result = self.client.list_users(name=name)
        audit_service.log(
            product="ZIA", operation="list_users", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="user",
            details={"count": len(result)},
        )
        return result

    def list_departments(self) -> List[Dict]:
        result = self.client.list_departments()
        audit_service.log(
            product="ZIA", operation="list_departments", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="department",
            details={"count": len(result)},
        )
        return result

    def list_groups(self) -> List[Dict]:
        result = self.client.list_groups()
        audit_service.log(
            product="ZIA", operation="list_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="group",
            details={"count": len(result)},
        )
        return result

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        result = self.client.list_locations_lite()
        audit_service.log(
            product="ZIA", operation="list_locations", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="location",
            details={"count": len(result)},
        )
        return result

    def get_location(self, location_id: str) -> Dict:
        result = self.client.get_location(location_id)
        audit_service.log(
            product="ZIA", operation="get_location", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="location",
            resource_id=location_id, resource_name=result.get("name"),
        )
        return result

    # ------------------------------------------------------------------
    # Security Policy
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        result = self.client.get_allowlist()
        audit_service.log(
            product="ZIA", operation="get_allowlist", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="allowlist",
        )
        return result

    def get_denylist(self) -> Dict:
        result = self.client.get_denylist()
        audit_service.log(
            product="ZIA", operation="get_denylist", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="denylist",
        )
        return result
