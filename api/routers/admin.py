from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.dependencies import require_admin, AuthUser
from api.auth_utils import hash_password
from db.database import get_session
from db.models import User, UserTenantEntitlement, TenantConfig

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    force_password_change: bool
    created_at: str
    last_login_at: Optional[str]

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "user"
    force_password_change: bool = True


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    force_password_change: Optional[bool] = None
    password: Optional[str] = None


class EntitlementOut(BaseModel):
    id: int
    user_id: int
    username: str
    tenant_id: int
    tenant_name: str
    granted_at: str


class EntitlementCreate(BaseModel):
    user_id: int
    tenant_id: int


# ── Users ─────────────────────────────────────────────────────────────────────

def _user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "force_password_change": u.force_password_change,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
def list_users(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        users = session.query(User).order_by(User.username).all()
        return [_user_out(u) for u in users]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: AuthUser = Depends(require_admin)):
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=422, detail="role must be 'admin' or 'user'")
    with get_session() as session:
        if session.query(User).filter_by(username=body.username).first():
            raise HTTPException(status_code=409, detail="Username already exists")
        user = User(
            username=body.username,
            email=body.email,
            role=body.role,
            password_hash=hash_password(body.password),
            force_password_change=body.force_password_change,
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.refresh(user)
        return _user_out(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, current: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.id == current.user_id and body.role is not None and body.role != "admin":
            raise HTTPException(status_code=400, detail="Cannot remove admin role from yourself")
        if user.id == current.user_id and body.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        if body.role is not None:
            if body.role not in ("admin", "user"):
                raise HTTPException(status_code=422, detail="role must be 'admin' or 'user'")
            user.role = body.role
        if body.email is not None:
            user.email = body.email
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.force_password_change is not None:
            user.force_password_change = body.force_password_change
        if body.password:
            user.password_hash = hash_password(body.password)
        user.updated_at = datetime.utcnow()
        session.flush()
        session.refresh(user)
        return _user_out(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, current: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.id == current.user_id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        session.delete(user)


# ── Entitlements ──────────────────────────────────────────────────────────────

def _ent_out(e: UserTenantEntitlement) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "username": e.user.username,
        "tenant_id": e.tenant_id,
        "tenant_name": e.tenant.name,
        "granted_at": e.granted_at.isoformat() if e.granted_at else None,
    }


@router.get("/entitlements")
def list_entitlements(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        ents = (
            session.query(UserTenantEntitlement)
            .join(UserTenantEntitlement.user)
            .join(UserTenantEntitlement.tenant)
            .order_by(User.username, TenantConfig.name)
            .all()
        )
        return [_ent_out(e) for e in ents]


@router.post("/entitlements", status_code=201)
def create_entitlement(body: EntitlementCreate, _: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=body.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        tenant = session.query(TenantConfig).filter_by(id=body.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        existing = session.query(UserTenantEntitlement).filter_by(
            user_id=body.user_id, tenant_id=body.tenant_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Entitlement already exists")
        ent = UserTenantEntitlement(user_id=body.user_id, tenant_id=body.tenant_id)
        session.add(ent)
        session.flush()
        session.refresh(ent)
        return _ent_out(ent)


@router.delete("/entitlements/{entitlement_id}", status_code=204)
def delete_entitlement(entitlement_id: int, _: AuthUser = Depends(require_admin)):
    with get_session() as session:
        ent = session.query(UserTenantEntitlement).filter_by(id=entitlement_id).first()
        if not ent:
            raise HTTPException(status_code=404, detail="Entitlement not found")
        session.delete(ent)
