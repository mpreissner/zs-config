#!/bin/sh
set -e
if [ "${ZS_TUI_ONLY}" = "1" ]; then
    exec python -m cli.z_config
else
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000
fi
