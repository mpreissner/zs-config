import requests
from typing import Any, Dict, List, Optional

from .auth import ZscalerAuth


class ZPAClient:
    """Low-level HTTP client for the Zscaler Private Access (ZPA) OneAPI.

    Handles authentication headers, base URL construction, and raw HTTP
    operations. Business logic lives in services/zpa_service.py.
    """

    def __init__(
        self,
        auth: ZscalerAuth,
        customer_id: str,
        oneapi_base_url: str = "https://api.zsapi.net",
    ):
        self.auth = auth
        self.customer_id = customer_id
        base = f"{oneapi_base_url.rstrip('/')}/zpa/mgmtconfig"
        self._v1 = f"{base}/v1/admin/customers/{customer_id}"
        self._v2 = f"{base}/v2/admin/customers/{customer_id}"
        self._userconfig = f"{oneapi_base_url.rstrip('/')}/zpa/userconfig/v1/customers/{customer_id}"
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

    def _get(self, url: str, params: Optional[Dict] = None) -> Any:
        r = self._session.get(url, headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, url: str, payload: Dict) -> Any:
        r = self._session.post(url, headers=self._headers(), json=payload, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else None

    def _put(self, url: str, payload: Dict) -> bool:
        r = self._session.put(url, headers=self._headers(), json=payload, timeout=30)
        r.raise_for_status()
        return r.status_code == 204

    def _delete(self, url: str) -> bool:
        r = self._session.delete(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.status_code == 204

    # ------------------------------------------------------------------
    # Certificates
    # ------------------------------------------------------------------

    def list_certificates(self, page: int = 1, page_size: int = 500) -> List[Dict]:
        data = self._get(f"{self._v1}/certificate", params={"page": page, "pagesize": page_size})
        return data.get("list", [])

    def list_issued_certificates(self) -> List[Dict]:
        """v2 endpoint — returns only Zscaler-issued certificates."""
        data = self._get(f"{self._v2}/certificate/issued")
        return data.get("list", [])

    def get_certificate(self, cert_id: str) -> Optional[Dict]:
        try:
            return self._get(f"{self._v1}/certificate/{cert_id}")
        except requests.HTTPError:
            return None

    def upload_certificate(self, name: str, cert_blob: str, description: str = "") -> Dict:
        """Upload a certificate + private key (combined PEM) to ZPA."""
        return self._post(
            f"{self._v1}/certificate",
            {"name": name, "description": description, "certBlob": cert_blob},
        )

    def delete_certificate(self, cert_id: str) -> bool:
        return self._delete(f"{self._v1}/certificate/{cert_id}")

    # ------------------------------------------------------------------
    # Application Segments
    # ------------------------------------------------------------------

    def list_applications(self, app_type: str = "BROWSER_ACCESS") -> List[Dict]:
        r = self._session.get(
            f"{self._v1}/application/getAppsByType",
            headers=self._headers(),
            params={"applicationType": app_type},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("list", [])

    def get_application(self, app_id: str) -> Dict:
        return self._get(f"{self._v1}/application/{app_id}")

    def create_application(self, config: Dict) -> Dict:
        return self._post(f"{self._v1}/application", config)

    def update_application(self, app_id: str, config: Dict) -> bool:
        return self._put(f"{self._v1}/application/{app_id}", config)

    def delete_application(self, app_id: str) -> bool:
        return self._delete(f"{self._v1}/application/{app_id}")

    # ------------------------------------------------------------------
    # PRA Portals
    # ------------------------------------------------------------------

    def list_pra_portals(self) -> List[Dict]:
        r = self._session.get(f"{self._v1}/praPortal", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def get_pra_portal(self, portal_id: str) -> Dict:
        return self._get(f"{self._v1}/praPortal/{portal_id}")

    def create_pra_portal(self, config: Dict) -> Dict:
        return self._post(f"{self._v1}/praPortal", config)

    def update_pra_portal(self, portal_id: str, config: Dict) -> bool:
        return self._put(f"{self._v1}/praPortal/{portal_id}", config)

    def delete_pra_portal(self, portal_id: str) -> bool:
        return self._delete(f"{self._v1}/praPortal/{portal_id}")

    # ------------------------------------------------------------------
    # PRA Consoles
    # ------------------------------------------------------------------

    def list_pra_consoles(self) -> List[Dict]:
        data = self._get(f"{self._v1}/praConsole")
        return data.get("list", [])

    def get_pra_console(self, console_id: str) -> Dict:
        return self._get(f"{self._v1}/praConsole/{console_id}")

    # ------------------------------------------------------------------
    # App Connectors & Groups
    # ------------------------------------------------------------------

    def list_connectors(self) -> List[Dict]:
        data = self._get(f"{self._v1}/connector")
        return data.get("list", [])

    def list_connector_groups(self) -> List[Dict]:
        data = self._get(f"{self._v1}/appConnectorGroup")
        return data.get("list", [])

    def list_server_groups(self) -> List[Dict]:
        data = self._get(f"{self._v1}/serverGroup")
        return data.get("list", [])

    def get_connector_group(self, group_id: str) -> Dict:
        return self._get(f"{self._v1}/appConnectorGroup/{group_id}")

    # ------------------------------------------------------------------
    # Segment Groups
    # ------------------------------------------------------------------

    def list_segment_groups(self) -> List[Dict]:
        data = self._get(f"{self._v1}/segmentGroup")
        return data.get("list", [])

    def get_segment_group(self, group_id: str) -> Dict:
        return self._get(f"{self._v1}/segmentGroup/{group_id}")

    def create_segment_group(self, config: Dict) -> Dict:
        return self._post(f"{self._v1}/segmentGroup", config)

    def update_segment_group(self, group_id: str, config: Dict) -> bool:
        return self._put(f"{self._v1}/segmentGroup/{group_id}", config)

    def delete_segment_group(self, group_id: str) -> bool:
        return self._delete(f"{self._v1}/segmentGroup/{group_id}")

    # ------------------------------------------------------------------
    # Policy Sets
    # ------------------------------------------------------------------

    def get_policy_set(self, policy_type: str) -> Dict:
        return self._get(f"{self._v1}/policySet/policyType/{policy_type}")

    def list_policy_rules(self, policy_type: str) -> List[Dict]:
        data = self._get(f"{self._v1}/policySet/rules/policyType/{policy_type}")
        return data.get("list", [])

    # ------------------------------------------------------------------
    # IdP / SAML / SCIM
    # ------------------------------------------------------------------

    def list_idp(self) -> List[Dict]:
        data = self._get(f"{self._v2}/idp")
        return data.get("list", [])

    def list_saml_attributes(self, idp_id: Optional[str] = None) -> List[Dict]:
        if idp_id:
            data = self._get(f"{self._v1}/samlAttribute/idp/{idp_id}")
        else:
            data = self._get(f"{self._v2}/samlAttribute")
        return data.get("list", [])

    def list_scim_groups(self, idp_id: str) -> List[Dict]:
        data = self._get(f"{self._userconfig}/scimgroup/idpId/{idp_id}")
        return data.get("list", [])

    # ------------------------------------------------------------------
    # Microtenants
    # ------------------------------------------------------------------

    def list_microtenants(self) -> List[Dict]:
        data = self._get(f"{self._v1}/microtenants")
        return data.get("list", [])

    def get_microtenant_summary(self) -> List[Dict]:
        data = self._get(f"{self._v1}/microtenants/summary")
        return data.get("list", [])

    # ------------------------------------------------------------------
    # Enrollment Certificates
    # ------------------------------------------------------------------

    def list_enrollment_certificates(self) -> List[Dict]:
        data = self._get(f"{self._v2}/enrollmentCert")
        return data.get("list", [])

    # ------------------------------------------------------------------
    # Privileged Credentials
    # ------------------------------------------------------------------

    def list_credentials(self) -> List[Dict]:
        data = self._get(f"{self._v1}/credential")
        return data.get("list", [])

    def get_credential(self, credential_id: str) -> Dict:
        return self._get(f"{self._v1}/credential/{credential_id}")

    def create_credential(self, config: Dict) -> Dict:
        return self._post(f"{self._v1}/credential", config)

    def update_credential(self, credential_id: str, config: Dict) -> bool:
        return self._put(f"{self._v1}/credential/{credential_id}", config)

    def delete_credential(self, credential_id: str) -> bool:
        return self._delete(f"{self._v1}/credential/{credential_id}")
