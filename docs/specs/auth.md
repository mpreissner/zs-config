# Spec: Multi-User Authentication and Authorization

**Feature branch**: `feature/auth` (from `dev`)
**Status**: Draft — awaiting implementation sign-off
**Scope**: JWT-based auth, local admin account, OIDC and SAML 2.0 SSO, admin web UI, tenant entitlements

---

## 1. Overview

The API is currently unauthenticated. This spec adds multi-user authentication with:

- A built-in local `admin` account (bcrypt password, force-change on first login)
- OIDC and SAML 2.0 SSO for enterprise IdP integration
- Per-user tenant entitlements — users access only the tenants they are entitled to
- A React admin UI for managing users, tenants, entitlements, and SSO provider config
- JWT access tokens (15 min) + refresh tokens in httponly cookies (7 days)

The existing CLI and `scripts/` flows bypass the API layer entirely. They authenticate directly to Zscaler using credentials from the DB. They are not affected by this feature.

---

## 2. Data Model

Four new tables. All use the existing `get_session()` pattern from `db/database.py`. The SQLite non-negotiable applies: never open a `get_session()` block inside an existing one — collect any audit events in a list and write them after the outer session closes.

### 2.1 SQLAlchemy model sketches

Add to `db/models.py`:

```python
import secrets
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship


class User(Base):
    """Local and SSO-provisioned users.

    SSO users are identified by (sso_provider, sso_subject). Local users
    have sso_provider=None and authenticate via bcrypt password.
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("sso_provider", "sso_subject", name="uq_user_sso"),
    )

    id                    = Column(Integer, primary_key=True)
    username              = Column(String(255), unique=True, nullable=False)
    email                 = Column(String(512), nullable=True)
    role                  = Column(String(32), nullable=False, default="user")
    # role values: "admin" | "user"

    # Local auth
    password_hash         = Column(Text, nullable=True)    # bcrypt; NULL for pure-SSO users
    force_password_change = Column(Boolean, nullable=False, default=False)

    # SSO linkage
    sso_provider          = Column(String(64), nullable=True)   # "oidc" | "saml" | NULL
    sso_subject           = Column(String(512), nullable=True)  # sub claim or SAML NameID

    is_active             = Column(Boolean, nullable=False, default=True)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at         = Column(DateTime, nullable=True)

    entitlements = relationship("UserTenantEntitlement", back_populates="user",
                                cascade="all, delete-orphan", lazy="select")

    def __repr__(self) -> str:
        return f"<User username={self.username!r} role={self.role!r}>"


class UserTenantEntitlement(Base):
    """Maps a user to a tenant they are permitted to access."""
    __tablename__ = "user_tenant_entitlements"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id", ondelete="CASCADE"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # admin user ID

    user   = relationship("User", back_populates="entitlements", foreign_keys=[user_id])
    tenant = relationship("TenantConfig", lazy="select")

    def __repr__(self) -> str:
        return f"<UserTenantEntitlement user_id={self.user_id} tenant_id={self.tenant_id}>"


class SsoConfig(Base):
    """OIDC and SAML provider configuration, stored in DB so it can be
    changed via the admin UI without a container restart.

    Only one row per provider type is expected for the MVP. The cache-bust
    endpoint reloads this table into memory without a restart.

    Sensitive fields (oidc_client_secret, saml_private_key) must never
    appear in API responses or logs — same rule as client_secret on tenants.
    """
    __tablename__ = "sso_config"

    id       = Column(Integer, primary_key=True)
    provider = Column(String(32), unique=True, nullable=False)  # "oidc" | "saml"
    enabled  = Column(Boolean, nullable=False, default=False)

    # OIDC fields
    oidc_client_id      = Column(String(512), nullable=True)
    oidc_client_secret_enc = Column(Text, nullable=True)       # Fernet-encrypted; never in responses
    oidc_metadata_url   = Column(String(1024), nullable=True)  # discovery URL
    oidc_scopes         = Column(String(512), nullable=True, default="openid email profile")

    # SAML fields
    saml_entity_id      = Column(String(1024), nullable=True)
    saml_metadata_url   = Column(String(1024), nullable=True)  # IdP metadata URL
    saml_sp_cert        = Column(Text, nullable=True)          # SP signing cert (public)
    saml_private_key_enc = Column(Text, nullable=True)         # Fernet-encrypted; never in responses
    saml_name_id_format = Column(String(255), nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SsoConfig provider={self.provider!r} enabled={self.enabled}>"
```

