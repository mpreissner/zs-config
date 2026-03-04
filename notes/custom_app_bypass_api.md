# Custom App Bypass Definitions — API Notes

Status: **Pending implementation** — waiting for OneAPI support, or implement via legacy API

---

## Background

Custom app bypass definitions (user-created) are NOT available via the ZCC OneAPI
(`api.zsapi.net`). They live exclusively on the legacy ZCC admin portal backend.

Zscaler-managed (pre-defined) definitions ARE available via OneAPI:
- `GET /zcc/papi/public/v1/webAppService/listByCompany`
- Returns 6 Zscaler-managed entries for this tenant
- `createdBy` is a numeric string (e.g. `"0"`, `"23971"`) for Zscaler-managed entries

---

## Legacy Admin Portal API

**Base URL:** `https://mobileadmin.{cloud}.net/webservice/api/web/`
(e.g. `https://mobileadmin.zscalertwo.net/webservice/api/web/`)

**Auth:** `Auth-Token: {jwt}` header
JWT obtained from: `POST https://api-mobile.{cloud}.net/papi/auth/v1/login`
Login body: `{"apiKey": "<client_id>", "secretKey": "<client_secret>"}`
Response field: `jwtToken`

### List custom app bypass definitions
```
GET  /webservice/api/web/customAppService/listByCompany
     ?page=1&pageSize=50&search=
```

### Create custom app bypass definition
```
POST /webservice/api/web/customAppService/create
```

**Required fields:**
- `name` — display name (string)
- `port` — single port, range (`8080-8090`), wildcard (`*`), or comma-separated list (`443,80`)
- `protocol` — `TCP`, `UDP`, or `*` (both)
- `ipv4` — comma-separated list of IPv4 addresses and/or CIDR notations
  e.g. `"192.168.1.0/24,10.0.0.1"`

**Payload shape** (to be confirmed with a full DevTools capture):
```json
{
  "name": "My App",
  "protocol": "TCP",
  "port": "443,80",
  "ipv4": "203.0.113.0/24,198.51.100.1"
}
```

**Note:** The OneAPI `webAppService` model stores `appDataBlob` as a list of objects:
```json
[{"proto": "TCP", "port": "443,80", "ipaddr": "...", "fqdn": ""}]
```
The legacy create API likely uses a flat `protocol`/`port`/`ipv4` form (not the blob format).
Confirm exact field names from the DevTools request body.

---

## Implementation plan (when ready)

1. **DB migration** — add `zcc_cloud` column to `TenantConfig` (nullable string, e.g. `"zscalertwo"`)
2. **Tenant setup UI** — add `zcc_cloud` field to tenant add/edit flow
3. **`ZCCClient`** — add:
   - `_legacy_login()` — POST to `api-mobile.{cloud}.net/papi/auth/v1/login`, cache JWT
   - `_legacy_get(path, params)` — GET with `Auth-Token` header against `mobileadmin.{cloud}.net`
   - `_legacy_post(path, json)` — POST with `Auth-Token` header
   - `list_custom_app_services()` — uses `_legacy_get`
   - `create_custom_app_service(name, protocol, port, ipv4)` — uses `_legacy_post`
4. **Import service** — add `ResourceDef("custom_app_service", "list_custom_app_services", name_field="name")`
5. **Menu** — merge Zscaler + custom definitions in "Bypass App Definitions" list (already shows Type column)
6. **Create workflow** — form: Name, Protocol (select), Port (text), IPv4 (text) → `create_custom_app_service()`

---

## Cloud name mapping (for reference)

| Cloud suffix | Cloud name      | URLs                                    |
|---|---|---|
| zscaler      | zscaler         | api-mobile.zscaler.net / mobileadmin.zscaler.net |
| zs1          | zscalerone      | api-mobile.zscalerone.net               |
| zs2          | zscalertwo      | api-mobile.zscalertwo.net               |
| zs3          | zscalerthree    | api-mobile.zscalerthree.net             |
| zsc          | zscloud         | api-mobile.zscloud.net                  |
| beta         | zscalerbeta     | api-mobile.zscalerbeta.net              |
