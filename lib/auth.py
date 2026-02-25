from urllib.parse import urlparse


class ZscalerAuth:
    """Credentials holder for Zscaler OneAPI.

    Provides client_id, client_secret, and vanity_domain to the SDK.
    Token acquisition and refresh are handled internally by zscaler-sdk-python.
    """

    def __init__(self, zidentity_base_url: str, client_id: str, client_secret: str):
        self.zidentity_base_url = zidentity_base_url
        self.client_id = client_id
        self.client_secret = client_secret

    @property
    def vanity_domain(self) -> str:
        """Extract subdomain for SDK vanityDomain config (e.g. 'acme' from 'https://acme.zslogin.net')."""
        return urlparse(self.zidentity_base_url).hostname.split('.')[0]