No session table. JWTs are stateless. Refresh token revocation is out of scope for MVP — document as follow-on.

### 2.2 Migration

Add to the `_migrate()` function in `db/database.py` after the existing migration statements:

```python
# auth tables — created by Base.metadata.create_all if new install;
# these ALTER TABLE stmts are no-ops on new installs and safe on existing ones
"ALTER TABLE users ADD COLUMN last_login_at DATETIME",
```

`Base.metadata.create_all` handles new installs. `_migrate()` handles the additive ALTER TABLE pattern already established in the codebase.

---

## 3. Admin Bootstrap Flow

The bootstrap runs inside the `lifespan` function in `api/main.py`, after `init_db()`. It must not open a session inside another session block.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    import os, sys, secrets, logging
    from db.database import init_db, get_session
    from db.models import User

    # Refuse to start if JWT_SECRET is not set
    if not os.environ.get("JWT_SECRET"):
        sys.exit("FATAL: JWT_SECRET environment variable is required but not set.")

    init_db()

    # Warn if CORS wildcard + credentials + SSO are all active together
    _maybe_warn_cors_wildcard()

    # Bootstrap admin user if no admin exists yet
    with get_session() as session:
        admin_exists = session.query(User).filter_by(role="admin", is_active=True).first()

    if not admin_exists:
        import bcrypt
        initial_password = os.environ.get("ADMIN_INITIAL_PASSWORD")
        if initial_password:
            plaintext = initial_password
        else:
            plaintext = secrets.token_urlsafe(15)  # ~20 printable chars
            print(f"[zs-config] Admin account created. Initial password: {plaintext}", flush=True)
            # Never write plaintext to log, audit, or DB

        password_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()

        with get_session() as session:
            admin = User(
                username="admin",
                role="admin",
                password_hash=password_hash,
                force_password_change=True,
                is_active=True,
            )
            session.add(admin)

    yield
```

Key constraints:
- The two `with get_session()` blocks are sequential, never nested. The check and the write are separate sessions to satisfy the SQLite non-negotiable.
- `plaintext` is never assigned to any DB field, log call, or audit entry.
- `print(..., flush=True)` goes to stdout only. Operators running `docker logs` see it once, then it never appears again.
- `ADMIN_INITIAL_PASSWORD` env var is consumed at first boot only. On subsequent starts the admin already exists and the block is skipped entirely.
- `bcrypt.gensalt()` defaults to cost factor 12, which is acceptable for MVP.

### 3.1 CORS wildcard warning

```python
def _maybe_warn_cors_wildcard():
    import logging, os
    from db.database import get_session
    from db.models import SsoConfig

    if os.environ.get("ZS_CONTAINER_MODE") != "1":
        return
    if os.environ.get("ALLOWED_ORIGINS", "*") != "*":
        return

    with get_session() as session:
        sso_enabled = session.query(SsoConfig).filter_by(enabled=True).first()

    if sso_enabled:
        logging.warning(
            "zs-config: ALLOWED_ORIGINS=* with SSO enabled in container mode. "
            "Credentialed requests will fail in browsers. Set ALLOWED_ORIGINS to your "
            "actual origin (e.g. https://your-host.example.com) before enabling SSO."
        )
