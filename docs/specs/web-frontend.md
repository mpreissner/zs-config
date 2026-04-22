# Spec: React Web Frontend + Docker Containerization

**Feature branch**: `feature/web-frontend` (from `dev`)  
**Status**: Draft — awaiting implementation sign-off  
**Scope**: MVP React UI served by FastAPI, single-container Docker image, docker-compose, Kubernetes notes

---

## 1. Directory Layout

```
zs-config/
├── web/                          # React + Vite source (new)
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                  # typed fetch wrappers (one file per router)
│       │   ├── tenants.ts
│       │   ├── audit.ts
│       │   ├── zia.ts
│       │   └── zpa.ts
│       ├── components/           # shared UI components
│       ├── pages/                # route-level components
│       │   ├── TenantsPage.tsx
│       │   ├── AuditPage.tsx
│       │   ├── ZiaPage.tsx
│       │   └── ZpaPage.tsx
│       └── hooks/
├── api/
│   ├── main.py                   # add StaticFiles mount + SPA fallback + /api/v1/system/info
│   ├── routers/
│   │   ├── zia.py
│   │   ├── zpa.py
│   │   └── system.py             # new — hosts /api/v1/system/info
│   └── static/                   # Vite build output lands here (git-ignored)
│       └── .gitkeep
├── Dockerfile                    # new
├── docker-compose.yml            # new
└── .dockerignore                 # new
```

**Vite output path**: `vite.config.ts` sets `build.outDir = "../api/static"` (relative to `web/`).  
FastAPI mounts `api/static` as `StaticFiles` at `/`. All `/api/*` routes take priority because the router is registered before `StaticFiles`. Unmatched routes return `api/static/index.html` for SPA client-side routing (see section 5).

The `api/static/` directory is git-ignored. The Dockerfile build stage runs `npm run build` and copies the output directly, so the directory never needs to exist in version control.

---

## 2. Dockerfile

Multi-stage build. Stage 1 compiles the React app; Stage 2 is the Python runtime. No nginx.

```dockerfile
# ── Stage 1: Node / Vite build ──────────────────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --prefer-offline

COPY web/ ./
# Vite config already sets outDir = "../api/static"
RUN npm run build


# ── Stage 2: Python runtime ──────────────────────────────────────────────────
# Pin to a digest for production builds — Python minor version upgrades are
# intentional image rebuilds, not automatic. Example:
#   FROM python:3.12-slim@sha256:<digest> AS runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# System deps: git is needed by pip for plugin installs from GitHub URLs
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install Python deps (api extras required)
COPY pyproject.toml requirements.txt* ./
RUN pip install --no-cache-dir ".[api]"

# Copy application source
COPY api/      ./api/
COPY cli/      ./cli/
COPY db/       ./db/
COPY lib/      ./lib/
COPY services/ ./services/

# Copy compiled frontend from stage 1
COPY --from=frontend-build /build/api/static ./api/static

# Data directories — real content comes from mounted volumes
RUN mkdir -p /data/db /data/plugins

# Non-root user for defence-in-depth
RUN useradd -r -u 1001 -g root zsconfig && chown -R zsconfig:root /app /data
USER zsconfig

ENV ZS_CONTAINER_MODE=1
ENV ZSCALER_DB_PATH=/data/db/zscaler.db
ENV ZS_PLUGIN_DIR=/data/plugins
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Base image notes**:
- `node:22-alpine` — small, LTS-aligned. Pin to a digest for production builds.
- `python:3.12-slim` — matches current dev environment. Upgrade to 3.13 when `zscaler-sdk-python` confirms compatibility.
- `git` is installed in the runtime image because `install_plugin()` runs `pip install git+https://...` via subprocess. Without git, plugin install silently fails or errors.

**What is NOT copied**:
- `cli/` TUI code is copied because `services/` imports from it indirectly (e.g. `cli/banner.py` for `VERSION`). If this import is ever cleaned up, `cli/` can be excluded.
- `reference/` (Postman collections) — excluded via `.dockerignore`
- `web/` source — only the compiled output from stage 1 is needed at runtime
- `.env`, `*.db`, `dist/`, `*.egg-info/` — excluded via `.dockerignore`

