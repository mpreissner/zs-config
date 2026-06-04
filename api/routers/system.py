"""System info and admin settings router."""

import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cli.banner import VERSION
from db.database import get_setting, set_setting
from api.dependencies import require_admin, AuthUser

router = APIRouter()


# ── System info ───────────────────────────────────────────────────────────────

@router.get("/api/v1/system/info", tags=["System"])
def system_info():
    try:
        idle_minutes = int(get_setting("idle_timeout_minutes") or "15")
    except Exception:
        idle_minutes = 15
    return {
        "version": VERSION,
        "container_mode": os.environ.get("ZS_CONTAINER_MODE", "0") == "1",
        "db_path": os.environ.get("ZSCALER_DB_PATH", "~/.local/share/zs-config/zscaler.db"),
        "plugin_dir": os.environ.get("ZS_PLUGIN_DIR", None),
        "idle_timeout_minutes": idle_minutes,
        "govcloud_enabled": os.environ.get("ZS_ENABLE_GOVCLOUD", "0") == "1",
    }


# ── Settings ──────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "access_token_ttl":           "300",
    "refresh_token_ttl":          "3600",
    "idle_timeout_minutes":       "15",
    "max_login_attempts":         "0",
    "audit_log_retention_days":   "90",
    "idp_enabled":                "false",
    "idp_provider":               "",
    "idp_issuer_url":             "",
    "idp_client_id":              "",
    "ssl_mode":                   "none",
    "ssl_domain":                 "",
    "encryption_algorithm":       "fernet",
    "fips_mode":                  "false",
    "key_rotation_interval_days": "0",
    "key_last_rotated_at":        "",
    # Update notifications
    "update_notify_enabled":      "false",
    "update_notify_email":        "",
    "smtp_host":                  "",
    "smtp_port":                  "587",
    "smtp_username":              "",
    "smtp_password":              "",
    "smtp_from_address":          "",
    "smtp_tls":                   "true",
}

_KEYS = set(_DEFAULTS.keys())


def _coerce(raw: dict) -> dict:
    try:
        smtp_port = int(raw["smtp_port"])
    except (ValueError, KeyError):
        smtp_port = 587
    return {
        "access_token_ttl":           int(raw["access_token_ttl"]),
        "refresh_token_ttl":          int(raw["refresh_token_ttl"]),
        "idle_timeout_minutes":       int(raw["idle_timeout_minutes"]),
        "max_login_attempts":         int(raw["max_login_attempts"]),
        "audit_log_retention_days":   int(raw["audit_log_retention_days"]),
        "idp_enabled":                raw["idp_enabled"] == "true",
        "idp_provider":               raw["idp_provider"],
        "idp_issuer_url":             raw["idp_issuer_url"],
        "idp_client_id":              raw["idp_client_id"],
        "ssl_mode":                   raw["ssl_mode"],
        "ssl_domain":                 raw["ssl_domain"],
        "encryption_algorithm":       raw["encryption_algorithm"],
        "fips_mode":                  raw["fips_mode"] == "true",
        "key_rotation_interval_days": int(raw["key_rotation_interval_days"]),
        "key_last_rotated_at":        raw["key_last_rotated_at"] or None,
        "update_notify_enabled":      raw.get("update_notify_enabled", "false") == "true",
        "update_notify_email":        raw.get("update_notify_email", ""),
        "smtp_host":                  raw.get("smtp_host", ""),
        "smtp_port":                  smtp_port,
        "smtp_username":              raw.get("smtp_username", ""),
        "smtp_password":              raw.get("smtp_password", ""),
        "smtp_from_address":          raw.get("smtp_from_address", ""),
        "smtp_tls":                   raw.get("smtp_tls", "true") == "true",
    }


def _load() -> dict:
    return {k: (get_setting(k) or v) for k, v in _DEFAULTS.items()}


class SettingsPatch(BaseModel):
    access_token_ttl:           Optional[int] = None
    refresh_token_ttl:          Optional[int] = None
    idle_timeout_minutes:       Optional[int] = None
    max_login_attempts:         Optional[int] = None
    audit_log_retention_days:   Optional[int] = None
    idp_enabled:                Optional[bool] = None
    idp_provider:               Optional[str] = None
    idp_issuer_url:             Optional[str] = None
    idp_client_id:              Optional[str] = None
    ssl_mode:                   Optional[str] = None
    ssl_domain:                 Optional[str] = None
    encryption_algorithm:       Optional[str] = None
    fips_mode:                  Optional[bool] = None
    key_rotation_interval_days: Optional[int] = None
    update_notify_enabled:      Optional[bool] = None
    update_notify_email:        Optional[str] = None
    smtp_host:                  Optional[str] = None
    smtp_port:                  Optional[int] = None
    smtp_username:              Optional[str] = None
    smtp_password:              Optional[str] = None
    smtp_from_address:          Optional[str] = None
    smtp_tls:                   Optional[bool] = None


@router.get("/api/v1/system/settings", tags=["System"])
def get_settings(_: AuthUser = Depends(require_admin)):
    return _coerce(_load())


@router.patch("/api/v1/system/settings", tags=["System"])
def patch_settings(body: SettingsPatch, _: AuthUser = Depends(require_admin)):
    for k, v in body.model_dump(exclude_none=True).items():
        if k in _KEYS:
            set_setting(k, str(v).lower() if isinstance(v, bool) else str(v))
    return _coerce(_load())


@router.post("/api/v1/system/update-notify/test", tags=["System"])
def test_update_notify(_: AuthUser = Depends(require_admin)):
    from services.update_notify_service import send_test_email
    from fastapi import HTTPException

    raw = _load()
    to_addr = raw.get("update_notify_email", "")
    host = raw.get("smtp_host", "")
    if not to_addr or not host:
        raise HTTPException(status_code=400, detail="update_notify_email and smtp_host must be configured first.")
    try:
        port = int(raw.get("smtp_port", "587"))
    except ValueError:
        port = 587
    try:
        send_test_email(
            host=host,
            port=port,
            username=raw.get("smtp_username", ""),
            password=raw.get("smtp_password", ""),
            from_addr=raw.get("smtp_from_address", ""),
            to_addr=to_addr,
            use_tls=raw.get("smtp_tls", "true") == "true",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"sent": True}