```

---

## 4. Authentication Flows

### 4.1 Local (admin) login

**Endpoint**: `POST /api/v1/auth/login`

Request body:
```json
{ "username": "admin", "password": "..." }
```

Flow:
1. Look up `User` by `username`, check `is_active`.
2. `bcrypt.checkpw(password.encode(), user.password_hash.encode())`.
3. On success, issue access token + refresh token (see section 7).
4. If `force_password_change=True`, still issue tokens but set `force_password_change: true` in the access token payload. The middleware enforces a redirect to `/change-password` — any request other than `POST /api/v1/auth/change-password` returns `HTTP 403` with `{"detail": "password_change_required"}`.
5. Return access token in JSON body; set refresh token in `Set-Cookie: refresh_token=...; HttpOnly; SameSite=Strict; Path=/api/v1/auth/refresh`.

**Endpoint**: `POST /api/v1/auth/change-password`

Request body: `{ "current_password": "...", "new_password": "..." }`

Flow:
1. Require valid access token (any authenticated user).
2. Re-verify `current_password` with bcrypt.
3. Hash `new_password`, update `password_hash`, set `force_password_change=False`.
4. Issue a new token pair (clears the force-change flag from the JWT payload).

**Endpoint**: `POST /api/v1/auth/refresh`

Flow:
1. Read `refresh_token` from cookie.
2. Verify JWT signature and expiry.
3. Issue new access token. Optionally rotate refresh token (MVP: no rotation).

**Endpoint**: `POST /api/v1/auth/logout`

Flow: clear the `refresh_token` cookie by setting `Max-Age=0`.

### 4.2 OIDC authorization code flow

**Endpoints**:
- `GET /api/v1/auth/oidc/login` — redirect to IdP authorization URL (built by `authlib`)
- `GET /api/v1/auth/oidc/callback` — receive `code`, exchange for tokens, upsert user, issue JWT pair

Flow:
1. On `/login`, read `SsoConfig` where `provider="oidc"` and `enabled=True`. If not found, return 404.
2. Build authorization URL via `authlib.integrations.starlette_client`. Redirect.
3. On `/callback`, exchange `code` for tokens. Extract `sub` (or `email` if `sub` unstable) from ID token claims.
4. Upsert `User`: look up by `(sso_provider="oidc", sso_subject=sub)`. If not found, create with `role="user"`, `force_password_change=False`. Update `email` and `last_login_at`.
5. Issue same JWT pair as local auth. New SSO users default to no entitlements.

### 4.3 SAML 2.0 SP-initiated flow

**Endpoints**:
- `GET /api/v1/auth/saml/login` — redirect to IdP SSO URL
- `POST /api/v1/auth/saml/acs` — assertion consumer service; process `SAMLResponse`

Flow:
1. On `/login`, read `SsoConfig` where `provider="saml"` and `enabled=True`. If not found, return 404.
2. Build authn request via `python3-saml` (`OneLogin_Saml2_Auth`). Redirect to IdP.
3. On `/acs`, parse and validate `SAMLResponse`. Extract `NameID`.
4. Upsert `User`: look up by `(sso_provider="saml", sso_subject=NameID)`. If not found, create with `role="user"`. Update `email` (from attributes if present) and `last_login_at`.
5. Issue same JWT pair. New SSO users default to no entitlements.

---

## 5. Authorization Model

### 5.1 Roles

| Role | Capabilities |
|------|-------------|
| `admin` | All tenant access; manage tenants, users, entitlements; access admin UI; CRUD on SSO config |
| `user` | Access only entitled tenants; read-only on tenant list (no credential fields); no admin UI |

### 5.2 FastAPI dependencies

Location: `api/dependencies.py`

```python
from fastapi import Depends, HTTPException, Cookie, Header
from typing import Optional
from dataclasses import dataclass


@dataclass
class AuthUser:
    user_id: int
    username: str
    role: str
    force_password_change: bool