---

## 3. docker-compose.yml

```yaml
version: "3.9"

services:
  zs-config:
    build: .
    image: zs-config:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - zs-db:/data/db
      - zs-plugins:/data/plugins
    environment:
      ZS_CONTAINER_MODE: "1"
      ZSCALER_DB_PATH: /data/db/zscaler.db
      ZS_PLUGIN_DIR: /data/plugins
      # Lock down CORS in production — comma-separated list of allowed origins
      # ALLOWED_ORIGINS: "https://your-host.example.com"
      # Optional: supply a corporate CA bundle
      # REQUESTS_CA_BUNDLE: /data/db/ca-bundle.pem
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  zs-db:
  zs-plugins:
```

**Volume semantics**:

| Volume | Mount path | Contents | Survives image update? |
|--------|-----------|----------|------------------------|
| `zs-db` | `/data/db` | `zscaler.db` (SQLite), optional `ca-bundle.pem` | Yes |
| `zs-plugins` | `/data/plugins` | pip-installed plugin packages | Yes |

The `ca-bundle.pem` convention from `cli/z_config.py` (`~/.config/zs-config/ca-bundle.pem`) does not translate directly to a container. The recommended approach is to drop `ca-bundle.pem` into the `zs-db` volume at `/data/db/ca-bundle.pem` and set `REQUESTS_CA_BUNDLE=/data/db/ca-bundle.pem` in the compose environment block.

---

## 4. Kubernetes Notes

This section is intentionally brief — full k8s manifests are out of scope for the MVP.

**PVC equivalents for the two volumes**:

```yaml
# db PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: zs-config-db
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi

# plugins PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: zs-config-plugins
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
```

Both volumes use `ReadWriteOnce` — the container is single-replica (SQLite has no concurrent write story). If HA is ever needed, the DB layer must move to Postgres first.

Mount the PVCs at `/data/db` and `/data/plugins` respectively in the Deployment pod spec. Pass the same env vars as the compose file.

`ALLOWED_ORIGINS` should be set via a k8s `ConfigMap` or `Secret` rather than hardcoded in the manifest.

**Secrets**: `ALLOWED_ORIGINS` is not sensitive, but any future API auth tokens or signing keys should live in a k8s `Secret` with `secretKeyRef`, not in the pod spec directly.

---

## 5. API Additions Needed

### 5.1 Static file serving and SPA fallback

Add to `api/main.py` after all routers are registered:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib

_STATIC_DIR = pathlib.Path(__file__).parent / "static"

