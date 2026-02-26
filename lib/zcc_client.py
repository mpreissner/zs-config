from typing import Dict, List, Optional

from zscaler import ZscalerClient

from .auth import ZscalerAuth

# Integer → label mappings used by both the client and the service layer
OS_TYPE_LABELS: Dict[int, str] = {
    1: "iOS",
    2: "Android",
    3: "Windows",
    4: "macOS",
    5: "Linux",
}

REGISTRATION_STATE_LABELS: Dict[int, str] = {
    0: "All (except Removed)",
    1: "Registered",
    3: "Removal Pending",
    4: "Unregistered",
    5: "Removed",
    6: "Quarantined",
}


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dicts(items) -> list:
    if not items:
        return []
    return [
        i if isinstance(i, dict) else (i.as_dict() if hasattr(i, "as_dict") else vars(i))
        for i in items
    ]


def _to_dict(item) -> dict:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, "as_dict"):
        return item.as_dict()
    return vars(item)


class ZCCClient:
    """SDK adapter for the Zscaler Client Connector (ZCC) API."""

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(
        self,
        username: Optional[str] = None,
        os_type: Optional[int] = None,
        page: int = 1,
        page_size: int = 500,
    ) -> List[Dict]:
        params: Dict = {"page": page, "pageSize": page_size}
        if username:
            params["username"] = username
        if os_type is not None:
            params["osType"] = os_type
        result, resp, err = self._sdk.zcc.devices.list_devices(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    def get_device_details(
        self,
        username: Optional[str] = None,
        udid: Optional[str] = None,
    ) -> Dict:
        params: Dict = {}
        if username:
            params["username"] = username
        if udid:
            params["udid"] = udid
        result, resp, err = self._sdk.zcc.devices.get_device_details(query_params=params)
        return _to_dict(_unwrap(result, resp, err))

    def remove_devices(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
        client_connector_version: Optional[List[str]] = None,
        page_size: int = 500,
    ) -> Dict:
        payload: Dict = {}
        if username:
            payload["userName"] = username
        if udids:
            payload["udids"] = udids
        if os_type is not None:
            payload["osType"] = os_type
        if client_connector_version:
            payload["clientConnectorVersion"] = client_connector_version
        result, resp, err = self._sdk.zcc.devices.remove_devices(
            query_params={"pageSize": page_size}, **payload
        )
        return _to_dict(_unwrap(result, resp, err))

    def force_remove_devices(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
        client_connector_version: Optional[List[str]] = None,
        page_size: int = 500,
    ) -> Dict:
        payload: Dict = {}
        if username:
            payload["userName"] = username
        if udids:
            payload["udids"] = udids
        if os_type is not None:
            payload["osType"] = os_type
        if client_connector_version:
            payload["clientConnectorVersion"] = client_connector_version
        result, resp, err = self._sdk.zcc.devices.force_remove_devices(
            query_params={"pageSize": page_size}, **payload
        )
        return _to_dict(_unwrap(result, resp, err))

    def download_devices(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        params: Dict = {}
        if os_types:
            params["osTypes"] = os_types
        if registration_types:
            params["registrationTypes"] = registration_types
        result, resp, err = self._sdk.zcc.devices.download_devices(
            query_params=params, filename=filename
        )
        return _unwrap(result, resp, err)

    def download_service_status(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        params: Dict = {}
        if os_types:
            params["osTypes"] = os_types
        if registration_types:
            params["registrationTypes"] = registration_types
        result, resp, err = self._sdk.zcc.devices.download_service_status(
            query_params=params, filename=filename
        )
        return _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    def get_otp(self, udid: str) -> Dict:
        result, resp, err = self._sdk.zcc.secrets.get_otp(query_params={"udid": udid})
        return _to_dict(_unwrap(result, resp, err))

    def get_passwords(self, username: str, os_type: int) -> Dict:
        result, resp, err = self._sdk.zcc.secrets.get_passwords(
            query_params={"username": username, "osType": os_type}
        )
        return _to_dict(_unwrap(result, resp, err))