def require_auth(
    authorization: Optional[str] = Header(default=None),
) -> AuthUser:
    """Validate Bearer access token. Returns decoded user context.

    Raises HTTP 401 if token is missing or invalid.
    Raises HTTP 403 if force_password_change=True and the endpoint is not
    POST /api/v1/auth/change-password (enforced in middleware, not here).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    payload = _decode_access_token(token)  # raises 401 on invalid/expired
    return AuthUser(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
        force_password_change=payload.get("fpc", False),
    )


def require_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    """Require admin role. Raises HTTP 403 otherwise."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
```

`_decode_access_token` is a private helper in `api/dependencies.py` that calls `jose.jwt.decode` with `JWT_SECRET` and algorithm `HS256`.

### 5.3 Tenant-scoped authorization

Existing ZIA and ZPA routers accept a `tenant` name path parameter. Add an entitlement check dependency:

```python
def require_tenant_access(
    tenant: str,               # path parameter, already present in all ZIA/ZPA routes
    user: AuthUser = Depends(require_auth),
) -> int:
    """Return tenant DB id if user is entitled. Raises 403 otherwise.

    Admins bypass the entitlement check and always have access.
    """
    from services.config_service import get_tenant
    from db.database import get_session
    from db.models import UserTenantEntitlement

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if user.role == "admin":
        return t.id

    with get_session() as session:
        ent = session.query(UserTenantEntitlement).filter_by(
            user_id=user.user_id, tenant_id=t.id
        ).first()
    if not ent:
        raise HTTPException(status_code=403, detail="Not entitled to this tenant")
    return t.id
```

Usage in an existing router, e.g. `api/routers/zia.py`:

```python
@router.get("/{tenant}/activation/status")
def get_activation_status(
    tenant: str,
    tenant_id: int = Depends(require_tenant_access),
    user: AuthUser = Depends(require_auth),
):
    ...
```

`require_tenant_access` already calls `require_auth` transitively (via `Depends`), so no double-auth.

### 5.4 force_password_change middleware

Add a middleware in `api/main.py` that intercepts all requests before they reach a router:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class ForcePasswordChangeMiddleware(BaseHTTPMiddleware):
    _EXEMPT = {"/api/v1/auth/change-password", "/api/v1/auth/login",
               "/api/v1/auth/logout", "/api/v1/auth/refresh",
               "/api/v1/auth/oidc/login", "/api/v1/auth/oidc/callback",
               "/api/v1/auth/saml/login", "/api/v1/auth/saml/acs",
               "/health", "/docs", "/openapi.json"}

    async def dispatch(self, request, call_next):
        if request.url.path in self._EXEMPT:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = _decode_access_token(auth.removeprefix("Bearer "))
                if payload.get("fpc"):
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        {"detail": "password_change_required"}, status_code=403
                    )
            except Exception:
                pass  # let the router's require_auth handle invalid tokens
        return await call_next(request)
```

Register before the CORS middleware so the CORS headers are still added on 403 responses.

---

## 6. Endpoint Table

### Auth endpoints

| Method | Path | Auth required | Notes |
|--------|------|---------------|-------|
| `POST` | `/api/v1/auth/login` | None | Local login; returns access token + sets refresh cookie |
| `POST` | `/api/v1/auth/refresh` | Refresh cookie | Returns new access token |
| `POST` | `/api/v1/auth/logout` | None | Clears refresh cookie |
| `POST` | `/api/v1/auth/change-password` | Bearer | Changes password; clears `force_password_change` |
| `GET` | `/api/v1/auth/oidc/login` | None | Redirects to OIDC IdP |
| `GET` | `/api/v1/auth/oidc/callback` | None | OIDC callback; upserts user; issues tokens |
| `GET` | `/api/v1/auth/saml/login` | None | Redirects to SAML IdP |
| `POST` | `/api/v1/auth/saml/acs` | None | SAML ACS; upserts user; issues tokens |

