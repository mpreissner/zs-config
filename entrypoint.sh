#!/bin/sh
set -e

if [ "${ZS_TUI_ONLY}" = "1" ]; then
    exec python -m cli.z_config
fi

# Determine SSL mode from DB at startup
SSL_CMD=$(python -c "
import os, sys
sys.path.insert(0, '.')
from db.database import get_setting
mode = get_setting('ssl_mode') or 'none'
if mode == 'upload':
    cert = '/data/db/ssl/cert.pem'
    key  = '/data/db/ssl/key.pem'
    import pathlib
    if pathlib.Path(cert).exists() and pathlib.Path(key).exists():
        domain = get_setting('ssl_domain') or 'localhost'
        print(f'ssl_mode=upload cert={cert} key={key} domain={domain}')
        sys.exit(0)
print('ssl_mode=none')
" 2>/dev/null || echo "ssl_mode=none")

case "$SSL_CMD" in
  ssl_mode=upload*)
    CERT=$(echo "$SSL_CMD"   | grep -o 'cert=[^ ]*'   | cut -d= -f2)
    KEY=$(echo "$SSL_CMD"    | grep -o 'key=[^ ]*'    | cut -d= -f2)
    DOMAIN=$(echo "$SSL_CMD" | grep -o 'domain=[^ ]*' | cut -d= -f2)
    ZS_SSL_DOMAIN="${DOMAIN:-localhost}" uvicorn api.redirect_app:redirect_app --host 0.0.0.0 --port 8000 &
    exec python api/run_ssl.py "$CERT" "$KEY"
    ;;
  *)
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000
    ;;
esac
