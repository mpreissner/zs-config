import time
import requests
from typing import Optional


class ZscalerAuth:
    """OAuth2 client_credentials token manager shared across all Zscaler products.

    All Zscaler OneAPI products authenticate via ZIdentity using the same
    client_credentials flow. A single instance of this class can be passed
    to multiple product clients (ZPA, ZIA, ZCC, etc.) and tokens are cached
    and refreshed automatically.
    """

    AUDIENCE = "https://api.zscaler.com"

    def __init__(self, zidentity_base_url: str, client_id: str, client_secret: str):
        self.token_url = f"{zidentity_base_url.rstrip('/')}/oauth2/v1/token"
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._expiry: float = 0

    def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._token and time.time() < self._expiry:
            return self._token
        self._refresh()
        return self._token

    def _refresh(self) -> None:
        resp = requests.post(
            self.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": self.AUDIENCE,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Refresh at 90% of actual expiry to avoid edge-case failures
        self._expiry = time.time() + (data.get("expires_in", 3600) * 0.9)
