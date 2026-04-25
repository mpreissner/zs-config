# Spec: Web Frontend v2 — Full CRUD, Nav Redesign, FIDO2, Route Structure

**Feature branch**: `feature/web-frontend`  
**Status**: Draft  
**Builds on**: `docs/specs/web-frontend.md` (MVP — auth, Docker, static serving)

---

## Table of Contents

1. [Overview and Scope](#1-overview-and-scope)
2. [DB Changes — WebAuthn Credential Table](#2-db-changes--webauthn-credential-table)
3. [Feature 1: FIDO2/WebAuthn for Local Users](#3-feature-1-fido2webauthn-for-local-users)
4. [Feature 2: Left Nav Redesign — Expandable Tenant Switcher](#4-feature-2-left-nav-redesign--expandable-tenant-switcher)
5. [Feature 3: Product Tabs per Active Tenant](#5-feature-3-product-tabs-per-active-tenant)
6. [Feature 4: Full CRUD / Actions](#6-feature-4-full-crud--actions)
7. [Feature 5: Route Structure](#7-feature-5-route-structure)
8. [New API Endpoints — Complete List](#8-new-api-endpoints--complete-list)
9. [New Frontend Components and Pages](#9-new-frontend-components-and-pages)
10. [Cross-Cutting Constraints](#10-cross-cutting-constraints)
11. [Backlog Impact](#11-backlog-impact)

---

## 1. Overview and Scope

The v1 frontend (implemented on `feature/web-frontend`) delivered: JWT auth, per-tenant ZIA/ZPA read-only views, tenant CRUD, admin user/entitlement management, and Docker packaging.

v2 adds:

| # | Feature | Summary |
|---|---------|---------|
| 1 | FIDO2/WebAuthn | Hardware key registration and login for local users |
| 2 | Nav redesign | Expandable tenant list in sidebar replaces flat "Tenants" link |
| 3 | Product tabs | ZIA/ZPA/ZDX/ZCC/ZID tabs per active tenant; sections mirror TUI groups |
| 4 | Full CRUD | REST endpoints + UI for create/edit/delete on key resource types |
| 5 | Route structure | New URL scheme: `/tenant/:id/zia`, `/tenant/:id/zpa`, etc. |

ZDX is analytics-only (read-only throughout). ZIA, ZPA, ZCC, and ZID get actionable operations.

---

## 2. DB Changes — WebAuthn Credential Table

### 2.1 SQLAlchemy Model

Add to `/Users/mike/Documents/CodeProjects/zs-config/db/models.py`:

```python
class WebAuthnCredential(Base):
    """FIDO2 / WebAuthn credential registered by a local user.

    One user may have multiple credentials (multiple hardware keys).
    Federated (SSO) users do not register credentials here — they do MFA
    at the IdP.
    """

    __tablename__ = "webauthn_credentials"

    id             = Column(Integer, primary_key=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id  = Column(Text, nullable=False, unique=True)  # base64url-encoded bytes
    public_key     = Column(Text, nullable=False)               # COSE key, base64url-encoded
    sign_count     = Column(Integer, nullable=False, default=0)
    aaguid         = Column(String(64), nullable=True)          # authenticator model GUID
    label          = Column(String(255), nullable=True)         # user-assigned name ("YubiKey 5")
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at   = Column(DateTime, nullable=True)

    user = relationship("User", backref="webauthn_credentials")

    def __repr__(self) -> str:
        return f"<WebAuthnCredential user_id={self.user_id} label={self.label!r}>"
```

### 2.2 Migration

Add an `ALTER TABLE` migration to `db/database.py` inside `_run_data_migrations()` (the same pattern as existing migrations). The migration creates the `webauthn_credentials` table if it does not exist, using `CREATE TABLE IF NOT EXISTS` via raw SQL executed against the connection. Do not use Alembic (it is in the backlog but not yet adopted).

The `init_db()` call in `api/main.py` runs `Base.metadata.create_all(engine)` which will create the new table on first startup in fresh installations. The `ALTER TABLE` migration path only matters for existing databases that already have a schema.

### 2.3 Dependency

```
py-webauthn>=2.0.0
```

Add to `pyproject.toml` under `[project.dependencies]` (not under `[api]` extras — FIDO2 is a core auth feature, not optional). `py-webauthn` does not depend on the zscaler SDK; no SDK-bug risk.

---

## 3. Feature 1: FIDO2/WebAuthn for Local Users

### 3.1 Scope

Only local users (those with `password_hash` set, `sso_provider IS NULL`) can register WebAuthn credentials. Federated users authenticate entirely at the IdP and are out of scope. WebAuthn coexists with password login: a user who has both a password and a registered key can use either. Registration of a key does not disable password login.

### 3.2 WebAuthn Registration Ceremony

**Step 1 — Begin registration**

```
POST /api/v1/auth/webauthn/register/begin
Authorization: Bearer <access_token>
```

Request body: `{ "label": "YubiKey 5 NFC" }` (optional label for the key)

Server actions:
1. Decode the JWT to get `user_id` and `username`.
2. Load existing credentials for this user from `webauthn_credentials` (used to exclude already-registered keys via `exclude_credentials`).
3. Call `py_webauthn.generate_registration_options(...)`:
   - `rp_id`: derived from `WEBAUTHN_RP_ID` env var (default `"localhost"`)
   - `rp_name`: `"zs-config"` (static)
   - `user_id`: `str(user_id).encode()` (bytes)
   - `user_name`: `username`
   - `exclude_credentials`: list of `{"id": base64url_decode(cred.credential_id), "type": "public-key"}` for all existing credentials
   - `authenticator_selection`: `{"user_verification": "preferred"}` — do not require UV so USB keys without PIN still work
   - `attestation`: `"none"` — we do not verify attestation; reduces complexity without security impact for internal tooling
4. Store the generated `challenge` in the server session (or a short-lived cache keyed by `user_id` and an opaque session token). The challenge must survive only for the duration of the ceremony (60 seconds max).
5. Return the `RegistrationOptions` as JSON (serialized via `py_webauthn.options_to_json(...)`).

Response: `200 OK`, body is the `PublicKeyCredentialCreationOptions` JSON that the browser passes to `navigator.credentials.create()`.

**Step 2 — Complete registration**

```
POST /api/v1/auth/webauthn/register/complete
Authorization: Bearer <access_token>
```

Request body: the raw `PublicKeyCredential` JSON from `navigator.credentials.create()` (the browser returns this; the frontend sends it as-is).

```json
{
  "label": "YubiKey 5 NFC",
  "credential": { /* PublicKeyCredential JSON */ }
}
```

Server actions:
1. Retrieve the stored challenge for this `user_id`.
2. Call `py_webauthn.verify_registration_response(...)`:
   - `credential`: parse the request body credential
   - `expected_challenge`: the stored challenge
   - `expected_rp_id`: `WEBAUTHN_RP_ID`
   - `expected_origin`: `WEBAUTHN_ORIGIN` env var (e.g. `"http://localhost:8000"`)
   - `require_user_verification`: `False` (matches `"preferred"` above)
3. On success, write a `WebAuthnCredential` row:
   - `credential_id`: base64url-encode `verified_registration.credential_id`
   - `public_key`: base64url-encode `verified_registration.credential_public_key`
   - `sign_count`: `verified_registration.sign_count`
   - `aaguid`: `str(verified_registration.aaguid)` if present
   - `label`: from request body (truncated to 255 chars)
4. Clear the stored challenge.
5. Write an audit event: `product=None, operation="register_webauthn", action="CREATE", status="SUCCESS", resource_type="webauthn_credential", resource_name=label`.

Response: `200 OK`, `{ "ok": true, "credential_id": "<base64url>" }`

On failure: `400 Bad Request`, `{ "detail": "<reason>" }`. Never log the raw credential bytes.

### 3.3 WebAuthn Authentication Ceremony

**Step 1 — Begin authentication**

```
POST /api/v1/auth/webauthn/authenticate/begin
```

No auth header required (the user is not yet logged in).

Request body: `{ "username": "alice" }`

Server actions:
1. Look up the `User` by `username`. If not found or `is_active=False`, return `404` (do not reveal whether the user exists — use a generic "No credentials found" message to the client).
2. Load all `WebAuthnCredential` rows for this `user_id`. If empty, return `400 { "detail": "No security keys registered" }`.
3. Call `py_webauthn.generate_authentication_options(...)`:
   - `rp_id`: `WEBAUTHN_RP_ID`
   - `allow_credentials`: list of `{"id": base64url_decode(cred.credential_id), "type": "public-key"}` for all registered keys
   - `user_verification`: `"preferred"`
4. Store challenge keyed by `username` (not `user_id` — we haven't verified identity yet). TTL 60 seconds.
5. Return `AuthenticationOptions` JSON.

Response: `200 OK`, `PublicKeyCredentialRequestOptions` JSON.

**Step 2 — Complete authentication**

```
POST /api/v1/auth/webauthn/authenticate/complete
```

No auth header required.

Request body:
```json
{
  "username": "alice",
  "credential": { /* PublicKeyCredential JSON from navigator.credentials.get() */ }
}
```

Server actions:
1. Retrieve the challenge stored for `username`.
2. Look up the `User` and their `WebAuthnCredential` rows.
3. Find the matching `WebAuthnCredential` by `credential_id` (compare the `credential.id` from the request to stored `credential_id` values).
4. Call `py_webauthn.verify_authentication_response(...)`:
   - `credential`: parse request body credential
   - `expected_challenge`: stored challenge
   - `expected_rp_id`: `WEBAUTHN_RP_ID`
   - `expected_origin`: `WEBAUTHN_ORIGIN`
   - `credential_public_key`: base64url-decode the stored `public_key`
   - `credential_current_sign_count`: the stored `sign_count`
   - `require_user_verification`: `False`
5. On success:
   - Update `WebAuthnCredential.sign_count` to `verified_authentication.new_sign_count`.
   - Update `WebAuthnCredential.last_used_at` to `datetime.utcnow()`.
   - Update `User.last_login_at`.
   - Issue access token and refresh token identical to the password login flow.
   - Clear the stored challenge.
   - Write audit event: `operation="webauthn_login", action="READ", status="SUCCESS"`.
6. Set the `refresh_token` httpOnly cookie (same as password login `_set_refresh_cookie`).

Response: `200 OK`
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "force_password_change": false
}
```

On failure: `401 Unauthorized`, `{ "detail": "Authentication failed" }`. Do not include the specific failure reason from py_webauthn in the API response (it may reveal implementation details).

### 3.4 Challenge Storage

Challenges must not be stored in the SQLite DB (too heavy for 60-second ephemeral state). Use an in-process dictionary keyed by `(username_or_userid, nonce)` with expiry timestamps. At the start of each `begin` call, sweep and discard challenges older than 60 seconds. This is sufficient for single-process deployments; if ever scaled horizontally, replace with Redis or a DB table.

Implementation: a `_challenge_store: dict[str, tuple[bytes, datetime]]` module-level dict in `api/routers/auth.py`, with a helper `_store_challenge(key, challenge)` and `_pop_challenge(key) -> bytes | None` that enforces the 60-second TTL.

### 3.5 Credential Management Endpoints

```
GET  /api/v1/auth/webauthn/credentials
DELETE /api/v1/auth/webauthn/credentials/{credential_id}
PATCH /api/v1/auth/webauthn/credentials/{credential_id}
```

All require `Authorization: Bearer <access_token>`. Users can only manage their own credentials (check `user_id` from JWT). Admins can manage any user's credentials via the admin router (see section 8).

`GET` response:
```json
[
  {
    "credential_id": "<base64url>",
    "label": "YubiKey 5 NFC",
    "aaguid": "f8a011f3-8c0a-4d15-8006-17111f9edc7d",
    "created_at": "2026-04-22T10:00:00",
    "last_used_at": "2026-04-22T12:00:00"
  }
]
```

Never return `public_key` or `sign_count` in API responses.

`DELETE` removes the credential row. If it is the last credential for a user who also has a `password_hash`, deletion is allowed. If the user has no `password_hash` and this is the last credential, return `400 { "detail": "Cannot remove last credential for a passwordless account" }`.

`PATCH` body: `{ "label": "New label" }` — update only the label.

### 3.6 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEBAUTHN_RP_ID` | `"localhost"` | Relying Party ID (must match the host the user browses to) |
| `WEBAUTHN_ORIGIN` | `"http://localhost:8000"` | Expected origin for response verification |

Both must be set correctly for production deployments. Document in the README and docker-compose template. These are non-sensitive and can be in the compose `environment` block.

### 3.7 Frontend — Security Key Registration (Settings Page)

Add a "Security Keys" card to the user settings section (accessible via the existing "Settings" nav item or a new profile dropdown — see nav redesign section).

Components involved:
- `pages/SecurityKeysPage.tsx` — list registered keys, label, last used, delete button, "Add Security Key" button.
- Uses `startRegistration` from `@simplewebauthn/browser` npm package (wraps `navigator.credentials.create()`).

Registration flow:
1. User clicks "Add Security Key".
2. Prompt for an optional label ("Name this key (optional):").
3. `POST /api/v1/auth/webauthn/register/begin` → receive options.
4. Call `startRegistration(options)` — browser prompts the user to touch the key.
5. `POST /api/v1/auth/webauthn/register/complete` → receive `{ ok: true }`.
6. Invalidate the credentials list query and show a success toast.
7. On error (user cancelled, key not recognized, etc.): show inline error without dismissing the list.

### 3.8 Frontend — Security Key Login (Login Page)

Modify `pages/LoginPage.tsx` to show a "Sign in with Security Key" button alongside the username/password form.

Authentication flow:
1. User enters username (required to look up their keys) and clicks "Sign in with Security Key".
2. `POST /api/v1/auth/webauthn/authenticate/begin` with `{ username }`.
3. If the response is `400` (no keys registered), show "No security keys registered for this account."
4. Call `startAuthentication(options)` from `@simplewebauthn/browser`.
5. `POST /api/v1/auth/webauthn/authenticate/complete` with `{ username, credential }`.
6. On success: same post-login flow as password login (store access token, handle `force_password_change`).

npm dependency: `@simplewebauthn/browser` (client-side WebAuthn helper, wraps the browser API).

---

## 4. Feature 2: Left Nav Redesign — Expandable Tenant Switcher

### 4.1 New Layout Structure

Replace `web/src/components/Layout.tsx` with a nav that has:

```
[logo] zs-config
─────────────────────
▼ Tenants              ← collapsible section header; click to expand/collapse
   ● acme-corp         ← active tenant (filled dot)
     staging-env       ← inactive tenant
     prod-us
─────────────────────
  Audit Log
─────────────────────
▼ Admin (admin only)   ← collapsible section header
     Users
     Tenant Access
     Settings
─────────────────────
[avatar] alice         ← username
  Profile / Keys
  Sign out
```

The "Tenants" label is itself a clickable section toggle, not a nav link. Individual tenant names are nav links.

### 4.2 Active Tenant State

Active tenant is stored in:
- React context (`ActiveTenantContext`) — in-memory during the session.
- `localStorage` key `"zs-config:active-tenant-id"` — persists across page reloads.

When the user clicks a tenant in the nav:
1. Set the active tenant in context and localStorage.
2. Navigate to `/tenant/:id/zia` (the default product tab).

When the app loads, if `localStorage` has a tenant ID and that tenant still exists in the fetched list, restore it as active automatically.

### 4.3 `ActiveTenantContext`

New file `web/src/context/ActiveTenantContext.tsx`:

```typescript
interface ActiveTenantContextValue {
  activeTenantId: number | null;
  setActiveTenantId: (id: number | null) => void;
}
```

Wrap the entire app in `<ActiveTenantProvider>` in `main.tsx` or `App.tsx`.

### 4.4 Tenant List in Nav

The sidebar fetches `GET /api/v1/tenants` (already exists). Results are sorted alphabetically by name. The list is short (tens, not thousands) so no pagination is needed in the nav.

Each tenant entry in the nav shows:
- A filled dot if it is the active tenant.
- The tenant `name`.
- A `(GovCloud)` suffix in a muted color if `govcloud: true`.
- A red `(!)` suffix if `last_validation_error` is non-null.

Clicking a tenant name sets it as active and navigates to `/tenant/:id/zia`.

### 4.5 User Info Footer

Replace the bare "Sign out" button with a footer section showing:
- User avatar initials (first letter of username in a colored circle).
- Username.
- A "Profile" link to `/profile` (see security keys page).
- "Sign out" button.

Admin users additionally see their role badge ("Admin").

---

## 5. Feature 3: Product Tabs per Active Tenant

### 5.1 Tab Visibility Rules

When a tenant is selected, the main panel shows tabs. Show/hide rules:

| Product | Tab shown when |
|---------|----------------|
| ZIA | Always |
| ZPA | `tenant.zpa_customer_id` is non-null |
| ZDX | Always (uses same credentials as ZIA) |
| ZCC | Always |
| ZID | Always |

### 5.2 TUI Menu Group Mapping

Each tab contains sections (accordions) matching the TUI menu groups. This is the authoritative section list:

**ZIA tab sections:**

| Section | TUI group | Current status |
|---------|-----------|---------------|
| Activation | Other | Exists (read/write) |
| URL Filtering | Web & URL Policy | Exists (read-only) — upgrade to CRUD |
| URL Categories | Web & URL Policy | Exists (read-only) — upgrade to CRUD |
| URL Lookup | Web & URL Policy | Exists (action) |
| Security Policy (Allow/Deny Lists) | Network Security | Exists (read-only) — upgrade to write |
| Firewall Policy | Network Security | New |
| SSL Inspection | Network Security | New |
| Users | Identity & Access | Exists (read-only) — upgrade to CRUD |
| Locations | Identity & Access | Exists (read-only) |
| Departments | Identity & Access | Exists (read-only) |
| Groups | Identity & Access | Exists (read-only) |
| DLP Engines | DLP | New |
| DLP Dictionaries | DLP | New |
| DLP Web Rules | DLP | New |
| Snapshots | Other | New |

**ZPA tab sections:**

| Section | TUI group | Current status |
|---------|-----------|---------------|
| App Connectors | Infrastructure | New |
| Service Edges | Infrastructure | New |
| Application Segments | Applications | Exists (read-only) — upgrade to CRUD |
| App Segment Groups | Applications | New |
| SAML Attributes | Identity & Directory | New |
| Access Policy | Policy | New |
| PRA Portals | PRA | Exists (read-only) |
| Certificates | Certificates | Exists (read-only) |
| Snapshots | Other | New |

**ZDX tab sections (all read-only):**

| Section | TUI group |
|---------|-----------|
| Device Lookup | Device Analytics |
| User Lookup | Users |
| Application Scores | Applications |

**ZCC tab sections:**

| Section | TUI group | Current status |
|---------|-----------|---------------|
| Devices | Devices | New — list + soft/force remove |
| OTP Lookup | Devices | New |
| Trusted Networks | Configuration | New |
| Forwarding Profiles | Configuration | New |
| App Profiles (Web Policies) | Configuration | New |
| Bypass App Definitions | Configuration | New |
| Export CSV | Export | New |

**ZID tab sections:**

| Section | TUI group | Current status |
|---------|-----------|---------------|
| Users | Users | New — full CRUD + password ops |
| Groups | Groups | New — list + member management |
| API Clients | API Clients | New — list + secret management |

### 5.3 Section Component Pattern

Each section is an accordion that defers data loading until opened (`enabled: isOpen` in `useQuery`). This pattern is already established in `TenantPage.tsx` and must be carried forward. Sections that have write operations additionally receive the `isAdmin` flag from `useAuth()` and conditionally render action buttons.

---

## 6. Feature 4: Full CRUD / Actions

This section specifies the UI pattern for each resource type, keyed to the service methods that already exist in `services/`.

### 6.1 UI Patterns

| Pattern | When to use | Component |
|---------|-------------|-----------|
| List/Search table | All list views | `DataTable` (sortable, client-side filter) |
| Create modal | Create new resource | `CreateModal` |
| Edit modal | Edit existing resource | `EditModal` (pre-populated) |
| Delete confirmation | Single delete | `ConfirmDialog` |
| Toggle switch | Enable/disable in table row | `Switch` (immediate mutation) |
| Bulk action | Multi-select + bulk operation | Checkbox column + `BulkActionBar` |
| File download | CSV export | Download button (triggers GET, `Content-Disposition: attachment`) |
| File upload | Import | `ImportModal` with `<input type="file">` |

### 6.2 ZIA — URL Categories (priority: high)

**Existing API**: `GET /{tenant}/url-categories`, `POST /{tenant}/url-lookup`

**New endpoints needed**:

```
GET  /api/v1/zia/{tenant}/url-categories/{category_id}
POST /api/v1/zia/{tenant}/url-categories
PUT  /api/v1/zia/{tenant}/url-categories/{category_id}
```

Service methods: `ZIAService.get_url_category()`, `ZIAService.create_url_category()`, `ZIAService.update_url_category()` — all exist.

No delete endpoint: ZIA does not support deleting custom URL categories via the OneAPI (deletion is through the admin portal only). The UI should not show a delete button.

**Request body for POST/PUT**:
```json
{
  "name": "My Custom Category",
  "type": "URL_CATEGORY",
  "urls": ["example.com", "test.org"],
  "dbCategorizedUrls": [],
  "customCategory": true,
  "superCategory": "USER_DEFINED",
  "description": ""
}
```

**UI**: Table with ID, Name, Type columns + filter. Custom categories (those with `customCategory: true` or numeric ID) get Edit button. Predefined categories are read-only (no edit button). "Add Category" button (admin only) opens create modal. After create/update: call `POST /{tenant}/activation/activate` automatically (`auto_activate=True` is the default in the service).

**ZIA activation banner**: after any mutating ZIA operation, the UI must show a persistent banner "ZIA changes pending — activation required" until the user clicks "Activate Now" or the page detects `status: "ACTIVE"` from the activation polling. Poll `GET /{tenant}/activation/status` every 30 seconds when the banner is visible.

### 6.3 ZIA — URL Filtering Rules (priority: high)

**Existing API**: `GET /{tenant}/url-filtering-rules`

**New endpoints needed**:

```
POST   /api/v1/zia/{tenant}/url-filtering-rules
PUT    /api/v1/zia/{tenant}/url-filtering-rules/{rule_id}
DELETE /api/v1/zia/{tenant}/url-filtering-rules/{rule_id}
PATCH  /api/v1/zia/{tenant}/url-filtering-rules/{rule_id}/state
```

Service methods: `ZIAService.create_url_filtering_rule()` exists. Need to add `update_url_filtering_rule()` and `delete_url_filtering_rule()` to `ZIAService` (call `self.client.update_url_filtering_rule(rule_id, config)` and `self.client.delete_url_filtering_rule(rule_id)` — both exist in `ZIAClient`).

`PATCH /{rule_id}/state` body: `{ "state": "ENABLED" | "DISABLED" }` — used for the row toggle switch.

**UI**: Table with Order, Name, Action, State columns. Toggle switch in State column (admin only). Edit and Delete buttons per row (admin only). "Add Rule" button. Delete confirmation modal shows rule name. After mutations: show ZIA activation banner.

### 6.4 ZIA — Users (priority: high)

**Existing API**: `GET /{tenant}/users?name=<filter>`

**New endpoints needed**:

```
GET    /api/v1/zia/{tenant}/users/{user_id}
POST   /api/v1/zia/{tenant}/users
PUT    /api/v1/zia/{tenant}/users/{user_id}
DELETE /api/v1/zia/{tenant}/users/{user_id}
```

Service methods: need to add `get_user()`, `create_user()`, `update_user()`, `delete_user()` to `ZIAService`. Each calls the corresponding `ZIAClient` method.

**Request body for POST/PUT**:
```json
{
  "name": "Alice Smith",
  "email": "alice@example.com",
  "password": "...",
  "department": { "id": 123 },
  "comments": ""
}
```

`password` is only required on POST. On PUT, omitting it leaves the password unchanged.

**UI**: Table with Name, Email, Department columns + text filter. Edit modal (admin only). Delete confirmation (admin only). "Add User" button (admin only). Bulk delete with checkboxes + "Delete Selected" (admin only). After mutations: show ZIA activation banner.

### 6.5 ZIA — Allow/Deny Lists (priority: medium)

**Existing API**: `GET /{tenant}/allowlist`, `GET /{tenant}/denylist`

**New endpoints needed**:

```
PUT /api/v1/zia/{tenant}/allowlist
PUT /api/v1/zia/{tenant}/denylist
```

Request body: `{ "whitelistUrls": ["url1", "url2"] }` / `{ "blacklistUrls": ["url1"] }`

Service methods: add `update_allowlist(urls: list)` and `update_denylist(urls: list)` to `ZIAService`.

**UI**: Two side-by-side lists (existing). Add an "Edit" button per list that opens a textarea modal with one URL per line. On save, PUT the full list. After save: show ZIA activation banner.

### 6.6 ZPA — Application Segments (priority: high)

**Existing API**: `GET /{tenant}/applications?app_type=BROWSER_ACCESS`

**New endpoints needed**:

```
GET    /api/v1/zpa/{tenant}/applications/{app_id}
POST   /api/v1/zpa/{tenant}/applications
PUT    /api/v1/zpa/{tenant}/applications/{app_id}
DELETE /api/v1/zpa/{tenant}/applications/{app_id}
PATCH  /api/v1/zpa/{tenant}/applications/{app_id}/enabled
```

Service methods: add `get_application()`, `create_application()`, `update_application()`, `delete_application()`, `set_application_enabled()` to `ZPAService`. The underlying `ZPAClient` methods already exist (`get_application`, `update_application`, `delete_application` — check `lib/zpa_client.py`; `create_application` may need to be added).

`PATCH /{app_id}/enabled` body: `{ "enabled": true }` — for the row toggle.

**Request body for POST/PUT**:
```json
{
  "name": "My App",
  "domainNames": ["app.example.com"],
  "tcpPortRanges": [{ "from": "443", "to": "443" }],
  "segmentGroupId": "<uuid>",
  "serverGroups": [{ "id": "<uuid>" }],
  "enabled": true,
  "description": ""
}
```

**UI**: Table with Name, Type, Domains (truncated), Enabled toggle columns. Edit and Delete buttons per row (admin only). Toggle switch in Enabled column. "Add Application Segment" button (admin only). No activation step — ZPA changes take effect immediately.

**Note on `app_type`**: the existing list endpoint accepts `app_type` as a query param. Keep this. The create form should have an App Type dropdown (`BROWSER_ACCESS`, `SECURE_REMOTE_ACCESS`). Do not mix types in a single list; add a filter dropdown.

### 6.7 ZCC — Devices (priority: medium)

**New endpoints needed**:

```
GET    /api/v1/zcc/{tenant}/devices
DELETE /api/v1/zcc/{tenant}/devices/remove
DELETE /api/v1/zcc/{tenant}/devices/force-remove
GET    /api/v1/zcc/{tenant}/devices/otp/{udid}
```

`GET /api/v1/zcc/{tenant}/devices` accepts query params:
- `username: str` (optional filter)
- `os_type: int` (optional, 1=Windows, 2=macOS, 3=iOS, 4=Android, 5=Linux, 6=ChromeOS)
- `page_size: int` (default 500, max 1000)

`DELETE /api/v1/zcc/{tenant}/devices/remove` and `force-remove` request body:
```json
{
  "udids": ["<udid1>", "<udid2>"],
  "os_type": 1
}
```

Service methods: `ZCCService.list_devices()`, `ZCCService.remove_device()`, `ZCCService.force_remove_device()`, `ZCCService.get_otp()` — all exist.

`_get_zcc_service()` helper in `api/routers/zcc.py` (new router file): same pattern as ZIA/ZPA — load tenant, build `ZCCClient`, return `ZCCService(client, tenant_id=tenant.id)`.

**UI**: Table with Hostname, User, OS, Registration State, UDID columns. Text filter for hostname/user. OS Type filter dropdown. Multi-select checkboxes. "Remove Selected" and "Force Remove Selected" bulk action buttons (admin only, with confirmation modal showing device count). "Get OTP" action per row opens a modal showing the OTP code with a copy button. No create or edit (ZCC devices are managed by the client agent, not by the portal).

### 6.8 ZID — Users (priority: medium)

**New endpoints needed**:

```
GET    /api/v1/zid/{tenant}/users
GET    /api/v1/zid/{tenant}/users/{user_id}
POST   /api/v1/zid/{tenant}/users
PUT    /api/v1/zid/{tenant}/users/{user_id}
DELETE /api/v1/zid/{tenant}/users/{user_id}
POST   /api/v1/zid/{tenant}/users/{user_id}/reset-password
PUT    /api/v1/zid/{tenant}/users/{user_id}/password
POST   /api/v1/zid/{tenant}/users/{user_id}/skip-mfa
```

`GET` accepts query params: `login_name`, `display_name`, `primary_email`, `domain_name`.

`POST /api/v1/zid/{tenant}/users/{user_id}/reset-password` — no body. Returns the temporary password from the response.

`PUT /api/v1/zid/{tenant}/users/{user_id}/password` body: `{ "password": "...", "reset_on_login": false }`

`POST /api/v1/zid/{tenant}/users/{user_id}/skip-mfa` body: `{ "until_timestamp": 1234567890 }`

Service methods: `ZIdentityService.list_users()`, `get_user()`, `create_user()`, `update_user()`, `delete_user()`, `reset_password()`, `update_password()`, `skip_mfa()` — all exist.

**UI**: Table with Login Name, Display Name, Email columns + search inputs per column. "Reset Password" action per row (admin only) — shows result in modal (temporary password from API, with copy button). "Set Password" action per row (admin only) — modal with password input + "Force change on login" checkbox. "Skip MFA" action per row — date picker for "until" datetime. "Add User" button. Delete confirmation.

### 6.9 ZID — Groups (priority: medium)

**New endpoints needed**:

```
GET  /api/v1/zid/{tenant}/groups
GET  /api/v1/zid/{tenant}/groups/{group_id}
GET  /api/v1/zid/{tenant}/groups/{group_id}/members
POST /api/v1/zid/{tenant}/groups/{group_id}/members
DELETE /api/v1/zid/{tenant}/groups/{group_id}/members/{user_id}
```

`POST .../members` body: `{ "user_id": "<zid-user-id>", "username": "<login_name>" }`

Service methods: `ZIdentityService.list_groups()`, `get_group()`, `list_group_members()`, `add_user_to_group()`, `remove_user_from_group()` — all exist.

**UI**: Group list table with Name, Type (dynamic/static) columns. Clicking a group name expands a member list sub-table. "Add Member" button opens a user search modal (calls ZID users list). "Remove" button per member row.

### 6.10 ZID — API Clients (priority: medium)

**New endpoints needed**:

```
GET    /api/v1/zid/{tenant}/api-clients
GET    /api/v1/zid/{tenant}/api-clients/{client_id}
GET    /api/v1/zid/{tenant}/api-clients/{client_id}/secrets
POST   /api/v1/zid/{tenant}/api-clients/{client_id}/secrets
DELETE /api/v1/zid/{tenant}/api-clients/{client_id}/secrets/{secret_id}
DELETE /api/v1/zid/{tenant}/api-clients/{client_id}
```

`POST .../secrets` body: `{ "expires_at": "2027-01-01T00:00:00Z" }` (optional)

Service methods: `ZIdentityService.list_api_clients()`, `get_api_client()`, `get_api_client_secrets()`, `add_api_client_secret()`, `delete_api_client_secret()`, `delete_api_client()` — all exist.

**IMPORTANT — secret display**: the `add_api_client_secret` response from ZIdentity includes a `clientSecret` value in the response. This is the only time the secret is visible. Display it in a modal with a copy button and a warning "This secret will not be shown again." The value must NOT be stored anywhere (not logged, not in DB, not in the audit entry — the audit entry records the operation and `secret_id`, not the value). This aligns with the global `client_secret` constraint.

**UI**: API Clients table with Name, Created, Last Modified. Clicking a client expands a secrets sub-table showing Secret ID, Created, Expires. "Add Secret" button (admin only). "Delete Secret" confirmation modal shows secret ID only. "Delete Client" confirmation modal.

### 6.11 ZDX — Read-Only Views

**New endpoints needed**:

```
GET  /api/v1/zdx/{tenant}/devices
GET  /api/v1/zdx/{tenant}/devices/{device_id}
GET  /api/v1/zdx/{tenant}/users
```

`GET /api/v1/zdx/{tenant}/devices` accepts: `query` (search string), `hours` (int, default 2).

Service methods: `ZDXService.search_devices()`, `get_device_summary()`, `lookup_user()` — all exist.

`_get_zdx_service()` helper in `api/routers/zdx.py` (new router file). ZDX uses the same `ZscalerAuth` / `client_id` / `client_secret` as ZIA. Build `ZDXClient(auth, tenant.oneapi_base_url)`.

**UI**: Device search form (query input + hours selector). Results table. Clicking a device shows health summary. User lookup: text search, results list. All read-only — no action buttons.

---

## 7. Feature 5: Route Structure

### 7.1 Route Definitions

Replace the current routes in `App.tsx` with:

```
/login                          → LoginPage (no auth required)
/change-password                → ChangePasswordPage (no auth required)
/profile                        → ProfilePage (auth required) — security keys, change password
/                               → Redirect: if active tenant in localStorage → /tenant/:id/zia, else /tenants
/tenants                        → TenantsPage (admin: CRUD list; non-admin: redirected to first entitled tenant)
/tenant/:id                     → Redirect to /tenant/:id/zia
/tenant/:id/zia                 → TenantWorkspacePage with ZIA tab active
/tenant/:id/zpa                 → TenantWorkspacePage with ZPA tab active
/tenant/:id/zdx                 → TenantWorkspacePage with ZDX tab active
/tenant/:id/zcc                 → TenantWorkspacePage with ZCC tab active
/tenant/:id/zid                 → TenantWorkspacePage with ZID tab active
/audit                          → AuditPage
/admin/users                    → AdminUsersPage (admin only)
/admin/entitlements             → AdminEntitlementsPage (admin only)
/admin/settings                 → AdminSettingsPage (admin only)
```

### 7.2 `TenantWorkspacePage`

New page component that:
1. Reads `:id` from URL params.
2. Fetches tenant detail via `GET /api/v1/tenants/:id`.
3. Sets active tenant in `ActiveTenantContext`.
4. Renders the tab bar (ZIA always, others conditional).
5. Renders the active tab's section list.

The active tab is determined by the URL segment (`/zia`, `/zpa`, etc.), not by component state. Clicking a tab navigates to the new URL using `<Link>` — this ensures the browser back button works correctly and the tab is bookmarkable.

### 7.3 Redirect Logic for "/"

In `App.tsx`:

```typescript
function RootRedirect() {
  const { tenants } = useTenants(); // fetches /api/v1/tenants
  const storedId = localStorage.getItem("zs-config:active-tenant-id");
  
  if (storedId && tenants?.some(t => String(t.id) === storedId)) {
    return <Navigate to={`/tenant/${storedId}/zia`} replace />;
  }
  if (tenants && tenants.length > 0) {
    return <Navigate to={`/tenant/${tenants[0].id}/zia`} replace />;
  }
  return <Navigate to="/tenants" replace />;
}
```

While `tenants` is loading, show a centered loading spinner.

### 7.4 Non-Admin User Routing

Non-admin users cannot access `/tenants` (the admin CRUD list). Instead:
- `GET /api/v1/tenants` returns only their entitled tenants.
- The root redirect navigates directly to the first entitled tenant.
- If a non-admin user navigates to `/tenants` directly, redirect to `/tenant/:first-id/zia`.

---

## 8. New API Endpoints — Complete List

All endpoints use prefix `/api/v1`. All require `Authorization: Bearer <access_token>` unless stated otherwise. Endpoints that mutate require `require_admin` unless stated otherwise.

### 8.1 Auth / WebAuthn (add to `api/routers/auth.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `POST` | `/api/v1/auth/webauthn/register/begin` | Bearer (any user) | `{ "label": str }` | `PublicKeyCredentialCreationOptions` JSON |
| `POST` | `/api/v1/auth/webauthn/register/complete` | Bearer (any user) | `{ "label": str, "credential": object }` | `{ "ok": true, "credential_id": str }` |
| `POST` | `/api/v1/auth/webauthn/authenticate/begin` | None | `{ "username": str }` | `PublicKeyCredentialRequestOptions` JSON |
| `POST` | `/api/v1/auth/webauthn/authenticate/complete` | None | `{ "username": str, "credential": object }` | `{ "access_token": str, "token_type": "bearer", "force_password_change": bool }` |
| `GET`  | `/api/v1/auth/webauthn/credentials` | Bearer (any user) | — | `[{ "credential_id", "label", "aaguid", "created_at", "last_used_at" }]` |
| `DELETE` | `/api/v1/auth/webauthn/credentials/{credential_id}` | Bearer (any user) | — | `204 No Content` |
| `PATCH` | `/api/v1/auth/webauthn/credentials/{credential_id}` | Bearer (any user) | `{ "label": str }` | `{ "credential_id", "label" }` |

### 8.2 ZIA (extend `api/routers/zia.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET` | `/api/v1/zia/{tenant}/url-categories/{category_id}` | any | — | Category object |
| `POST` | `/api/v1/zia/{tenant}/url-categories` | admin | Category config | Created category |
| `PUT` | `/api/v1/zia/{tenant}/url-categories/{category_id}` | admin | Category config | Updated category |
| `POST` | `/api/v1/zia/{tenant}/url-filtering-rules` | admin | Rule config | Created rule |
| `PUT` | `/api/v1/zia/{tenant}/url-filtering-rules/{rule_id}` | admin | Rule config | Updated rule |
| `DELETE` | `/api/v1/zia/{tenant}/url-filtering-rules/{rule_id}` | admin | — | `{ "deleted": true }` |
| `PATCH` | `/api/v1/zia/{tenant}/url-filtering-rules/{rule_id}/state` | admin | `{ "state": str }` | Updated rule |
| `GET` | `/api/v1/zia/{tenant}/users/{user_id}` | any | — | User object |
| `POST` | `/api/v1/zia/{tenant}/users` | admin | User config | Created user |
| `PUT` | `/api/v1/zia/{tenant}/users/{user_id}` | admin | User config | Updated user |
| `DELETE` | `/api/v1/zia/{tenant}/users/{user_id}` | admin | — | `{ "deleted": true }` |
| `PUT` | `/api/v1/zia/{tenant}/allowlist` | admin | `{ "whitelistUrls": [str] }` | Updated allowlist |
| `PUT` | `/api/v1/zia/{tenant}/denylist` | admin | `{ "blacklistUrls": [str] }` | Updated denylist |

All ZIA mutation endpoints: after successful service call, the service's `auto_activate=True` parameter handles activation. The endpoint does NOT need to call activate itself. The frontend shows the activation banner after any mutation by re-polling `GET /{tenant}/activation/status`.

### 8.3 ZPA (extend `api/routers/zpa.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET` | `/api/v1/zpa/{tenant}/applications/{app_id}` | any | — | Application object |
| `POST` | `/api/v1/zpa/{tenant}/applications` | admin | App segment config | Created application |
| `PUT` | `/api/v1/zpa/{tenant}/applications/{app_id}` | admin | App segment config | Updated application |
| `DELETE` | `/api/v1/zpa/{tenant}/applications/{app_id}` | admin | — | `{ "deleted": true }` |
| `PATCH` | `/api/v1/zpa/{tenant}/applications/{app_id}/enabled` | admin | `{ "enabled": bool }` | Updated application |
| `GET` | `/api/v1/zpa/{tenant}/segment-groups` | any | — | `[SegmentGroup]` |
| `GET` | `/api/v1/zpa/{tenant}/server-groups` | any | — | `[ServerGroup]` |
| `GET` | `/api/v1/zpa/{tenant}/app-connectors` | any | — | `[AppConnector]` |
| `GET` | `/api/v1/zpa/{tenant}/service-edges` | any | — | `[ServiceEdge]` |

`segment-groups` and `server-groups` are needed as reference data for the application segment create/edit form dropdowns.

### 8.4 ZCC (new router `api/routers/zcc.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET` | `/api/v1/zcc/{tenant}/devices` | any | — | `[Device]` (query params: `username`, `os_type`, `page_size`) |
| `DELETE` | `/api/v1/zcc/{tenant}/devices/remove` | admin | `{ "udids": [str], "os_type": int }` | API response from ZCC |
| `DELETE` | `/api/v1/zcc/{tenant}/devices/force-remove` | admin | `{ "udids": [str], "os_type": int }` | API response from ZCC |
| `GET` | `/api/v1/zcc/{tenant}/devices/otp/{udid}` | admin | — | `{ "otp": str }` |
| `GET` | `/api/v1/zcc/{tenant}/trusted-networks` | any | — | `[TrustedNetwork]` |
| `GET` | `/api/v1/zcc/{tenant}/forwarding-profiles` | any | — | `[ForwardingProfile]` |
| `GET` | `/api/v1/zcc/{tenant}/web-policies` | any | — | `[WebPolicy]` |
| `GET` | `/api/v1/zcc/{tenant}/web-app-services` | any | — | `[WebAppService]` |

ZCC is inherently multi-OS. The `os_type` parameter uses ZCC's integer OS type scheme. The frontend should present a human-readable OS dropdown.

### 8.5 ZDX (new router `api/routers/zdx.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET` | `/api/v1/zdx/{tenant}/devices` | any | — | `[Device]` (query params: `query`, `hours`) |
| `GET` | `/api/v1/zdx/{tenant}/devices/{device_id}` | any | — | `{ "health": object, "events": [object] }` |
| `GET` | `/api/v1/zdx/{tenant}/users` | any | — | `[User]` (query params: `query`) |

### 8.6 ZID (new router `api/routers/zid.py`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET` | `/api/v1/zid/{tenant}/users` | any | — | `[ZidUser]` (query params: `login_name`, `display_name`, `primary_email`, `domain_name`) |
| `GET` | `/api/v1/zid/{tenant}/users/{user_id}` | any | — | ZidUser object |
| `POST` | `/api/v1/zid/{tenant}/users` | admin | ZidUser config | Created user |
| `PUT` | `/api/v1/zid/{tenant}/users/{user_id}` | admin | ZidUser config | Updated user |
| `DELETE` | `/api/v1/zid/{tenant}/users/{user_id}` | admin | — | `204` |
| `POST` | `/api/v1/zid/{tenant}/users/{user_id}/reset-password` | admin | — | `{ "temporary_password": str }` |
| `PUT` | `/api/v1/zid/{tenant}/users/{user_id}/password` | admin | `{ "password": str, "reset_on_login": bool }` | `{ "ok": true }` |
| `POST` | `/api/v1/zid/{tenant}/users/{user_id}/skip-mfa` | admin | `{ "until_timestamp": int }` | `{ "ok": true }` |
| `GET` | `/api/v1/zid/{tenant}/groups` | any | — | `[ZidGroup]` (query params: `name`, `exclude_dynamic`) |
| `GET` | `/api/v1/zid/{tenant}/groups/{group_id}` | any | — | ZidGroup object |
| `GET` | `/api/v1/zid/{tenant}/groups/{group_id}/members` | any | — | `[ZidUser]` |
| `POST` | `/api/v1/zid/{tenant}/groups/{group_id}/members` | admin | `{ "user_id": str, "username": str }` | `{ "ok": true }` |
| `DELETE` | `/api/v1/zid/{tenant}/groups/{group_id}/members/{user_id}` | admin | — | `204` |
| `GET` | `/api/v1/zid/{tenant}/api-clients` | any | — | `[ApiClient]` (query params: `name`) |
| `GET` | `/api/v1/zid/{tenant}/api-clients/{client_id}` | any | — | ApiClient object |
| `GET` | `/api/v1/zid/{tenant}/api-clients/{client_id}/secrets` | admin | — | `[{ "secret_id", "created_at", "expires_at" }]` |
| `POST` | `/api/v1/zid/{tenant}/api-clients/{client_id}/secrets` | admin | `{ "expires_at": str \| null }` | `{ "secret_id": str, "client_secret": str }` — one-time only |
| `DELETE` | `/api/v1/zid/{tenant}/api-clients/{client_id}/secrets/{secret_id}` | admin | — | `204` |
| `DELETE` | `/api/v1/zid/{tenant}/api-clients/{client_id}` | admin | — | `204` |

**ZID `_get_service()` pattern**: load tenant by name, build `ZscalerAuth`, then build `ZIdentityClient(auth, tenant.zidentity_base_url)`, return `ZIdentityService(client, tenant_id=tenant.id)`. Note: ZID uses `zidentity_base_url` not `oneapi_base_url`.

### 8.7 Register New Routers in `api/main.py`

```python
from api.routers import zcc as zcc_router, zdx as zdx_router, zid as zid_router

app.include_router(zcc_router.router, prefix="/api/v1/zcc", tags=["ZCC"])
app.include_router(zdx_router.router, prefix="/api/v1/zdx", tags=["ZDX"])
app.include_router(zid_router.router, prefix="/api/v1/zid", tags=["ZID"])
```

Also add WebAuthn routes to `ForcePasswordChangeMiddleware._EXEMPT`:
```python
"/api/v1/auth/webauthn/authenticate/begin",
"/api/v1/auth/webauthn/authenticate/complete",
```

---

## 9. New Frontend Components and Pages

### 9.1 Context Files

| File | Purpose |
|------|---------|
| `web/src/context/ActiveTenantContext.tsx` | Stores active tenant ID; syncs with localStorage |

### 9.2 API Client Modules (new files)

| File | Covers |
|------|--------|
| `web/src/api/zcc.ts` | ZCC device, OTP, trusted-network, forwarding-profile, web-policy endpoints |
| `web/src/api/zdx.ts` | ZDX device, user endpoints |
| `web/src/api/zid.ts` | ZID user, group, api-client endpoints |
| `web/src/api/webauthn.ts` | WebAuthn register/authenticate/manage endpoints |

Extend existing:
- `web/src/api/zia.ts` — add URL category CRUD, URL filtering rule CRUD, user CRUD, allowlist/denylist PUT
- `web/src/api/zpa.ts` — add application CRUD, segment-groups, server-groups, app-connectors, service-edges

### 9.3 Shared Components (new)

| Component | File | Purpose |
|-----------|------|---------|
| `DataTable` | `components/DataTable.tsx` | Sortable table with column filter; wraps a `<table>` or TanStack Table; accepts columns config + data |
| `ConfirmDialog` | `components/ConfirmDialog.tsx` | Modal dialog with confirm/cancel; accepts `title`, `message`, `onConfirm`, `onCancel`, `destructive?: boolean` |
| `CreateModal` | `components/CreateModal.tsx` | Generic modal wrapper for create forms; handles title, close, submit |
| `EditModal` | `components/EditModal.tsx` | Same as CreateModal but labeled "Edit" |
| `BulkActionBar` | `components/BulkActionBar.tsx` | Sticky bar shown when rows are selected; shows selection count + action buttons |
| `ZiaActivationBanner` | `components/ZiaActivationBanner.tsx` | Yellow banner with "Activate Now" button; shown whenever ZIA has pending changes |
| `CopyButton` | `components/CopyButton.tsx` | Icon button that copies text to clipboard with visual feedback |
| `Toast` | `components/Toast.tsx` | Transient success/error notification (or use an existing library like `react-hot-toast`) |

### 9.4 Pages (new or replaced)

| Page | File | Replaces/New |
|------|------|-------------|
| `TenantWorkspacePage` | `pages/TenantWorkspacePage.tsx` | Replaces `TenantPage.tsx` — adds ZDX/ZCC/ZID tabs, URL-driven tab switching |
| `ProfilePage` | `pages/ProfilePage.tsx` | New — security keys list, change password link |
| `SecurityKeysPage` | `pages/SecurityKeysPage.tsx` | New — can be embedded in ProfilePage |

Modify:
- `pages/LoginPage.tsx` — add WebAuthn button
- `components/Layout.tsx` — expandable tenant list, user footer

Keep without changes:
- `pages/AuditPage.tsx`
- `pages/AdminUsersPage.tsx`
- `pages/AdminEntitlementsPage.tsx`
- `pages/AdminSettingsPage.tsx`
- `pages/ChangePasswordPage.tsx`

### 9.5 ZIA Section Components (upgrade from read-only to CRUD)

These live inside `TenantWorkspacePage` as exported sub-components, or in a `components/zia/` subdirectory:

| Component | Operations added |
|-----------|-----------------|
| `UrlCategoriesSection` | Edit modal for custom categories; "Add Category" modal |
| `UrlFilteringRulesSection` | Add, edit, delete, toggle-state |
| `UsersSection` | Add, edit, delete, bulk delete |
| `AllowDenySection` | Edit modal for each list (textarea, PUT on save) |
| `ZiaActivationBanner` | Polls activation status; "Activate Now" button |

### 9.6 ZPA Section Components (upgrade + new)

| Component | Operations |
|-----------|------------|
| `ApplicationSegmentsSection` | Full CRUD + enable/disable toggle |
| `SegmentGroupsSection` | Read-only list (reference data) |
| `AppConnectorsSection` | Read-only list |
| `ServiceEdgesSection` | Read-only list |

### 9.7 ZCC Section Components (new)

| Component | Operations |
|-----------|------------|
| `ZccDevicesSection` | List + OS filter + bulk remove + force-remove + OTP modal |
| `ZccTrustedNetworksSection` | Read-only list |
| `ZccForwardingProfilesSection` | Read-only list |
| `ZccWebPoliciesSection` | Read-only list |
| `ZccWebAppServicesSection` | Read-only list |

### 9.8 ZDX Section Components (new, all read-only)

| Component | Operations |
|-----------|------------|
| `ZdxDeviceSearchSection` | Search form + results table + device detail |
| `ZdxUserLookupSection` | Search input + results |

### 9.9 ZID Section Components (new)

| Component | Operations |
|-----------|------------|
| `ZidUsersSection` | List/search + CRUD + password ops + skip-MFA |
| `ZidGroupsSection` | List/search + member list + add/remove member |
| `ZidApiClientsSection` | List + secrets management + delete |

---

## 10. Cross-Cutting Constraints

### 10.1 SQLite Write-Lock

All new API endpoints follow the established pattern: collect audit events in a list, write them after the `with get_session()` block closes. No endpoint opens a session inside an existing session block.

The new ZCC, ZDX, and ZID routers do not write to the DB directly. They call service methods which internally use `audit_service.log()` — which itself opens its own session. Since `audit_service.log()` is called after the client API call returns (not inside a session block), there is no deadlock risk.

The WebAuthn credential table is written from within the `register/complete` endpoint. The write is a single `with get_session()` block with no nested opens. Audit events for WebAuthn are written in a separate `_write_audit()` call after the session closes, matching the pattern in `api/routers/tenants.py`.

### 10.2 client_secret Constraints

- ZCC, ZDX, ZID, and ZIA/ZPA routers all decrypt `client_secret_enc` inside their `_get_service()` helpers and pass the plaintext only to `ZscalerAuth`. The plaintext is never returned in any response.
- ZID `add_api_client_secret()` response: the one-time `clientSecret` value is passed through to the frontend response. This is intentional and unavoidable (it is the only time the ZID-managed secret is available). The API endpoint response body includes `client_secret` in this one case. It must NOT be written to the audit log — the audit entry records `secret_id` and `expires_at` only.
- WebAuthn `public_key` and `sign_count` fields are never included in any GET response. `credential_id` is safe to expose (it is not a secret).

### 10.3 ZIA Activation

All ZIA mutation endpoints rely on `auto_activate=True` in the service methods. The service automatically calls `self.activate()` after each mutation. The frontend must reflect this by re-polling `GET /{tenant}/activation/status` after any mutation. The `ZiaActivationBanner` component handles this by invalidating the `["zia-activation", tenant]` React Query cache key after any ZIA mutation.

### 10.4 questionary Constraint

Not applicable to the web frontend. The questionary constraint applies only to the TUI (`cli/`). The web frontend uses React and Tailwind and has no questionary dependency.

### 10.5 CORS and Credentials

`WEBAUTHN_RP_ID` must be set to the hostname the user browses to (without port). If users access zs-config at `http://myserver:8000`, `WEBAUTHN_RP_ID=myserver`. The `WEBAUTHN_ORIGIN` must be the full origin: `http://myserver:8000`. These must match exactly or py_webauthn's verification will fail.

### 10.6 Admin-Only vs. Any-User Endpoints

For ZCC, ZDX, and ZID read-only endpoints, `require_auth` (not `require_admin`) is used. Non-admin users see data for their entitled tenants. The `check_tenant_access()` call inside each `_get_service()` enforces entitlements.

Mutation endpoints (POST/PUT/DELETE/PATCH) all use `require_admin`. This is consistent with the existing ZIA and ZPA mutation endpoints and the pattern in the TUI (non-admin users cannot mutate).

---

## 11. Backlog Impact

### Unblocked by v2

- "Test suite" (backlog) — the new routers follow the established pattern and can be covered by the same `httpx`/`pytest` approach once a test harness is set up.
- "Alembic migrations" — the `WebAuthnCredential` table is the first table added post-MVP. This is a good forcing function to introduce Alembic migrations instead of the current `ALTER TABLE` pattern. However, Alembic adoption is not in scope for v2; it is in the backlog.

### Conflicts

- **`ZpaPage.tsx` and `ZiaPage.tsx`**: these two files exist (`web/src/pages/ZpaPage.tsx`, `ZiaPage.tsx`) but the current `App.tsx` routes redirect away from them. They appear to be dead code. The Coder should confirm whether they contain any unique logic not present in `TenantPage.tsx` before deleting them.
- **`TenantPage.tsx`**: will be superseded by `TenantWorkspacePage.tsx`. The existing sections within `TenantPage.tsx` should be migrated, not rewritten — move the section components wholesale and extend them.
- **`TenantsPage.tsx`**: remains but is now only the admin CRUD view. Non-admin users never see it.

### SDK Bug Flags

From `.claude/notes.md`:

- **ZPA SDK `ServiceEdgeControllerAPI._zpa` bug** — affects `GET /api/v1/zpa/{tenant}/service-edges`. The class-level patch in `lib/zpa_client.py` is required. Verify the patch is applied before implementing the service-edges API endpoint. If the patch is absent, every call to `list_service_edges()` will raise `AttributeError`.
- **ZIdentity SDK wrapper objects** — `list_users()`, `list_groups()`, `list_api_clients()` return model wrapper objects, not plain lists. The `_zid_list()` extractor must be used. Verify this is handled in each ZID service method before the API endpoint is added.
- **ZPA SDK snake_case deserialization** — ZPA API responses are in snake_case in the SDK. The `ZpaApplication` TypeScript type must use snake_case keys (`domain_names`, `application_type`, etc.) not camelCase. The existing `ZpaApplication` interface in `web/src/api/zpa.ts` uses camelCase (`domainNames`, `applicationType`) — this may already work if the current GET endpoint passes through the SDK response as-is. Verify before adding create/update endpoints, as the request body sent back to ZPA must be in the format the SDK/API expects.

### New npm Dependency

```
@simplewebauthn/browser
```

Add to `web/package.json`. This is the browser-side companion to `py_webauthn` and has no runtime dependency on any Zscaler SDK.

---

*End of spec.*
