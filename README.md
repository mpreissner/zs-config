# zscaler-scripts

Automation toolset for Zscaler OneAPI — headless scripts, interactive TUI, and a REST API ready for a future GUI.

## Architecture

```
zscaler-scripts/
│
├── lib/               # Low-level API clients (auth + per-product HTTP wrappers)
│   ├── auth.py          # Shared OAuth2 client_credentials token manager
│   ├── zpa_client.py    # ZPA raw API methods
│   ├── zia_client.py    # ZIA raw API methods
│   ├── rate_limiter.py  # Rolling-window rate limiter (respects API limits)
│   └── conf_writer.py   # zscaler-oneapi.conf writer (chmod 600)
│
├── db/                # Database layer (SQLAlchemy + SQLite by default)
│   ├── models.py      # TenantConfig, AuditLog, Certificate, ZPAResource, SyncLog
│   └── database.py    # Engine setup, session context manager
│
├── services/          # Business logic — shared by CLI, scripts, and API
│   ├── config_service.py      # Tenant CRUD with encrypted secret storage
│   ├── audit_service.py       # Operation audit logging
│   ├── zpa_service.py         # ZPA workflows (cert rotation, etc.)
│   ├── zpa_import_service.py  # ZPA config import (pulls live config into DB)
│   └── zia_service.py         # ZIA workflows (activation, etc.)
│
├── scripts/           # Headless automation scripts (server-deployed)
│   ├── zpa/
│   │   ├── cert-upload.py  # Certificate rotation (acme.sh deploy hook)
│   │   └── deploy.sh       # Shell wrapper for acme.sh
│   └── zia/
│
├── cli/               # Interactive Rich TUI
│   ├── zscaler-cli.py
│   ├── session.py         # Process-level active tenant state
│   └── menus/
│       ├── main_menu.py   # Main menu + settings + audit log viewer
│       ├── zpa_menu.py    # ZPA certificate management + config import
│       └── zia_menu.py    # ZIA activation + URL lookup
│
├── api/               # FastAPI REST API (future GUI backend)
│   ├── main.py
│   ├── routers/
│   │   ├── zpa.py
│   │   └── zia.py
│   └── schemas/
│       ├── zpa.py
│       └── zia.py
│
├── config/            # Server-side credential templates
│   └── zscaler-oneapi.conf
│
└── data/              # SQLite database (git-ignored)
    └── zscaler.db
```

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Generate an encryption key
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Add to your shell profile:
```bash
export ZSCALER_SECRET_KEY=<generated_key>
```

### 3. Launch the CLI
```bash
python cli/zscaler-cli.py
```
Go to **Settings → Manage Tenants → Add Tenant** to register your first Zscaler tenant.

---

## Headless Script Usage (acme.sh deploy hook)

### Option A — Environment variables (server deployment)
Copy `config/zscaler-oneapi.conf` to `/etc/zscaler-oneapi.conf`, fill in your credentials, then:
```bash
# Register with acme.sh
acme.sh --deploy -d "*.example.com" --deploy-hook /path/to/scripts/zpa/deploy.sh
```

### Option B — Database tenant (interactive setup required first)
```bash
python scripts/zpa/cert-upload.py /path/to/cert.pem /path/to/key.pem "*.example.com" --tenant prod
```

---

## Config Import (ZPA)

The CLI can pull a full snapshot of your ZPA configuration into the local database.

Launch the CLI, select a tenant, then go to **ZPA → Import Config**.

The import fetches 18 resource types (applications, segment groups, connectors, PRA portals, policies, certificates, etc.) and stores each as a `ZPAResource` row with the full JSON payload.  Subsequent imports only write rows whose content has changed (SHA-256 comparison), so re-runs are fast.

Rate limiting is applied automatically (conservative 15 req/10 s) so the import won't trigger API throttling.  A typical tenant with ~80 resources takes roughly 60 seconds on first run.

Once imported, resources can be queried directly from the SQLite database or (in future) compared across tenants, replayed to a new environment, or diffed between snapshots.

---

## REST API (future GUI)

```bash
uvicorn api.main:app --reload
```
OpenAPI docs: http://localhost:8000/docs

---

## Database

SQLite by default (`data/zscaler.db`). Override with:
```bash
export ZSCALER_DB_URL="postgresql://user:pass@host/dbname"
```

The database stores:
- **TenantConfig** — connection details per Zscaler tenant (secrets encrypted at rest)
- **AuditLog** — immutable record of every operation performed
- **Certificate** — lifecycle tracking for certs managed by this toolset
- **ZPAResource** — full JSON snapshot of every ZPA resource (one row per `tenant × type × id`); SHA-256 hash enables fast change detection on re-import
- **SyncLog** — outcome of each config-import run (status, counters, error messages)

---

## Extending

- **New ZPA endpoint** → add a method to `lib/zpa_client.py`, expose it in `services/zpa_service.py`
- **New automation script** → create `scripts/<product>/your-script.py`, import from `lib/` and `services/`
- **New CLI menu** → add a menu file under `cli/menus/`, wire it into `cli/menus/main_menu.py`
- **New API endpoint** → add a route to `api/routers/<product>.py`
- **New product** (ZCC, ZDX, etc.) → add `lib/<product>_client.py` + `services/<product>_service.py`, follow the same pattern
