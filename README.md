# z-config

Automation toolset for Zscaler OneAPI — interactive TUI, headless scripts, and a REST API backend.

## Architecture

```
z-config/
│
├── lib/               # Low-level API clients
│   ├── auth.py          # OAuth2 client_credentials token manager
│   ├── zpa_client.py    # ZPA API methods
│   ├── zia_client.py    # ZIA API methods
│   └── conf_writer.py   # zscaler-oneapi.conf writer (chmod 600)
│
├── db/                # Database layer (SQLAlchemy + SQLite by default)
│   ├── models.py      # TenantConfig, AuditLog, Certificate, ZPAResource, SyncLog
│   └── database.py    # Engine setup, session context manager
│
├── services/          # Business logic — shared by CLI, scripts, and API
│   ├── config_service.py        # Tenant CRUD with encrypted secret storage
│   ├── audit_service.py         # Operation audit logging
│   ├── zpa_service.py           # ZPA workflows (cert rotation, etc.)
│   ├── zpa_import_service.py    # ZPA config import (pulls live config into DB)
│   ├── zpa_segment_service.py   # App segment bulk-create logic
│   └── zia_service.py           # ZIA workflows
│
├── scripts/           # Headless automation scripts (server-deployed)
│   └── zpa/
│       ├── cert-upload.py  # Certificate rotation (acme.sh deploy hook)
│       └── deploy.sh       # Shell wrapper for acme.sh
│
├── cli/               # Interactive Rich TUI
│   ├── zscaler-cli.py
│   ├── session.py
│   └── menus/
│       ├── main_menu.py   # Main menu, settings, audit log viewer
│       ├── zpa_menu.py    # ZPA — app segments, certificates, import
│       └── zia_menu.py    # ZIA — activation, URL lookup
│
├── api/               # FastAPI REST API (future GUI backend)
│   └── ...
│
├── config/            # Server-side credential templates
│   └── zscaler-oneapi.conf
│
└── data/              # SQLite database (git-ignored)
    └── zscaler.db
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Launch the CLI

```bash
python cli/zscaler-cli.py
```

An encryption key is generated automatically on first launch and saved to `~/.config/zscaler-cli/secret.key`.  No manual setup required.

Go to **Settings → Manage Tenants → Add Tenant** to register your first Zscaler tenant.

> **Override:** set `ZSCALER_SECRET_KEY` in your environment to use a specific key instead of the auto-generated one.

---

## CLI — ZPA Menu

### Config Import

**ZPA → Import Config**

Pulls a full snapshot of your ZPA tenant into the local SQLite database.  Fetches 18 resource types (applications, segment groups, server groups, connectors, PRA portals, policies, certificates, and more) and stores each as a `ZPAResource` row.  Subsequent imports only update rows whose content has changed (SHA-256 comparison), so re-runs are fast.

Run Import Config before using any feature that reads from the local DB (List Segments, Bulk Create dependency resolution, etc.).

---

### Application Segments

**ZPA → Application Segments**

| Option | Description |
|---|---|
| List Segments | Table view of all imported segments — filter by All / Enabled / Disabled |
| Search by Domain | Find segments by FQDN substring match |
| Enable / Disable | Toggle a segment's enabled state live (calls ZPA API + audit log) |
| Bulk Create from CSV | Import new segments from a CSV file (see below) |
| Export CSV Template | Write a ready-to-edit template to disk |
| CSV Field Reference | In-tool reference: accepted values for every field |

---

### Bulk Create from CSV

**ZPA → Application Segments → Bulk Create from CSV**

The workflow runs in stages:

1. **Parse & validate** — checks required fields and port format; invalid rows are shown with specific error messages.  You can abort or skip invalid rows and continue.
2. **Dry run** — resolves segment group and server group names against the local DB.  Each row is tagged:
   - `READY` — all dependencies found, will be created
   - `MISSING_DEPENDENCY` — a segment group or server group name wasn't found in the DB
   - `INVALID` — validation error
3. **Fix missing groups** *(optional)* — if any rows have missing dependencies, you can create the missing segment groups and server groups directly from the CLI.  A re-import is triggered automatically so the new groups are available for the next dry run.  Note: server groups created this way have no connector groups assigned — assign them in the ZPA portal afterwards.
4. **Confirm & create** — shows a count of READY rows.  Confirm to proceed.
5. **Progress bar** — segments are created one at a time; failures are collected without aborting the batch.
6. **Summary** — `✓ Created X  ✗ Failed Y  — Skipped Z` with per-row error details for any failures.

Every created resource is written to the audit log.

---

### CSV Format

Use **Export CSV Template** to get a pre-filled starting point, or build your own using the column reference below.

#### Required columns

| Column | Description |
|---|---|
| `name` | Segment name — must be unique within the tenant |
| `domain_names` | Semicolon-separated FQDNs, e.g. `app.example.com;*.internal.example.com` |
| `segment_group` | Exact name of an existing Segment Group (must be in local DB) |
| `server_groups` | Semicolon-separated Server Group names, e.g. `SG-East;SG-West` |
| `tcp_ports` | Required if `udp_ports` is blank — see port format below |
| `udp_ports` | Required if `tcp_ports` is blank — see port format below |

#### Optional columns (defaults shown)

| Column | Default | Accepted values |
|---|---|---|
| `description` | *(blank)* | Any string |
| `enabled` | `true` | `true` / `false` |
| `app_type` | `BROWSER_ACCESS` | `BROWSER_ACCESS` \| `SIPA` \| `INSPECT` \| `SECURE_REMOTE_ACCESS` |
| `bypass_type` | `NEVER` | `NEVER` \| `ALWAYS` \| `ON_NET` |
| `double_encrypt` | `false` | `true` / `false` |
| `health_check_type` | `DEFAULT` | `DEFAULT` \| `NONE` |
| `health_reporting` | `ON_ACCESS` | `NONE` \| `ON_ACCESS` \| `CONTINUOUS` |
| `icmp_access_type` | `NONE` | `NONE` \| `PING` \| `PING_TRACEROUTING` |
| `passive_health_enabled` | `true` | `true` / `false` |
| `is_cname_enabled` | `true` | `true` / `false` |
| `select_connector_close_to_app` | `false` | `true` / `false` |

#### Port format

| Example | Meaning |
|---|---|
| `443` | Single port |
| `8080-8090` | Range (inclusive) |
| `80;443;8080-8090` | Multiple entries, semicolon-separated |

---

### Certificate Management

**ZPA → Certificate Management**

| Option | Description |
|---|---|
| List Certificates | Show all certificates in the tenant |
| Rotate Certificate for Domain | Upload a new PEM cert+key, update all matching App Segments and PRA Portals, delete the old cert |
| Delete Certificate | Remove a certificate by selection |

---

## Headless Script — Certificate Rotation (acme.sh)

For server-deployed automated certificate rotation:

### Option A — Config file
Copy `config/zscaler-oneapi.conf` to `/etc/zscaler-oneapi.conf`, fill in credentials, then register with acme.sh:
```bash
acme.sh --deploy -d "*.example.com" --deploy-hook /path/to/scripts/zpa/deploy.sh
```

### Option B — Database tenant
```bash
python scripts/zpa/cert-upload.py /path/to/cert.pem /path/to/key.pem "*.example.com" --tenant prod
```

---

## Database

SQLite by default at `data/zscaler.db` (git-ignored). Override with:
```bash
export ZSCALER_DB_URL="postgresql://user:pass@host/dbname"
```

| Table | Contents |
|---|---|
| `TenantConfig` | Connection details per Zscaler tenant (client secret encrypted at rest) |
| `AuditLog` | Immutable record of every operation performed |
| `Certificate` | Lifecycle tracking for certs managed by this toolset |
| `ZPAResource` | Full JSON snapshot of every ZPA resource (`tenant × type × id`); SHA-256 hash enables fast change detection on re-import |
| `SyncLog` | Outcome of each import run (status, counters, errors) |

---

## Encryption Key

Tenant secrets are encrypted with [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption.

- **Auto-managed:** on first launch a key is generated and saved to `~/.config/zscaler-cli/secret.key` (chmod 600).
- **Env var override:** set `ZSCALER_SECRET_KEY` to use a specific key.
- **Rotation:** go to **Settings → Generate Encryption Key**.  Warning: rotating the key makes previously saved tenant secrets unreadable — re-add tenants after rotating.

---

## Extending

- **New ZPA endpoint** → add a method to `lib/zpa_client.py`
- **New automation script** → create `scripts/<product>/your-script.py`
- **New CLI menu** → add a file under `cli/menus/`, wire into `main_menu.py`
- **New product** (ZCC, ZDX, etc.) → add `lib/<product>_client.py` + `services/<product>_service.py`
