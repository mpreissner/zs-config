import time
from typing import Dict, List, Optional

import requests
from zscaler import ZscalerClient

from .auth import ZscalerAuth


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dict(item) -> dict:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, "as_dict"):
        return item.as_dict()
    return vars(item)


def _zid_list(result) -> list:
    """Extract a plain list of dicts from a ZIdentity SDK response.

    The ZIdentity SDK returns model wrapper objects (Users, Groups, etc.)
    rather than bare lists. This helper unpacks them by inspecting the
    as_dict() output and pulling out the first list-valued field.
    """
    if result is None:
        return []
    if isinstance(result, list):
        return [_to_dict(i) for i in result]
    if hasattr(result, "as_dict"):
        d = result.as_dict()
        if isinstance(d, list):
            return [_to_dict(i) for i in d]
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, list):
                    return [_to_dict(i) for i in v]
    # Last resort: try direct iteration
    try:
        return [_to_dict(i) for i in result]
    except TypeError:
        return []


class ZIdentityClient:
    """SDK adapter for the Zscaler Identity (ZIdentity) API.

    Most operations use zscaler-sdk-python. Endpoints not yet in the SDK,
    and all operations for GovCloud tenants, use direct HTTP with a cached
    OAuth2 token acquired via the client_credentials flow.

    GovCloud note: the ZscalerClient SDK constructs the token URL as
    {vanityDomain}.zslogin.net, which fails for GovCloud tenants whose
    ZIdentity URL is {vanityDomain}.zidentitygov.us. When self._govcloud
    is True, all SDK-backed methods fall back to direct HTTP using
    _direct_get/_direct_post/_direct_put/_direct_delete.
    """

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._direct_base = f"{oneapi_base_url}/ziam/admin/api/v1"
        self._govcloud = auth.govcloud
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Direct HTTP helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = requests.post(
            f"{self.auth.zidentity_base_url}/oauth2/v1/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.auth.client_id,
                "client_secret": self.auth.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _direct_get(self, path: str, params: Optional[dict] = None) -> Dict:
        resp = requests.get(
            f"{self._direct_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _direct_post(self, path: str, json: Optional[dict] = None) -> Dict:
        resp = requests.post(
            f"{self._direct_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json=json,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _direct_put(self, path: str, json: Optional[dict] = None) -> Dict:
        resp = requests.put(
            f"{self._direct_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json=json,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _direct_delete(self, path: str) -> None:
        resp = requests.delete(
            f"{self._direct_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            timeout=15,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(
        self,
        login_name: Optional[str] = None,
        display_name: Optional[str] = None,
        primary_email: Optional[str] = None,
        domain_name: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict]:
        params: Dict = {"limit": limit}
        if login_name:
            params["loginname[like]"] = login_name
        if display_name:
            params["displayname[like]"] = display_name
        if primary_email:
            params["primaryemail[like]"] = primary_email
        if domain_name:
            params["domainname"] = domain_name
        if self._govcloud:
            return _zid_list(self._direct_get("users", params=params))
        result, resp, err = self._sdk.zidentity.users.list_users(query_params=params)
        return _zid_list(_unwrap(result, resp, err))

    def get_user(self, user_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"users/{user_id}")
        result, resp, err = self._sdk.zidentity.users.get_user(user_id)
        return _to_dict(_unwrap(result, resp, err))

    def list_user_groups(self, user_id: str) -> List[Dict]:
        if self._govcloud:
            return _zid_list(self._direct_get(f"users/{user_id}/groups"))
        result, resp, err = self._sdk.zidentity.users.list_user_group_details(user_id)
        return _zid_list(_unwrap(result, resp, err))

    def get_admin_entitlement(self, user_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"users/{user_id}/entitlements/admin")
        result, resp, err = self._sdk.zidentity.user_entitlement.get_admin_entitlement(user_id)
        return _to_dict(_unwrap(result, resp, err))

    def get_service_entitlement(self, user_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"users/{user_id}/entitlements/service")
        result, resp, err = self._sdk.zidentity.user_entitlement.get_service_entitlement(user_id)
        return _to_dict(_unwrap(result, resp, err))

    # Direct HTTP — not yet in SDK
    def create_user(self, payload: Dict) -> Dict:
        return self._direct_post("users", json=payload)

    def update_user(self, user_id: str, payload: Dict) -> Dict:
        return self._direct_put(f"users/{user_id}", json=payload)

    def delete_user(self, user_id: str) -> None:
        self._direct_delete(f"users/{user_id}")

    def reset_password(self, user_id: str) -> Dict:
        return self._direct_post(f"users/{user_id}:resetpassword")

    def update_password(
        self, user_id: str, password: str, reset_on_login: bool = False
    ) -> Dict:
        return self._direct_put(
            f"users/{user_id}:updatepassword",
            json={"password": password, "resetPwdOnLogin": reset_on_login},
        )

    def skip_mfa(self, user_id: str, until_timestamp: int) -> Dict:
        return self._direct_post(
            f"users/{user_id}:setskipmfa",
            json={"timestamp": until_timestamp},
        )

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def list_groups(
        self,
        name: Optional[str] = None,
        exclude_dynamic: bool = False,
        limit: int = 500,
    ) -> List[Dict]:
        params: Dict = {"limit": limit}
        if name:
            params["name[like]"] = name
        if exclude_dynamic:
            params["excludedynamicgroups"] = "true"
        if self._govcloud:
            return _zid_list(self._direct_get("groups", params=params))
        result, resp, err = self._sdk.zidentity.groups.list_groups(query_params=params)
        return _zid_list(_unwrap(result, resp, err))

    def get_group(self, group_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"groups/{group_id}")
        result, resp, err = self._sdk.zidentity.groups.get_group(int(group_id))
        return _to_dict(_unwrap(result, resp, err))

    def list_group_members(self, group_id: str, limit: int = 500) -> List[Dict]:
        if self._govcloud:
            return _zid_list(self._direct_get(f"groups/{group_id}/users", params={"limit": limit}))
        result, resp, err = self._sdk.zidentity.groups.list_group_users_details(
            group_id, query_params={"limit": limit}
        )
        return _zid_list(_unwrap(result, resp, err))

    def add_user_to_group(self, group_id: str, user_id: str) -> Dict:
        if self._govcloud:
            return self._direct_put(f"groups/{group_id}/users/{user_id}")
        result, resp, err = self._sdk.zidentity.groups.add_user_to_group(group_id, user_id)
        return _to_dict(_unwrap(result, resp, err))

    def remove_user_from_group(self, group_id: str, user_id: str) -> Dict:
        if self._govcloud:
            self._direct_delete(f"groups/{group_id}/users/{user_id}")
            return {}
        result, resp, err = self._sdk.zidentity.groups.remove_user_from_group(group_id, user_id)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # API Clients
    # ------------------------------------------------------------------

    def list_api_clients(
        self, name: Optional[str] = None, limit: int = 500
    ) -> List[Dict]:
        params: Dict = {"limit": limit}
        if name:
            params["name[like]"] = name
        if self._govcloud:
            return _zid_list(self._direct_get("apiclients", params=params))
        result, resp, err = self._sdk.zidentity.api_client.list_api_clients(query_params=params)
        return _zid_list(_unwrap(result, resp, err))

    def get_api_client(self, client_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"apiclients/{client_id}")
        result, resp, err = self._sdk.zidentity.api_client.get_api_client(client_id)
        return _to_dict(_unwrap(result, resp, err))

    def get_api_client_secrets(self, client_id: str) -> Dict:
        if self._govcloud:
            return self._direct_get(f"apiclients/{client_id}/secrets")
        result, resp, err = self._sdk.zidentity.api_client.get_api_client_secret(client_id)
        return _to_dict(_unwrap(result, resp, err))

    def add_api_client_secret(
        self, client_id: str, expires_at: Optional[str] = None
    ) -> Dict:
        if self._govcloud:
            body = {"expiresAt": expires_at} if expires_at else {}
            return self._direct_post(f"apiclients/{client_id}/secrets", json=body)
        kwargs = {}
        if expires_at:
            kwargs["expiresAt"] = expires_at
        result, resp, err = self._sdk.zidentity.api_client.add_api_client_secret(
            client_id, **kwargs
        )
        return _to_dict(_unwrap(result, resp, err))

    def delete_api_client_secret(self, client_id: str, secret_id: str) -> bool:
        if self._govcloud:
            self._direct_delete(f"apiclients/{client_id}/secrets/{secret_id}")
            return True
        result, resp, err = self._sdk.zidentity.api_client.delete_api_client_secret(
            client_id, secret_id
        )
        _unwrap(result, resp, err)
        return True

    def delete_api_client(self, client_id: str) -> bool:
        if self._govcloud:
            self._direct_delete(f"apiclients/{client_id}")
            return True
        result, resp, err = self._sdk.zidentity.api_client.delete_api_client(client_id)
        _unwrap(result, resp, err)
        return True
