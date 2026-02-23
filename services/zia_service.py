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
        return self.client.get_activation_status()

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
        return self.client.list_url_categories_lite()

    def get_url_category(self, category_id: str) -> Dict:
        return self.client.get_url_category(category_id)

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
        return self.client.url_lookup(urls)

    # ------------------------------------------------------------------
    # URL Filtering Rules
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        return self.client.list_url_filtering_rules()

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
        return self.client.list_users(name=name)

    def list_departments(self) -> List[Dict]:
        return self.client.list_departments()

    def list_groups(self) -> List[Dict]:
        return self.client.list_groups()

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        return self.client.list_locations_lite()

    def get_location(self, location_id: str) -> Dict:
        return self.client.get_location(location_id)

    # ------------------------------------------------------------------
    # Security Policy
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        return self.client.get_allowlist()

    def get_denylist(self) -> Dict:
        return self.client.get_denylist()
