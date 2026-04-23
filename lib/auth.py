import threading
import time

import requests
from urllib.parse import urlparse

# Module-level token cache: key=(client_id, zidentity_base_url) → (token, expires_at)
_token_cache: dict = {}
_token_lock = threading.Lock()


class ZscalerAuth:
    """Credentials holder for Zscaler OneAPI.

    Provides client_id, client_secret, and vanity_domain to the SDK.
    Token acquisition and refresh are handled internally by zscaler-sdk-python.
    """

    def __init__(self, zidentity_base_url: str, client_id: str, client_secret: str, govcloud: bool = False):
        self.zidentity_base_url = zidentity_base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.govcloud = govcloud

    @property
    def vanity_domain(self) -> str:
        """Extract subdomain for SDK vanityDomain config (e.g. 'acme' from 'https://acme.zslogin.net')."""
        return urlparse(self.zidentity_base_url).hostname.split('.')[0]

    def get_token(self) -> str:
        """Return a valid OAuth2 access token, using a short-lived cache to avoid
        a fresh network round-trip on every API call."""
        cache_key = (self.client_id, self.zidentity_base_url)
        now = time.monotonic()

        with _token_lock:
            entry = _token_cache.get(cache_key)
            if entry:
                token, expires_at = entry
                if now < expires_at - 30:  # 30-second safety buffer
                    return token

        resp = requests.post(
            f"{self.zidentity_base_url}/oauth2/v1/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": "https://api.zscaler.com",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))

        with _token_lock:
            _token_cache[cache_key] = (token, now + expires_in)

        return token
