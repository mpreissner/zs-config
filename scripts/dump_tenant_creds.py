#!/usr/bin/env python3
"""Print decrypted tenant credentials for migration to a new install."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.config_service import list_tenants, decrypt_secret

tenants = list_tenants()
if not tenants:
    print("No tenants found.")
    sys.exit(0)

for t in tenants:
    print(f"\n--- {t.name} ---")
    print(f"  zidentity_base_url : {t.zidentity_base_url}")
    print(f"  oneapi_base_url    : {t.oneapi_base_url}")
    print(f"  client_id          : {t.client_id}")
    print(f"  client_secret      : {decrypt_secret(t.client_secret_enc)}")
    print(f"  govcloud           : {t.govcloud}")
    if t.zpa_customer_id:
        print(f"  zpa_customer_id    : {t.zpa_customer_id}")
    if t.notes:
        print(f"  notes              : {t.notes}")
