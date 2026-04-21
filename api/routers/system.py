"""System info router — exposes version and runtime environment metadata."""

import os

from fastapi import APIRouter

from cli.banner import VERSION

router = APIRouter()


@router.get("/api/v1/system/info", tags=["System"])
def system_info():
    return {
        "version": VERSION,
        "container_mode": os.environ.get("ZS_CONTAINER_MODE", "0") == "1",
        "db_path": os.environ.get("ZSCALER_DB_PATH", "~/.local/share/zs-config/zscaler.db"),
        "plugin_dir": os.environ.get("ZS_PLUGIN_DIR", None),
    }
