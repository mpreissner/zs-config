# Changelog

All notable changes to this project will be documented in this file.

---

## [0.1.0] - 2026-02-25

### Added

#### ZPA — Connectors
- **List Connectors** — scrollable table showing Name, Group, Control Channel Status (green if authenticated), Private IP, Version, and Enabled state
- **Search Connectors** — partial name match, same table columns
- **Enable / Disable** — checkbox multi-select; patches `enabled` via API and updates local DB immediately
- **Rename Connector** — select connector, enter new name, confirms with old → new display; updates API and local DB
- **Delete Connector** — confirmation prompt (default: No); marks `is_deleted` in local DB on success

#### ZPA — Connector Groups
- **List Connector Groups** — scrollable table showing Name, Location, member Connector count (from local DB), and Enabled state
- **Search Connector Groups** — partial name match
- **Create Connector Group** — name + optional description; targeted re-import syncs new group into local DB automatically
- **Enable / Disable Group** — checkbox multi-select; patches `enabled` via API and updates local DB immediately
- **Delete Connector Group** — API rejection (e.g. group has members) is surfaced cleanly; local DB updated only on success

#### ZPA — PRA Portals
- **List PRA Portals** — scrollable table with domain, enabled state, and certificate name
- **Search by Domain** — partial domain match
- **Create Portal** — name, domain, certificate selection from local DB, enabled flag, optional user notification
- **Enable / Disable** — checkbox multi-select
- **Delete Portal** — confirmation prompt (default: No)

### Changed
- Connectors and PRA Portals promoted from stubs into the top section of the ZPA menu (alongside Application Segments and Certificate Management)
- ZPA menu order: Application Segments → Certificate Management → Connectors → PRA Portals → *(separator)* → Import Config → Reset N/A Resource Types

---

## [0.0.2] - 2026-02-24

### Fixed
- Windows compatibility — all `chmod` / `os.chmod` calls are now guarded with `sys.platform != "win32"` so the tool runs on Windows without raising `NotImplementedError`
- Platform-aware default credentials file path — Windows now defaults to `%APPDATA%\z-config\zscaler-oneapi.conf` instead of `/etc/zscaler-oneapi.conf`

### Changed
- Entry point renamed from `cli/zscaler-cli.py` to `cli/z_config.py` to match the repository name (`z-config`)
- Encryption key path moved from `~/.config/zscaler-cli/secret.key` to `~/.config/z-config/secret.key`; existing keys at the old location are migrated automatically on first launch

---

## [0.0.1] - 2026-02-24

Initial release.

### ZPA — Application Segments
- List Segments — table view of all imported segments with All / Enabled / Disabled filter
- Search by Domain — FQDN substring search across the local DB cache
- Enable / Disable — spacebar multi-select checkbox to toggle any number of segments in a single bulk operation; local DB updated immediately after each successful API call, no re-import required
- Bulk Create from CSV — parse & validate → dry-run with dependency resolution → optional auto-create of missing segment groups and server groups → progress bar → per-row error reporting → automatic re-import of newly created segments
- Export CSV Template — writes a two-row pre-filled template to any path
- CSV Field Reference — in-tool scrollable reference listing every column, accepted values, and defaults

### ZPA — Certificate Management
- List Certificates
- Rotate Certificate for Domain — upload new PEM cert+key, update all matching app segments and PRA portals, delete the old cert
- Delete Certificate

### ZPA — Config Import
- Pulls 18 resource types from the ZPA API into the local SQLite cache
- SHA-256 change detection for fast re-imports
- Automatic N/A detection — resource types that return 401 (not entitled) are skipped and recorded per tenant

### ZIA
- Policy activation
- URL category lookup

### CLI
- Full-screen scrollable viewer for all table views — Z-Config banner pinned at top, content scrolls with ↑↓ / j k / PageDown / PageUp / g / G, status bar with row range and scroll %, q to exit
- Auto-generated encryption key on first launch — saved to `~/.config/z-config/secret.key`, no manual setup required
- Tenant management — add, list, remove; client secrets encrypted at rest with Fernet
- Audit log viewer — all operations recorded with product, operation, resource, status, and local-timezone timestamp
- Settings — manage tenants, rotate encryption key, configure server credentials file, clear imported data

