"""ZIA baseline push service.

Reads an exported snapshot JSON (produced by Config Snapshots → Export) and
pushes every resource to a live ZIA tenant via the API.

Strategy:
  - Resources are attempted in dependency order (PUSH_ORDER).
  - On 409 conflict: look up the resource by name, then attempt an update.
  - On 400/403/feature-not-licensed: record as failure, move on.
  - After each pass: if no progress was made, stop (stable state).
  - ID remapping: as objects are created/located in the target, a source→target
    mapping is built and applied to all subsequent payloads so cross-environment
    references resolve correctly.

Usage:
    service = ZIAPushService(client, tenant_id=tenant.id)
    records = service.push_baseline(baseline_dict)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Push order — resources are attempted tier by tier within each pass
# ---------------------------------------------------------------------------

PUSH_ORDER: List[str] = [
    # Tier 1 — no deps
    "rule_label",
    "time_interval",
    "workload_group",
    "bandwidth_class",
    # Tier 2 — objects
    "url_category",
    "ip_destination_group",
    "ip_source_group",
    "network_service",
    "network_svc_group",
    "network_app_group",
    "dlp_engine",
    "dlp_dictionary",
    # Tier 3 — locations
    "location",
    # Tier 4 — rules
    "url_filtering_rule",
    "firewall_rule",
    "firewall_dns_rule",
    "firewall_ips_rule",
    "ssl_inspection_rule",
    "nat_control_rule",
    "forwarding_rule",
    "dlp_web_rule",
    "bandwidth_control_rule",
    "traffic_capture_rule",
    "cloud_app_control_rule",
    # Tier 5 — merge-only list resources
    "allowlist",
    "denylist",
]

# Types that are env-specific or read-only in the SDK — skip entirely
SKIP_TYPES: set = {
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    "location_group",       # read-only in SDK
    "network_app",          # system-defined, read-only
    "cloud_app_policy",     # reference data, not policy
    "cloud_app_ssl_policy",
}

# Within pushable types: skip if raw_config.predefined is True
SKIP_IF_PREDEFINED: set = {
    "dlp_engine",
    "dlp_dictionary",
    "url_category",
    "network_service",
}

# Fields stripped from raw_config before push
READONLY_FIELDS: set = {
    "id",
    "predefined",
    "lastModifiedBy",
    "lastModifiedTime",
    "createdBy",
    "creationTime",
    "createdAt",
    "updatedAt",
    "modifiedTime",
    "modifiedBy",
    "lastModifiedByUser",
    "isDeleted",
    "dbCategoryIndex",
    "deleted",
}

# ---------------------------------------------------------------------------
# SDK method dispatch tables
# ---------------------------------------------------------------------------

# Maps resource_type → (create_method_name, update_method_name)
_WRITE_METHODS: Dict[str, tuple] = {
    "rule_label":             ("create_rule_label",             "update_rule_label"),
    "time_interval":          ("create_time_interval",          "update_time_interval"),
    "workload_group":         ("create_workload_group",         "update_workload_group"),
    "bandwidth_class":        ("create_bandwidth_class",        "update_bandwidth_class"),
    "url_category":           ("create_url_category",          "update_url_category"),
    "ip_destination_group":   ("create_ip_destination_group",  "update_ip_destination_group"),
    "ip_source_group":        ("create_ip_source_group",       "update_ip_source_group"),
    "network_service":        ("create_network_service",       "update_network_service"),
    "network_svc_group":      ("create_network_svc_group",     "update_network_svc_group"),
    "network_app_group":      ("create_network_app_group",     "update_network_app_group"),
    "dlp_engine":             ("create_dlp_engine",            "update_dlp_engine"),
    "dlp_dictionary":         ("create_dlp_dictionary",        "update_dlp_dictionary"),
    "location":               ("create_location",              "update_location"),
    "url_filtering_rule":     ("create_url_filtering_rule",    "update_url_filtering_rule"),
    "firewall_rule":          ("create_firewall_rule",         "update_firewall_rule"),
    "firewall_dns_rule":      ("create_firewall_dns_rule",     "update_firewall_dns_rule"),
    "firewall_ips_rule":      ("create_firewall_ips_rule",     "update_firewall_ips_rule"),
    "ssl_inspection_rule":    ("create_ssl_inspection_rule",   "update_ssl_inspection_rule"),
    "nat_control_rule":       ("create_nat_control_rule",      "update_nat_control_rule"),
    "forwarding_rule":        ("create_forwarding_rule",       "update_forwarding_rule"),
    "dlp_web_rule":           ("create_dlp_web_rule",         "update_dlp_web_rule"),
    "bandwidth_control_rule": ("create_bandwidth_control_rule","update_bandwidth_control_rule"),
    "traffic_capture_rule":   ("create_traffic_capture_rule",  "update_traffic_capture_rule"),
}

# Maps resource_type → list_method_name (used by _find_by_name)
_LIST_METHODS: Dict[str, str] = {
    "rule_label":             "list_rule_labels",
    "time_interval":          "list_time_intervals",
    "workload_group":         "list_workload_groups",
    "bandwidth_class":        "list_bandwidth_classes",
    "url_category":           "list_url_categories",
    "ip_destination_group":   "list_ip_destination_groups",
    "ip_source_group":        "list_ip_source_groups",
    "network_service":        "list_network_services",
    "network_svc_group":      "list_network_svc_groups",
    "network_app_group":      "list_network_app_groups",
    "dlp_engine":             "list_dlp_engines",
    "dlp_dictionary":         "list_dlp_dictionaries",
    "location":               "list_locations",
    "url_filtering_rule":     "list_url_filtering_rules",
    "firewall_rule":          "list_firewall_rules",
    "firewall_dns_rule":      "list_firewall_dns_rules",
    "firewall_ips_rule":      "list_firewall_ips_rules",
    "ssl_inspection_rule":    "list_ssl_inspection_rules",
    "nat_control_rule":       "list_nat_control_rules",
    "forwarding_rule":        "list_forwarding_rules",
    "dlp_web_rule":           "list_dlp_web_rules",
    "bandwidth_control_rule": "list_bandwidth_control_rules",
    "traffic_capture_rule":   "list_traffic_capture_rules",
    "cloud_app_control_rule": "list_all_cloud_app_rules",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PushRecord:
    resource_type: str
    name: str
    status: str   # "created" | "updated" | "skipped" | "failed:<reason>"

    @property
    def is_created(self) -> bool:
        return self.status == "created"

    @property
    def is_updated(self) -> bool:
        return self.status == "updated"

    @property
    def is_skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def is_failed(self) -> bool:
        return self.status.startswith("failed:")

    @property
    def failure_reason(self) -> str:
        if self.is_failed:
            return self.status[len("failed:"):]
        return ""


# ---------------------------------------------------------------------------
# Push service
# ---------------------------------------------------------------------------

class ZIAPushService:
    def __init__(self, client, tenant_id: int):
        self._client = client
        self._tenant_id = tenant_id
        self._id_remap: Dict[str, str] = {}   # source_id (str) → target_id (str)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push_baseline(
        self,
        baseline: dict,
        progress_callback=None,
    ) -> List[PushRecord]:
        """Main entry point. Runs ordered passes until stable.

        Args:
            baseline: Parsed snapshot export JSON dict (must have 'resources' key).
            progress_callback: Optional callable(pass_num, resource_type, record)
                called after each individual push attempt.

        Returns:
            All PushRecord objects (created + updated + skipped + failed).
        """
        resources = baseline.get("resources", {})

        # Build pending dict in push order; unknown types appended at end
        ordered_types = [t for t in PUSH_ORDER if t in resources]
        extra_types = [t for t in resources if t not in PUSH_ORDER]
        ordered_types.extend(extra_types)

        # pending: resource_type → list of entry dicts {name, raw_config, source_id}
        pending: Dict[str, List[dict]] = {}
        for rtype in ordered_types:
            if rtype in SKIP_TYPES:
                continue
            entries = resources[rtype]
            if not entries:
                continue
            pending[rtype] = list(entries)

        all_records: List[PushRecord] = []
        pass_num = 0

        while pending:
            pass_num += 1
            prev_pending_count = sum(len(v) for v in pending.values())

            new_pending, pass_records = self._single_pass(pending, pass_num, progress_callback)

            all_records.extend(pass_records)
            pending = new_pending

            current_count = sum(len(v) for v in pending.values())
            if current_count >= prev_pending_count:
                # No progress — stable failure set
                # Record remaining as failed (stable)
                for rtype, entries in pending.items():
                    for entry in entries:
                        all_records.append(PushRecord(
                            resource_type=rtype,
                            name=entry.get("name", "?"),
                            status="failed:stable — no progress after retry",
                        ))
                break

        return all_records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _single_pass(
        self,
        pending: Dict[str, List[dict]],
        pass_num: int,
        progress_callback=None,
    ) -> tuple[Dict[str, List[dict]], List[PushRecord]]:
        """One iteration over pending resources.

        Returns (new_pending, records_this_pass).
        """
        new_pending: Dict[str, List[dict]] = {}
        records: List[PushRecord] = []

        for rtype in list(pending.keys()):
            entries = pending[rtype]
            remaining = []

            # Allowlist/denylist handled specially
            if rtype in ("allowlist", "denylist"):
                list_records = self._push_list_resource(rtype, entries)
                records.extend(list_records)
                if progress_callback:
                    for r in list_records:
                        progress_callback(pass_num, rtype, r)
                continue

            for entry in entries:
                rec = self._push_one(rtype, entry)
                if progress_callback:
                    progress_callback(pass_num, rtype, rec)

                if rec.is_failed and "stable" not in rec.failure_reason:
                    # Transient failure — keep for retry
                    remaining.append(entry)
                else:
                    records.append(rec)

            if remaining:
                new_pending[rtype] = remaining

        return new_pending, records

    def _push_one(self, resource_type: str, entry: dict) -> PushRecord:
        """Push a single resource. entry has 'name', 'raw_config', 'id' keys."""
        name = entry.get("name", "?")
        source_id = str(entry.get("id", ""))
        raw_config = entry.get("raw_config", {})

        # Skip predefined resources within certain types
        if resource_type in SKIP_IF_PREDEFINED and raw_config.get("predefined"):
            if source_id:
                self._register_remap(source_id, source_id)  # map to itself; best-effort
            return PushRecord(resource_type=resource_type, name=name, status="skipped")

        # Cloud app control rules need special handling (rule_type embedded in config)
        if resource_type == "cloud_app_control_rule":
            return self._push_cloud_app_rule(name, source_id, raw_config)

        if resource_type not in _WRITE_METHODS:
            return PushRecord(
                resource_type=resource_type,
                name=name,
                status="skipped",
            )

        create_method_name, update_method_name = _WRITE_METHODS[resource_type]
        create_method = getattr(self._client, create_method_name)
        update_method = getattr(self._client, update_method_name)

        # Strip readonly fields and remap IDs
        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        try:
            result = create_method(config)
            target_id = str(result.get("id", ""))
            if source_id and target_id:
                self._register_remap(source_id, target_id)
            return PushRecord(resource_type=resource_type, name=name, status="created")
        except Exception as exc:
            exc_str = str(exc)

            # 409 conflict → look up by name and update
            if "409" in exc_str or "already exists" in exc_str.lower() or "conflict" in exc_str.lower():
                found_id = self._find_by_name(resource_type, name)
                if found_id:
                    if source_id:
                        self._register_remap(source_id, found_id)
                    try:
                        update_method(found_id, config)
                        return PushRecord(resource_type=resource_type, name=name, status="updated")
                    except Exception as upd_exc:
                        return PushRecord(
                            resource_type=resource_type,
                            name=name,
                            status=f"failed:{upd_exc}",
                        )
                else:
                    return PushRecord(
                        resource_type=resource_type,
                        name=name,
                        status=f"failed:409 — could not locate existing resource by name",
                    )

            # 400/403/not-licensed — permanent failure
            if any(code in exc_str for code in ("400", "403", "NOT_SUBSCRIBED", "not licensed")):
                return PushRecord(
                    resource_type=resource_type,
                    name=name,
                    status=f"failed:{exc_str[:120]}",
                )

            # Other error — transient, allow retry
            return PushRecord(
                resource_type=resource_type,
                name=name,
                status=f"failed:{exc_str[:120]}",
            )

    def _push_cloud_app_rule(self, name: str, source_id: str, raw_config: dict) -> PushRecord:
        """Push a cloud app control rule (requires rule_type parameter)."""
        rule_type = raw_config.get("type") or raw_config.get("ruleType")
        if not rule_type:
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status="failed:missing rule type in config",
            )

        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        try:
            result = self._client.create_cloud_app_rule(rule_type, config)
            target_id = str(result.get("id", ""))
            if source_id and target_id:
                self._register_remap(source_id, target_id)
            return PushRecord(resource_type="cloud_app_control_rule", name=name, status="created")
        except Exception as exc:
            exc_str = str(exc)
            if "409" in exc_str or "already exists" in exc_str.lower() or "conflict" in exc_str.lower():
                # Find by name across all rules of this type
                try:
                    existing = self._client.list_cloud_app_rules(rule_type)
                    found = next((r for r in existing if r.get("name") == name), None)
                    if found:
                        found_id = str(found.get("id", ""))
                        if source_id and found_id:
                            self._register_remap(source_id, found_id)
                        try:
                            self._client.update_cloud_app_rule(rule_type, found_id, config)
                            return PushRecord(resource_type="cloud_app_control_rule", name=name, status="updated")
                        except Exception as upd_exc:
                            return PushRecord(
                                resource_type="cloud_app_control_rule",
                                name=name,
                                status=f"failed:{upd_exc}",
                            )
                except Exception:
                    pass
                return PushRecord(
                    resource_type="cloud_app_control_rule",
                    name=name,
                    status="failed:409 — could not locate existing rule by name",
                )
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status=f"failed:{exc_str[:120]}",
            )

    def _push_list_resource(self, resource_type: str, entries: List[dict]) -> List[PushRecord]:
        """Special handler for allowlist / denylist — merge only."""
        records = []
        for entry in entries:
            raw_config = entry.get("raw_config", {})
            urls = raw_config.get("whitelistUrls") or raw_config.get("blacklistUrls") or []
            if not urls:
                records.append(PushRecord(
                    resource_type=resource_type,
                    name=resource_type,
                    status="skipped",
                ))
                continue
            try:
                if resource_type == "allowlist":
                    self._client.add_to_allowlist(urls)
                else:
                    self._client.add_to_denylist(urls)
                records.append(PushRecord(
                    resource_type=resource_type,
                    name=resource_type,
                    status="updated",
                ))
            except Exception as exc:
                records.append(PushRecord(
                    resource_type=resource_type,
                    name=resource_type,
                    status=f"failed:{exc}",
                ))
        return records

    def _strip(self, config: dict) -> dict:
        """Return a shallow copy of config with READONLY_FIELDS removed."""
        return {k: v for k, v in config.items() if k not in READONLY_FIELDS}

    def _apply_id_remap(self, config: dict) -> dict:
        """Walk config recursively. For any sub-dict with an 'id' key whose value
        (coerced to str) is in _id_remap, replace it with the mapped target ID."""
        return self._remap_value(copy.deepcopy(config))

    def _remap_value(self, value):
        if isinstance(value, dict):
            if "id" in value:
                id_str = str(value["id"])
                if id_str in self._id_remap:
                    value["id"] = type(value["id"])(self._id_remap[id_str])
            return {k: self._remap_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._remap_value(item) for item in value]
        return value

    def _register_remap(self, source_id, target_id) -> None:
        """Store source→target ID mapping (both coerced to str)."""
        self._id_remap[str(source_id)] = str(target_id)

    def _find_by_name(self, resource_type: str, name: str) -> Optional[str]:
        """Return target ID of existing resource matching name, or None."""
        list_method_name = _LIST_METHODS.get(resource_type)
        if not list_method_name:
            return None
        try:
            list_method = getattr(self._client, list_method_name)
            items = list_method()
            for item in items:
                if item.get("name") == name:
                    return str(item.get("id", ""))
        except Exception:
            pass
        return None