### Admin endpoints (admin role only)

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/admin/users` | List all users |
| `POST` | `/api/v1/admin/users` | Create local user |
| `PUT` | `/api/v1/admin/users/{id}` | Update user (role, active status) |
| `DELETE` | `/api/v1/admin/users/{id}` | Deactivate user (soft delete) |
| `GET` | `/api/v1/admin/entitlements` | List all user-tenant entitlements |
| `POST` | `/api/v1/admin/entitlements` | Grant entitlement |
| `DELETE` | `/api/v1/admin/entitlements/{id}` | Revoke entitlement |
| `GET` | `/api/v1/admin/sso` | List SSO configs (no sensitive fields in response) |
| `PUT` | `/api/v1/admin/sso/{provider}` | Upsert SSO config |
| `POST` | `/api/v1/admin/sso/reload` | Bust SSO config cache (reload from DB) |

### Existing endpoints updated

All existing ZIA and ZPA endpoints gain `require_tenant_access` dependency (see section 5.3).

The existing tenant CRUD endpoints from `web-frontend.md` section 5.3 (`POST /api/v1/tenants`, `PUT /api/v1/tenants/{id}`, `DELETE /api/v1/tenants/{id}`, `GET /api/v1/tenants/{id}`) require `require_admin`. `GET /api/v1/tenants` requires `require_auth` (all authenticated users can see the tenant list, but non-admins see only entitled tenants and no credential fields).

---

## 7. JWT Design

### 7.1 Access token payload

```json
{
  "sub": 1,
  "username": "admin",
  "role": "admin",
  "fpc": false,
  "iat": 1714000000,
  "exp": 1714000900
}
```

- `sub`: integer `User.id`
- `role`: `"admin"` or `"user"`
- `fpc`: `force_password_change` flag (boolean)
- `exp`: `iat + 900` (15 minutes)
- Algorithm: `HS256`
- Signing key: `JWT_SECRET` env var (required; startup refuses with a clear fatal message if absent — see section 3)

### 7.2 Refresh token payload

```json
{
  "sub": 1,
  "type": "refresh",
  "iat": 1714000000,
  "exp": 1714604800
}
```

- `exp`: `iat + 604800` (7 days)
- Stored in `HttpOnly; SameSite=Strict; Path=/api/v1/auth/refresh` cookie
- `SameSite=Strict` is safe for desktop/localhost deployments. Server deployments where the frontend origin differs from the API origin may need `SameSite=Lax`. This is a configuration concern — document in deployment notes. Do not make it an env var in MVP; treat as a code constant to revisit.

### 7.3 Token issuance helper

Location: `api/auth_utils.py`

```python
import os, time
from jose import jwt

_ALGORITHM = "HS256"

def _secret() -> str:
    return os.environ["JWT_SECRET"]  # never falls back to a default

def issue_access_token(user) -> str:
    now = int(time.time())
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "fpc": user.force_password_change,
        "iat": now,
        "exp": now + 900,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)

