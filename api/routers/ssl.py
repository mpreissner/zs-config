import asyncio
import os
import signal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from api.dependencies import require_admin, AuthUser
from services import ssl_service
from services.ssl_service import SSLValidationError

router = APIRouter()


def _require_container_mode() -> None:
    if os.environ.get("ZS_CONTAINER_MODE") != "1":
        raise HTTPException(status_code=503, detail="ssl_container_only")


async def _delayed_restart() -> None:
    await asyncio.sleep(2)
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/api/v1/system/ssl/upload", tags=["System"])
async def upload_ssl(
    method: str = Form(...),
    domain: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
    pfx_password: str = Form(default=""),
    pem_text: str = Form(default=""),
    _: AuthUser = Depends(require_admin),
) -> dict:
    _require_container_mode()

    if method not in ("pfx", "pem_file", "pem_paste"):
        raise HTTPException(status_code=422, detail="method must be pfx, pem_file, or pem_paste")
    if method in ("pfx", "pem_file") and file is None:
        raise HTTPException(status_code=422, detail="file is required for pfx and pem_file methods")
    if method == "pem_paste" and not pem_text.strip():
        raise HTTPException(status_code=422, detail="pem_text is required for pem_paste method")

    try:
        if method == "pfx":
            bundle = ssl_service.process_pfx(await file.read(), pfx_password, domain)
        elif method == "pem_file":
            bundle = ssl_service.process_pem_bytes(await file.read(), domain)
        else:
            bundle = ssl_service.process_pem_text(pem_text, domain)
        ssl_service.save_bundle(bundle, domain)
    except SSLValidationError as e:
        return JSONResponse(status_code=400, content={"detail": e.code, "message": str(e)})

    asyncio.create_task(_delayed_restart())
    return {"status": "restarting", "domain": domain}


@router.get("/api/v1/system/ssl/status", tags=["System"])
def ssl_status(_: AuthUser = Depends(require_admin)) -> dict:
    s = ssl_service.get_status()
    return {
        "active": s.active,
        "mode": s.mode,
        "domain": s.domain,
        "subject": s.subject,
        "sans": s.sans,
        "not_before": s.not_before,
        "not_after": s.not_after,
        "days_until_expiry": s.days_until_expiry,
    }


@router.delete("/api/v1/system/ssl", tags=["System"])
async def remove_ssl(_: AuthUser = Depends(require_admin)) -> dict:
    _require_container_mode()
    ssl_service.remove_ssl()
    asyncio.create_task(_delayed_restart())
    return {"status": "restarting"}
