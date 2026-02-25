#!/bin/bash
# ZPA Certificate Deploy Hook for acme.sh
#
# Place this file at a stable path (e.g. /root/scripts/zpa/deploy.sh)
# and register it with acme.sh:
#   acme.sh --deploy -d "*.example.com" --deploy-hook /root/scripts/zpa/deploy.sh
#
# acme.sh sets the following variables before calling this script:
#   DOMAIN              — the domain being renewed
#   CERT_FULLCHAIN_PATH — path to the full certificate chain PEM
#   CERT_KEY_PATH       — path to the private key PEM
#
# Credentials are loaded from the config file. Set DEPLOY_CONF to override
# the default path, or set the env vars directly if preferred.

set -euo pipefail

DEPLOY_CONF="${DEPLOY_CONF:-/etc/zscaler-oneapi.conf}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/cert-upload.py"

# Load credentials if config file exists
if [[ -f "$DEPLOY_CONF" ]]; then
    # shellcheck source=/dev/null
    source "$DEPLOY_CONF"
fi

echo "==================================="
echo "ZPA Certificate Deploy"
echo "Domain : $DOMAIN"
echo "Cert   : $CERT_FULLCHAIN_PATH"
echo "Key    : $CERT_KEY_PATH"
echo "==================================="

python3 "$PYTHON_SCRIPT" \
    "$CERT_FULLCHAIN_PATH" \
    "$CERT_KEY_PATH" \
    "$DOMAIN"

exit_code=$?

if [[ $exit_code -eq 0 ]]; then
    echo "✓ ZPA deployment successful for $DOMAIN"
else
    echo "✗ ZPA deployment failed for $DOMAIN (exit code: $exit_code)"
fi

exit $exit_code