def issue_refresh_token(user) -> str:
    now = int(time.time())
    payload = {
        "sub": user.id,
        "type": "refresh",
        "iat": now,
        "exp": now + 604800,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and verify. Raises jose.JWTError on invalid/expired."""
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
```

### 7.4 Key rotation

Out of scope for MVP. Document as follow-on: introduce `JWT_SECRET_PREV` env var to allow rolling rotation (verify with either key, sign with `JWT_SECRET`).

---

## 8. SSO Provider Config Storage and Caching

`SsoConfig` rows are loaded once at startup into a module-level dict in `api/sso_cache.py`:

```python
_cache: dict[str, "SsoConfig"] = {}

def load_sso_cache():
    from db.database import get_session
    from db.models import SsoConfig
    with get_session() as session:
        rows = session.query(SsoConfig).filter_by(enabled=True).all()
        _cache.clear()
        _cache.update({r.provider: r for r in rows})

def get_sso_config(provider: str):
    return _cache.get(provider)
```

`load_sso_cache()` is called in `lifespan` after `init_db()`. The `POST /api/v1/admin/sso/reload` endpoint calls `load_sso_cache()` directly — no restart required.

Sensitive fields (`oidc_client_secret_enc`, `saml_private_key_enc`) are Fernet-encrypted in the DB using the same `encrypt_secret` / `decrypt_secret` from `services/config_service.py`. They are decrypted at runtime when building the OIDC/SAML client objects. They never appear in API responses (the `SsoConfig` response schema omits both fields and replaces them with a `has_secret: bool` and `has_private_key: bool` indicator, mirroring the `has_credentials` pattern from `web-frontend.md` section 5.3).

---

## 9. Python Libraries

Add to the `[api]` optional dependency group in `pyproject.toml`:

```toml
[project.optional-dependencies]
api = [
    # ... existing api deps ...
    "passlib[bcrypt]",
    "python-jose[cryptography]",
    "authlib",
    "python3-saml",
]
```

SAML requires `xmlsec` at the system level. Add to the Dockerfile runtime stage:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    xmlsec1 \
    libxml2-dev \
    libxmlsec1-dev \
    libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*
```

Note: `python3-saml` wraps the `xmlsec1` binary as well as the C library. Both `xmlsec1` (binary) and `libxmlsec1-dev` (headers for the Python binding) are needed.

---

## 10. React Admin UI Scope

### 10.1 New routes

| Route | Component | Role required |
|-------|-----------|---------------|
| `/login` | `LoginPage` | None |
| `/change-password` | `ChangePasswordPage` | Authenticated (any) |
| `/admin/users` | `AdminUsersPage` | admin |
| `/admin/tenants` | `AdminTenantsPage` | admin |
| `/admin/entitlements` | `AdminEntitlementsPage` | admin |
| `/admin/sso` | `AdminSsoPage` | admin |

### 10.2 Login page

- Local login form (username + password)
- Password field must include a show/hide toggle (eye icon) to allow the user to de-obfuscate the input and verify what they typed. Same applies to all password inputs on the change-password and create-user forms.
- SSO buttons rendered only if `GET /api/v1/admin/sso` returns enabled providers
- On submit: `POST /api/v1/auth/login` → store access token in memory (not localStorage — XSS risk); refresh token lands in httponly cookie automatically
- If `force_password_change=true` in response, redirect to `/change-password`

### 10.3 Auth state

Use a React context (`AuthContext`) that holds the decoded access token payload. On app load, attempt `POST /api/v1/auth/refresh` (using the existing cookie) to silently re-authenticate. If it fails (no valid cookie), redirect to `/login`.

Axios/fetch interceptor: on `401` response, attempt one refresh; on second `401`, clear auth state and redirect to `/login`.

### 10.4 Admin sections

**`/admin/users`**:
- Table: username, email, role, SSO provider, active, last login
- Actions: create local user (modal with username/email/initial password), set role, deactivate

**`/admin/tenants`**:
- Full CRUD for tenants including credentials — this is the web equivalent of the CLI tenant management flow
- `client_secret` field in create/edit forms: write-only input; response shows `has_credentials: true/false` only
- Calls the tenant CRUD endpoints from `web-frontend.md` section 5.3

**`/admin/entitlements`**:
- Two-column UI: select user, then select tenants to grant/revoke
- Calls `POST/DELETE /api/v1/admin/entitlements`

**`/admin/sso`**:
- OIDC section: client_id, metadata URL, scopes, client_secret (write-only input), enable/disable toggle
- SAML section: entity ID, metadata URL, SP cert (text area), private key (write-only text area), enable/disable toggle
- "Reload config" button calls `POST /api/v1/admin/sso/reload`

### 10.5 Route guards

`PrivateRoute` component wraps all authenticated routes. `AdminRoute` wraps all `/admin/*` routes and checks `role === "admin"`. Both redirect to `/login` if not authenticated.

---

## 11. Security Considerations

### 11.1 Secrets discipline

The following fields must never appear in logs, audit entries, or API responses:

| Field | Location | Rule |
|-------|----------|-------|
| `client_secret` (Zscaler API) | `TenantConfig.client_secret_enc` | Already enforced; unchanged |
| `oidc_client_secret` (SSO provider) | `SsoConfig.oidc_client_secret_enc` | Same Fernet treatment; omit from all responses |
| `saml_private_key` (SP signing key) | `SsoConfig.saml_private_key_enc` | Same Fernet treatment; omit from all responses |
| Admin initial password | Bootstrap stdout print only | Never written to DB, log, or audit |
| User passwords (any) | Never stored in plaintext | bcrypt hash only |

### 11.2 CORS and credentialed requests

From `web-frontend.md` section 9: `allow_credentials=True` + `ALLOWED_ORIGINS=*` is broken for credentialed requests (browser spec prohibits it). With auth added, this is no longer just a footgun — it is a functional breakage. The startup warning in section 3.1 covers the SSO case. Additionally:

- The React frontend must send `credentials: "include"` on all fetch calls to allow the refresh token cookie to be sent
- This requires `ALLOWED_ORIGINS` to be set to the actual origin in any non-localhost deployment
- Document prominently in README and deployment notes

### 11.3 Refresh token cookie settings

- `HttpOnly`: yes — not accessible to JavaScript
- `SameSite=Strict`: safe for same-origin (localhost dev, desktop). For server deployments where frontend and API are on the same domain, `Strict` is correct. If they are on different subdomains, `Lax` is needed. Treat as a constant for MVP; document as a configuration concern.
- `Secure`: should be `True` in production (HTTPS only). Add a `ZS_SECURE_COOKIES` env var (default `False`) so bare-metal development does not require HTTPS.
- `Path=/api/v1/auth/refresh`: scopes the cookie to the refresh endpoint only — it is not sent on every API request

### 11.4 Password hashing

`bcrypt` cost factor 12 (passlib default). Admin bootstrap uses `bcrypt.gensalt()` directly (same factor). Do not reduce cost factor in tests — use a test fixture that bypasses hashing instead.

### 11.5 JWT secret requirements

`JWT_SECRET` must be at least 32 bytes of entropy. Add a startup check:

```python
jwt_secret = os.environ.get("JWT_SECRET", "")
if len(jwt_secret) < 32:
    sys.exit("FATAL: JWT_SECRET must be at least 32 characters.")
```

---

## 12. What Is NOT in Scope for MVP

| Item | Notes |
|------|-------|
| MFA / TOTP | Follow-on |
| Per-tenant role permissions beyond admin/user | Follow-on |
| Audit logging of auth events | Follow-on — auth events (login, logout, failed auth, password change) should eventually be in `AuditLog`. Excluded from MVP to keep scope tight. |
| API key auth for machine-to-machine | Follow-on |
| Group/team-based entitlement | Follow-on |
| JWT refresh token revocation / session table | Follow-on |
| JWT key rotation | Follow-on — design: `JWT_SECRET_PREV` env var for rolling rotation |
| Pre-provisioning SSO users (SCIM) | Follow-on |
| Rate limiting on `/api/v1/auth/login` | Follow-on — recommend `slowapi` + Redis or in-memory counter |

---

## 13. Open Questions

1. **`SameSite` cookie for cross-subdomain deploys**: if the React frontend is served from `app.host.com` and the API from `api.host.com`, `SameSite=Strict` blocks the refresh cookie. `SameSite=Lax` would be needed. Decision needed before production deployment guidance is written. For MVP (same origin), `Strict` is correct.

2. **SAML SP metadata endpoint**: `python3-saml` can generate SP metadata XML at a well-known URL (typically `GET /api/v1/auth/saml/metadata`). Some IdPs require this URL during SP registration. Should this endpoint be added? It has no auth requirement (public endpoint) and exposes only the public SP cert and entity ID — no sensitive data. Recommend adding it, but marking it as optional for the MVP endpoint table above.

3. ~~**OIDC redirect URI registration**~~ — **Resolved**: store `oidc_redirect_uri` as an explicit field in `SsoConfig`. Operators set it to the full public URL (e.g. `https://zs-config.corp.com/api/v1/auth/oidc/callback`). The API uses this stored value when building the authorization URL and when exchanging the code — it never derives the URI from the incoming request. Add `oidc_redirect_uri = Column(String(1024), nullable=True)` to the `SsoConfig` model and expose it as an editable field in the admin SSO UI (required when OIDC is enabled).

4. **Admin account username change**: the built-in account is hardcoded as `username="admin"`. Should admins be able to rename it? Recommend: no — the bootstrap check uses `role="admin"`, not `username="admin"`, so the username is cosmetic only. Admins can create additional admin accounts. Rename can be added as a follow-on.

5. **`bcrypt` import approach**: the spec uses `import bcrypt` directly in the lifespan bootstrap. `passlib[bcrypt]` wraps bcrypt and provides the CryptContext API which is more ergonomic for the rest of the auth service. Decision: use `passlib.context.CryptContext` everywhere in the auth service module; the lifespan bootstrap can import from the auth service rather than calling bcrypt directly. This avoids two different bcrypt call styles in the codebase.
