import requests
from typing import Any, Dict, List, Optional

from .auth import ZscalerAuth


class ZIAClient:
    """Low-level HTTP client for the Zscaler Internet Access (ZIA) OneAPI.

    NOTE: ZIA configuration changes do not take effect until you call activate().
    Always call activate() after making changes, or use the context manager pattern
    in services/zia_service.py which handles activation automatically.
    """

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._base = f"{oneapi_base_url.rstrip('/')}/zia/api/v1"
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth.get_token()}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        r = self._session.get(f"{self._base}{path}", headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: Dict = None) -> Any:
        r = self._session.post(f"{self._base}{path}", headers=self._headers(), json=payload or {}, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else None

    def _put(self, path: str, payload: Dict) -> Any:
        r = self._session.put(f"{self._base}{path}", headers=self._headers(), json=payload, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else None

    def _delete(self, path: str) -> bool:
        r = self._session.delete(f"{self._base}{path}", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return True

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def get_activation_status(self) -> Dict:
        return self._get("/status")

    def activate(self) -> Dict:
        """Commit all pending ZIA configuration changes."""
        return self._post("/status/activate")

    # ------------------------------------------------------------------
    # URL Categories
    # ------------------------------------------------------------------

    def list_url_categories(self, include_built_in: bool = False) -> List[Dict]:
        params = {"includeParentCategory": "true"} if include_built_in else {}
        return self._get("/urlCategories", params=params)

    def list_url_categories_lite(self) -> List[Dict]:
        return self._get("/urlCategories/lite")

    def get_url_category(self, category_id: str) -> Dict:
        return self._get(f"/urlCategories/{category_id}")

    def create_url_category(self, config: Dict) -> Dict:
        return self._post("/urlCategories", config)

    def update_url_category(self, category_id: str, config: Dict) -> Dict:
        return self._put(f"/urlCategories/{category_id}", config)

    def delete_url_category(self, category_id: str) -> bool:
        return self._delete(f"/urlCategories/{category_id}")

    def url_lookup(self, urls: List[str]) -> List[Dict]:
        return self._post("/urlLookup", urls)

    # ------------------------------------------------------------------
    # URL Filtering Policies
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        return self._get("/urlFilteringRules")

    def get_url_filtering_rule(self, rule_id: str) -> Dict:
        return self._get(f"/urlFilteringRules/{rule_id}")

    def create_url_filtering_rule(self, config: Dict) -> Dict:
        return self._post("/urlFilteringRules", config)

    def update_url_filtering_rule(self, rule_id: str, config: Dict) -> Dict:
        return self._put(f"/urlFilteringRules/{rule_id}", config)

    def delete_url_filtering_rule(self, rule_id: str) -> bool:
        return self._delete(f"/urlFilteringRules/{rule_id}")

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def list_users(self, name: Optional[str] = None, group: Optional[str] = None, dept: Optional[str] = None) -> List[Dict]:
        params = {}
        if name:
            params["name"] = name
        if group:
            params["group"] = group
        if dept:
            params["dept"] = dept
        return self._get("/users", params=params)

    def get_user(self, user_id: str) -> Dict:
        return self._get(f"/users/{user_id}")

    def create_user(self, config: Dict) -> Dict:
        return self._post("/users", config)

    def update_user(self, user_id: str, config: Dict) -> Dict:
        return self._put(f"/users/{user_id}", config)

    def delete_user(self, user_id: str) -> bool:
        return self._delete(f"/users/{user_id}")

    def list_departments(self) -> List[Dict]:
        return self._get("/departments")

    def list_groups(self) -> List[Dict]:
        return self._get("/groups")

    # ------------------------------------------------------------------
    # Firewall Policies
    # ------------------------------------------------------------------

    def list_firewall_rules(self) -> List[Dict]:
        return self._get("/firewallFilteringRules")

    def get_firewall_rule(self, rule_id: str) -> Dict:
        return self._get(f"/firewallFilteringRules/{rule_id}")

    def create_firewall_rule(self, config: Dict) -> Dict:
        return self._post("/firewallFilteringRules", config)

    def update_firewall_rule(self, rule_id: str, config: Dict) -> Dict:
        return self._put(f"/firewallFilteringRules/{rule_id}", config)

    def delete_firewall_rule(self, rule_id: str) -> bool:
        return self._delete(f"/firewallFilteringRules/{rule_id}")

    # ------------------------------------------------------------------
    # Location Management
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        return self._get("/locations")

    def list_locations_lite(self) -> List[Dict]:
        return self._get("/locations/lite")

    def get_location(self, location_id: str) -> Dict:
        return self._get(f"/locations/{location_id}")

    def create_location(self, config: Dict) -> Dict:
        return self._post("/locations", config)

    def update_location(self, location_id: str, config: Dict) -> Dict:
        return self._put(f"/locations/{location_id}", config)

    def delete_location(self, location_id: str) -> bool:
        return self._delete(f"/locations/{location_id}")

    # ------------------------------------------------------------------
    # Admin Audit Logs
    # ------------------------------------------------------------------

    def request_audit_log(self, filter_config: Dict) -> Dict:
        return self._post("/auditlogEntryReport", filter_config)

    def get_audit_log_status(self) -> Dict:
        return self._get("/auditlogEntryReport")

    # ------------------------------------------------------------------
    # Security Policy (Allowlist / Denylist)
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        return self._get("/security")

    def update_allowlist(self, config: Dict) -> Dict:
        return self._put("/security", config)

    def get_denylist(self) -> Dict:
        return self._get("/security/advanced")

    def update_denylist(self, config: Dict) -> Dict:
        return self._put("/security/advanced", config)

    # ------------------------------------------------------------------
    # Rule Labels
    # ------------------------------------------------------------------

    def list_rule_labels(self) -> List[Dict]:
        return self._get("/ruleLabels")

    def create_rule_label(self, name: str, description: str = "") -> Dict:
        return self._post("/ruleLabels", {"name": name, "description": description})

    # ------------------------------------------------------------------
    # Admin & Role Management
    # ------------------------------------------------------------------

    def list_admin_users(self) -> List[Dict]:
        return self._get("/adminUsers")

    def list_admin_roles(self) -> List[Dict]:
        return self._get("/adminRoles/lite")