if _STATIC_DIR.exists():
    # Mount assets (JS/CSS/fonts) at /assets — Vite outputs here
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Catch-all: return index.html for any path not matched by an API router."""
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"detail": "Frontend not built"}, 404
```

The conditional `if _STATIC_DIR.exists()` means the API continues to work normally in bare-metal dev mode where the frontend has not been built. This is important: `uvicorn api.main:app --reload` for backend development must not require the frontend to be built first.

Order matters: all `app.include_router(...)` calls and named `@app.get(...)` endpoints must be registered before the catch-all. The catch-all must be last.

### 5.2 `GET /api/v1/system/info` (new router: `api/routers/system.py`)

```python
# api/routers/system.py
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
```

Register in `api/main.py`:
```python
from api.routers import system
app.include_router(system.router)
```

The web UI fetches `/api/v1/system/info` on load and uses `container_mode` to decide whether to show the "Check for updates" button.

### 5.3 Tenant CRUD endpoints (missing from current API)

`GET /api/v1/tenants` exists (read-only list). The web UI needs the following for MVP tenant management:

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/tenants/{id}` | Single tenant detail (no `client_secret` field — see section 9) |
| `POST` | `/api/v1/tenants` | Create tenant; accepts `client_secret` in request body, encrypts before storage |
| `PUT` | `/api/v1/tenants/{id}` | Update tenant; same secret handling |
| `DELETE` | `/api/v1/tenants/{id}` | Delete tenant and cascade |

These endpoints call `services/config_service.py` functions only. The raw `client_secret` must never appear in any response body (see section 9).

A `has_credentials` boolean field (True/False, derived from whether `client_secret_enc` is set) is acceptable in responses as a status indicator.

### 5.4 ZIA activation state

The existing `GET /api/v1/zia/{tenant}/activation/status` endpoint is sufficient for the web UI to surface pending activation state. No new endpoint needed — the React UI should poll this and show a banner when activation is pending.

### 5.5 Endpoints that are NOT needed for MVP

- Plugin install/uninstall via the API — the plugin manager runs pip as a subprocess and writes to the filesystem. This is fundamentally a CLI-side operation. Expose it in a follow-on iteration once the security model for running arbitrary pip installs from an HTTP endpoint is designed properly.
- ZIA snapshot/restore — the existing snapshot service is correct but the API router is not stubbed. Out of scope for MVP.
- Auth/login flow — see section 9.

---

## 6. Auto-Update Gating

### Call sites that must be guarded

In `cli/z_config.py`, lines 126–128:

```python
# Current code (no guard):
zs_update_found = check_for_updates()
if not zs_update_found:
    check_plugin_updates()
```

Change to:

```python
import os

_container_mode = os.environ.get("ZS_CONTAINER_MODE", "0") == "1"
if not _container_mode:
    zs_update_found = check_for_updates()
    if not zs_update_found:
        check_plugin_updates()
```

Also guard the deferred plugin install block at lines 118–123 of `cli/z_config.py`:

```python
# Current code (no guard):
from lib.plugin_manager import get_pending_plugin_install, clear_pending_plugin_install
_pending = get_pending_plugin_install()
if _pending:
    from cli.menus.plugin_menu import _complete_pending_install
    _complete_pending_install(_pending)
    clear_pending_plugin_install()
```

The deferred install flow calls `questionary` (interactive TTY) and assumes a TUI context. Wrap it with the same `if not _container_mode` guard. In container mode there is no TTY, so running this would hang or crash.

### Why `check_for_updates()` itself is not the right place for the guard

`check_for_updates()` is the right function signature boundary — the guard goes in `z_config.py` so the function remains independently testable. Do not add the env-var check inside `update_checker.py`.

---

## 7. Plugin Volume and Directory Discovery

### Current state

`lib/plugin_manager.py` uses Python's `importlib.metadata.entry_points(group="zs_config.plugins")` for discovery and `pip install`/`pip uninstall` via subprocess for install/uninstall. Plugins install into the active Python environment (`sys.executable`'s site-packages), not a custom directory.

This means the "plugin volume" is not a directory of plugin source files — it is the site-packages of the Python interpreter running inside the container. The `zs-plugins` Docker volume must be mounted at a path that pip uses as a target.

### Recommended approach

Set `PYTHONUSERBASE` to the plugin volume mount point:

```
ENV PYTHONUSERBASE=/data/plugins
```

Then run pip with `--user`:

```python
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "--user", url],
    ...
)
```

This directs pip to install into `/data/plugins/lib/pythonX.Y/site-packages/`. Because `PYTHONUSERBASE` is set, Python automatically includes this path on `sys.path`, so entry point discovery works without any code changes.

**Risk**: `install_plugin()` in `lib/plugin_manager.py` currently does not pass `--user`. Adding `--user` when `ZS_PLUGIN_DIR` (or `PYTHONUSERBASE`) is set requires a small change to `install_plugin()`. The same applies to `uninstall_plugin()`.

**Proposed change to `lib/plugin_manager.py`**:

```python
def _pip_install_args() -> list[str]:
    """Return extra pip args for plugin install. Adds --user in container mode."""
    if os.environ.get("ZS_CONTAINER_MODE") == "1":
        return ["--user"]
    return []

def _pip_uninstall_args() -> list[str]:
    if os.environ.get("ZS_CONTAINER_MODE") == "1":
        return ["--user"]
    return []
```

Then in `install_plugin()`:
```python
[sys.executable, "-m", "pip", "install", *_pip_install_args(), url],
```

And in `uninstall_plugin()`:
```python
[sys.executable, "-m", "pip", "uninstall", "--yes", *_pip_uninstall_args(), package_name],
```

**Bare-metal default**: When `ZS_CONTAINER_MODE` is not set, behavior is unchanged — plugins install into the active environment as before. `ZS_PLUGIN_DIR` env var and `PYTHONUSERBASE` are both left unset.

**Inside the container**: `PYTHONUSERBASE=/data/plugins` is set in the Dockerfile ENV (and can be overridden per compose/k8s). The `zs-plugins` volume backs this directory, so plugins persist across container image upgrades.

---

## 8. React App Scope (MVP)

### In scope

| Area | What the MVP covers |
|------|---------------------|
| Tenant list | Read-only list of tenants from `GET /api/v1/tenants`; show name, cloud URLs, govcloud flag, created date |
| Tenant management | Create, edit, delete tenants via the new CRUD endpoints (section 5.3) |
| Audit log viewer | Paginated table from `GET /api/v1/audit`; filter by tenant and product; timestamp, operation, action, status, resource name, details |
| ZIA status | Per-tenant: activation status badge, trigger activation button |
| ZIA URL lookup | Form to submit URLs, display categorization results |
| ZPA certificates | List certs per tenant |
| System info bar | `container_mode`, version string; hide update-checker UI when `container_mode=true` |
| Health indicator | Polls `GET /health`; shows connected/disconnected badge |

### Explicitly out of scope for MVP

- Plugin install/uninstall UI (security design needed first — see section 5.5)
- ZPA certificate rotation form (file upload from browser to container to Zscaler is a multi-step design problem)
- ZIA snapshot/restore UI
- Tenant credential rotation / re-auth flow
- Dark/light theme toggle (use system preference via CSS `prefers-color-scheme` only)
- Internationalization
- Auth/login for the API itself (see section 9)
- Real-time streaming / websockets

### Recommended React stack for MVP

| Concern | Library | Rationale |
|---------|---------|-----------|
| Build | Vite + TypeScript | Fast dev server; matches the spec |
| Routing | React Router v6 | Standard SPA routing |
| Data fetching | TanStack Query v5 | Cache, background refetch, loading states without Redux |
| UI components | shadcn/ui (Tailwind) | Composable, no runtime dependency, small bundle |
| Tables | TanStack Table v8 | Used by shadcn/ui data-table patterns |

Do not introduce a full state manager (Redux, Zustand) in the MVP. TanStack Query's server-state cache is sufficient.

---

## 9. Security Considerations

### CORS

`api/main.py` already reads `ALLOWED_ORIGINS` from the environment:
```python
allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
```

In the Dockerfile, `ALLOWED_ORIGINS` defaults to `*` (permissive). This is acceptable for local desktop use (`docker run`, `localhost`).

**Production requirement**: operators deploying to a server must set `ALLOWED_ORIGINS` to the actual host(s). The docker-compose template includes this as a commented-out example. The `GET /api/v1/system/info` response should NOT include `allowed_origins` — this would expose the CORS config to any caller and is unnecessary.

### Authentication

The API is currently unauthenticated. This is acceptable for desktop use (only localhost reaches it). It is not acceptable for any networked or multi-user deployment.

The natural insertion point for auth is FastAPI middleware or a dependency injected into all routers:

```python
# Future: api/dependencies.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer

security = HTTPBearer()

def require_auth(token = Security(security)):
    # validate JWT or API key here
    ...
```

**Auth is out of scope for this spec.** A follow-on spec should cover: token issuance, session expiry, and whether the auth store lives in the SQLite DB or a separate system. The key constraint is that adding auth must not break the existing bare-metal CLI or headless script flows, which bypass the API layer entirely.

**Call-out for operators**: until auth is implemented, do not expose port 8000 on a network interface reachable by untrusted users. In the compose file the default binding is `127.0.0.1:8000:8000` — change the docker-compose template to use `127.0.0.1:8000:8000` not `0.0.0.0` to make this safe by default.

Update the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "127.0.0.1:8000:8000"    # change to "0.0.0.0:8000:8000" deliberately for server deploy
```

### Secrets — client_secret

**Non-negotiable rule** (already in `CLAUDE.md`): `client_secret` must never appear in logs, audit entries, or API responses.

Specific constraints for the API layer:

1. The `GET /api/v1/tenants` and `GET /api/v1/tenants/{id}` response serializers must not include `client_secret_enc` or any decrypted form.
2. The `POST /api/v1/tenants` and `PUT /api/v1/tenants/{id}` request bodies accept `client_secret` in plaintext, but it must be encrypted via `services/config_service.decrypt_secret` before any DB write and must not be echoed back in the response.
3. FastAPI's automatic OpenAPI schema generation will expose the request model shape — acceptable, but the field should be marked `write_only=True` in the Pydantic model.
4. The `GET /api/v1/audit` response already excludes credentials (audit events are written by `services/` which never stores secrets). No change needed.
5. Uvicorn access logs must not be set to debug level in production (request body logging would capture secrets in POST payloads). The default `--log-level info` is correct.

### Docker image

- The image runs as non-root user `zsconfig` (uid 1001). See Dockerfile.
- The SQLite file is created with mode 0600 by `db/database.py:_secure_db_file()` — this already works because the file is created inside the container by the same process that owns it.
- The plugin directory at `/data/plugins` should have mode 0700 — the Dockerfile sets this via `chown -R zsconfig:root /data`.

---

## 10. Open Questions

These must be resolved before or during implementation:

1. **Plugin install in container mode — pip target** — RESOLVED  
   Decision: option (a). The base image is pinned to `python:3.12-slim` with a digest for production builds. Python minor version upgrades are treated as intentional image rebuilds, not automatic updates. No symlink scripts or venv bootstrapping are added. Operators who upgrade the image to a new Python minor version must reinstall plugins. See the Dockerfile comment in section 2 for the digest-pinning instruction.

2. **CORS wildcard for localhost**  
   When `ALLOWED_ORIGINS=*`, `allow_credentials=True` is silently ignored by browsers (the spec prohibits credentialed cross-origin requests to wildcard origins). For the MVP this is fine because there are no credentials in request headers. If auth is added (bearer tokens), `ALLOWED_ORIGINS` must be locked down to a specific origin before credentials work. This is a footgun — document it prominently in the README.

3. **`cli/banner.py` import in API context**  
   `api/routers/system.py` imports `from cli.banner import VERSION`. The `cli/` package is included in the Docker image for this reason (see section 2). If the intent is to eventually produce a "server-only" image that excludes the TUI, `VERSION` should be moved to a `version.py` module at the package root and imported from there by both `cli/banner.py` and `api/`. This is a minor refactor but worth noting as a future cleanup.

4. **DB path on Windows bare-metal vs container**  
   `db/database.py` has Windows-specific path logic using `APPDATA`. Inside the container (Linux), this code path is never reached. No action needed, but worth confirming the Windows path logic is not broken by the new `ZSCALER_DB_PATH` env var being set in the container image ENV (it is not — the env var is only present when `ZS_CONTAINER_MODE=1` which is not set on Windows bare-metal).

5. **`_migrate_db_path()` in container**  
   `db/database.py:_migrate_db_path()` is called unconditionally when `ZSCALER_DB_URL` and `ZSCALER_DB_PATH` are both unset. In the container, `ZSCALER_DB_PATH` is always set, so `_migrate_db_path()` is skipped. This is correct. No action needed — just confirm no operator accidentally omits `ZSCALER_DB_PATH` from their environment. The Dockerfile `ENV` statement ensures it is always set in the image.

6. **Vite base path for sub-path deployments**  
   If operators reverse-proxy the API under a sub-path (e.g. `https://host/zs-config/`), Vite's default `base: "/"` will produce broken asset paths. For the MVP, assume the app is served at the root. Document this limitation. If sub-path support is needed, add a `ZS_BASE_PATH` env var and thread it through both Vite's `base` option (build-time) and FastAPI's `root_path` (runtime).

7. **`requirements.txt` vs `pyproject.toml` in Docker**  
   The Dockerfile uses `pip install ".[api]"` which reads `pyproject.toml`. The repo also has a `requirements.txt`. These may drift. The Coder should verify whether `requirements.txt` is generated from `pyproject.toml` or maintained separately, and consolidate if possible. The `api` optional dependency group in `pyproject.toml` already has the right shape.
