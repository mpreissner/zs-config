#!/usr/bin/env python3
"""ZPA Certificate Upload / Rotation Script

Designed to be called by acme.sh as a --deploy-hook, but also supports
loading tenant config from the local database via --tenant.

Usage (acme.sh hook — env vars set by acme.sh):
    acme.sh --deploy --deploy-hook /path/to/scripts/zpa/deploy.sh

Usage (manual / database config):
    python cert-upload.py <cert_path> <key_path> <domain> --tenant <name>

Environment variables (acme.sh / server mode):
    ZIDENTITY_BASE_URL   — required
    ZSCALER_CLIENT_ID    — required
    ZSCALER_CLIENT_SECRET — required
    ZPA_CUSTOMER_ID      — required
    ONEAPI_BASE_URL      — optional, defaults to https://api.zsapi.net
    CERT_FULLCHAIN_PATH — set by acme.sh (overrides positional arg 1)
    CERT_KEY_PATH       — set by acme.sh (overrides positional arg 2)
    DOMAIN              — set by acme.sh (overrides positional arg 3)
"""

import argparse
import os
import sys

# Ensure repo root is importable regardless of working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from lib.auth import ZscalerAuth
from lib.zpa_client import ZPAClient
from services.zpa_service import ZPAService


def _load_from_env():
    """Return (auth, customer_id, oneapi_url) from environment variables."""
    missing = [v for v in ("ZIDENTITY_BASE_URL", "ZSCALER_CLIENT_ID", "ZSCALER_CLIENT_SECRET", "ZPA_CUSTOMER_ID")
               if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    auth = ZscalerAuth(
        os.environ["ZIDENTITY_BASE_URL"],
        os.environ["ZSCALER_CLIENT_ID"],
        os.environ["ZSCALER_CLIENT_SECRET"],
    )
    return auth, os.environ["ZPA_CUSTOMER_ID"], os.environ.get("ONEAPI_BASE_URL", "https://api.zsapi.net"), None


def _load_from_db(tenant_name: str):
    """Return (auth, customer_id, oneapi_url, tenant_id) from the database."""
    from db.database import init_db
    from services.config_service import decrypt_secret, get_tenant

    init_db()
    tenant = get_tenant(tenant_name)
    if not tenant:
        print(f"ERROR: Tenant '{tenant_name}' not found in database.")
        sys.exit(1)
    if not tenant.zpa_customer_id:
        print(f"ERROR: Tenant '{tenant_name}' has no ZPA Customer ID configured.")
        sys.exit(1)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    return auth, tenant.zpa_customer_id, tenant.oneapi_base_url, tenant.id


def main():
    parser = argparse.ArgumentParser(description="ZPA Certificate Rotation")
    parser.add_argument("cert_path", nargs="?", help="Path to certificate PEM file")
    parser.add_argument("key_path", nargs="?", help="Path to private key PEM file")
    parser.add_argument("domain", nargs="?", help="Domain name (e.g. *.example.com)")
    parser.add_argument("--tenant", help="Tenant name from database (alternative to env vars)")
    args = parser.parse_args()

    # Resolve paths — CLI args take priority, fall back to acme.sh env vars
    cert_path = args.cert_path or os.environ.get("CERT_FULLCHAIN_PATH")
    key_path = args.key_path or os.environ.get("CERT_KEY_PATH")
    domain = args.domain or os.environ.get("DOMAIN")

    if not all([cert_path, key_path, domain]):
        parser.print_help()
        sys.exit(1)

    # Resolve credentials
    if args.tenant:
        auth, customer_id, oneapi_url, tenant_id = _load_from_db(args.tenant)
    else:
        auth, customer_id, oneapi_url, tenant_id = _load_from_env()

    client = ZPAClient(auth, customer_id, oneapi_url)
    service = ZPAService(client, tenant_id=tenant_id)

    print(f"=== ZPA Certificate Rotation: {domain} ===")

    try:
        result = service.rotate_certificate(cert_path, key_path, domain)
        print(f"✓ New certificate uploaded: {result['cert_name']} (ID: {result['new_cert_id']})")
        print(f"✓ Browser Access apps updated: {result['apps_updated']}")
        print(f"✓ PRA Portals updated:         {result['portals_updated']}")
        if result["certs_deleted"]:
            print(f"✓ Old certificates deleted:    {result['certs_deleted']}")
        if result["certs_skipped"]:
            print(f"  Certificates still in use (skipped): {result['certs_skipped']}")

        if result["apps_updated"] + result["portals_updated"] == 0:
            print(f"\nWARNING: No matching resources found for domain '{domain}'.")
            print("  Certificate was uploaded but not assigned to anything.")

        print("=== Complete ===")
        sys.exit(0)

    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
