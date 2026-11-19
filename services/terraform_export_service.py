"""Generate Terraform HCL from imported ZIA / ZPA resources.

Produces a best-effort .tf file that covers all resource types with a
supported Terraform provider resource.  Fields that require cross-references
(objects carrying an {id, name} pair) are emitted as comments so the user
can wire them up manually.  Read-only / computed fields are omitted.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_session
from db.models import ZIAResource, ZPAResource

# ---------------------------------------------------------------------------
# Resource type → Terraform type maps
# ---------------------------------------------------------------------------

ZIA_RESOURCE_MAP: Dict[str, str] = {
    "url_category": "zia_url_categories",
    "url_filtering_rule": "zia_url_filtering_rules",
    "firewall_rule": "zia_firewall_filtering_rules",
    "firewall_dns_rule": "zia_firewall_dns_rules",
    "firewall_ips_rule": "zia_firewall_ips_rules",
    "ssl_inspection_rule": "zia_ssl_inspection_rules",
    "forwarding_rule": "zia_forwarding_control_rule",
    "ip_destination_group": "zia_ip_destination_groups",
    "ip_source_group": "zia_ip_source_groups",
    "network_service": "zia_network_services",
    "network_svc_group": "zia_network_service_groups",
    "rule_label": "zia_rule_labels",
    "time_interval": "zia_time_windows",
    "location": "zia_location_management",
    "admin_user": "zia_admin_users",
    "department": "zia_user_management_departments",
    "group": "zia_user_management_groups",
    "user": "zia_user_management_users",
    "dlp_engine": "zia_dlp_engines",
    "dlp_dictionary": "zia_dlp_dictionaries",
    "dlp_web_rule": "zia_dlp_web_rules",
    "static_ip": "zia_traffic_forwarding_static_ip",
    "vpn_credential": "zia_traffic_forwarding_vpn_credentials",
    "gre_tunnel": "zia_traffic_forwarding_gre_tunnel",
    "sandbox_rule": "zia_sandbox_rules",
    "bandwidth_class": "zia_bandwidth_classes",
    "bandwidth_control_rule": "zia_bandwidth_control_rules",
    "nat_control_rule": "zia_nat_control_rules",
    "workload_group": "zia_workload_groups",
    "tenancy_restriction_profile": "zia_tenancy_restriction_profile",
}

ZPA_RESOURCE_MAP: Dict[str, str] = {
    "application": "zpa_application_segment",
    "segment_group": "zpa_segment_group",
    "server_group": "zpa_server_group",
    "app_connector_group": "zpa_app_connector_group",
    "pra_portal": "zpa_pra_portal_controller",
    "pra_credential": "zpa_pra_credential_controller",
    "pra_console": "zpa_pra_console_controller",
    "policy_access": "zpa_policy_access_rule",
    "policy_timeout": "zpa_policy_timeout_rule",
    "policy_forwarding": "zpa_policy_forwarding_rule",
    "policy_inspection": "zpa_policy_inspection_rule",
    "policy_isolation": "zpa_policy_isolation_rule",
    "service_edge_group": "zpa_service_edge_group",
    "lss_config": "zpa_lss_config_controller",
}

ZPA_DATA_MAP: Dict[str, str] = {
    "idp": "zpa_idp_controller",
    "trusted_network": "zpa_trusted_network",
    "enrollment_cert": "zpa_enrollment_cert",
    "saml_attribute": "zpa_saml_attribute",
}

# Fields that are read-only / computed and should not appear in .tf files.
SKIP_FIELDS = {
    "id",
    "last_modified_time",
    "last_modified_by",
    "modified_time",
    "modified_by",
    "creation_time",
    "created_time",
    "created_by",
    "created_at",
    "updated_at",
    "access_control",
    "creator_context",
    "extensions",
    "is_name_l10n_tag",
    "external_id",
    "predefined",
    "default_rule",
    "is_default_rule",
    "microtenant_name",
    "policy_migrated",
    "config_space",
}

# Secret attributes the providers accept.  The APIs never return the real
# value (ZIA masks a PSK as "*****", ZPA omits PRA credentials), so each one
# becomes a sensitive input variable the user supplies at apply time.
SECRET_FIELDS = {"pre_shared_key", "password", "private_key", "passphrase"}


def _required_secrets(resource_type: str, cfg: Dict[str, Any]) -> List[str]:
    """Secrets a resource needs even when the API left them out of the record."""
    if resource_type == "vpn_credential":
        return ["pre_shared_key"]
    if resource_type == "pra_credential":
        ctype = str(cfg.get("credential_type", "")).upper()
        if ctype == "SSH_KEY":
            return ["private_key"]
        return ["password"]
    return []


def _snake(key: str) -> str:
    """Convert an API camelCase key to the provider's snake_case attribute name."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    return re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s).lower()


def _normalize(v: Any) -> Any:
    """Recursively snake_case dict keys (raw_config holds the API's camelCase)."""
    if isinstance(v, dict):
        out = {_snake(k): _normalize(x) for k, x in v.items()}
        # ZIA accepts "psk" as an alias; the provider attribute is pre_shared_key.
        if "psk" in out:
            out.setdefault("pre_shared_key", out["psk"])
            del out["psk"]
        return out
    if isinstance(v, list):
        return [_normalize(x) for x in v]
    return v


def _variable_block(name: str) -> str:
    return f'variable "{name}" {{\n  type      = string\n  sensitive = true\n}}\n'


# ---------------------------------------------------------------------------
# HCL helpers
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    """Return a valid Terraform label derived from a resource name."""
    label = re.sub(r"[^a-zA-Z0-9_]", "_", str(name)).strip("_").lower()
    label = re.sub(r"_+", "_", label)
    if label and label[0].isdigit():
        label = "r_" + label
    return label or "resource"


def _hcl_str(v: str) -> str:
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    s = s.replace("${", "$${").replace("%{", "%%{")
    return '"' + s + '"'


def _is_ref(v: Any) -> bool:
    """True if v looks like a Zscaler reference object {id, name, ...}."""
    return isinstance(v, dict) and "id" in v


def _render_scalar(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _hcl_str(v)
    return None


def _one_line(v: Any) -> str:
    """Flatten a value for use inside a # comment (a newline would end it)."""
    return re.sub(r"[\r\n]+", " ", str(v))


def _ref_comment(key: str, items: List[Any], pad: str) -> str:
    parts = []
    for r in items:
        if isinstance(r, dict):
            rid = _one_line(r.get("id", "?"))
            rname = _one_line(r.get("name", ""))
            parts.append(f'{{id={rid}, name="{rname}"}}')
        else:
            parts.append(_one_line(r))
    joined = ", ".join(parts)
    return f"{pad}# {key} = [{joined}]  # TODO: replace with resource references"


def _render_block(
    fields: Dict[str, Any],
    indent: int = 1,
    var_prefix: str = "",
    secret_vars: Optional[List[str]] = None,
) -> List[str]:
    """Recursively render a dict as HCL attribute lines and nested blocks.

    Secret fields render as `key = var.<prefix>_<key>`; the variable names
    are appended to secret_vars so the caller can declare them.
    """
    pad = "  " * indent
    scalars: List[Tuple[str, str]] = []
    ref_comments: List[str] = []
    nested: List[Tuple[str, List[Dict]]] = []

    for key, val in fields.items():
        if key in SKIP_FIELDS:
            continue

        if key in SECRET_FIELDS and secret_vars is not None:
            var_name = _slug(f"{var_prefix}_{key}")
            secret_vars.append(var_name)
            scalars.append((key, f"var.{var_name}"))
            continue

        if val is None:
            continue

        if isinstance(val, list):
            if not val:
                continue
            # List of scalars
            if all(isinstance(x, (str, int, float, bool)) and not isinstance(x, dict) for x in val):
                items = []
                for x in val:
                    s = _render_scalar(x)
                    if s is not None:
                        items.append(s)
                if items:
                    scalars.append((key, "[" + ", ".join(items) + "]"))
            # List of reference objects
            elif all(_is_ref(x) for x in val):
                ref_comments.append(_ref_comment(key, val, pad))
            # List of mixed or nested content objects
            elif all(isinstance(x, dict) for x in val):
                refs = [x for x in val if _is_ref(x)]
                non_refs = [x for x in val if not _is_ref(x)]
                if refs:
                    ref_comments.append(_ref_comment(key, refs, pad))
                if non_refs:
                    nested.append((key, non_refs))
            # Mixed or unknown — comment out
            else:
                ref_comments.append(f"{pad}# {key} = ...  # complex value, configure manually")

        elif isinstance(val, dict):
            if _is_ref(val):
                ref_comments.append(_ref_comment(key, [val], pad))
            else:
                nested.append((key, [val]))

        else:
            s = _render_scalar(val)
            if s is not None:
                scalars.append((key, s))

    lines: List[str] = []

    for key, hcl_val in scalars:
        lines.append(f"{pad}{key} = {hcl_val}")

    if ref_comments:
        lines.append("")
        lines.append(f"{pad}# Cross-references — replace with Terraform resource references:")
        lines.extend(ref_comments)

    for key, block_list in nested:
        for block in block_list:
            inner_fields = {k: v for k, v in block.items() if k not in SKIP_FIELDS}
            if not inner_fields:
                continue
            lines.append("")
            lines.append(f"{pad}{key} {{")
            lines.extend(
                _render_block(inner_fields, indent + 1, f"{var_prefix}_{key}", secret_vars)
            )
            lines.append(f"{pad}}}")

    return lines


def _resource_block(
    tf_type: str, label: str, fields: Dict[str, Any], resource_type: str = ""
) -> str:
    fields = dict(fields)
    for key in _required_secrets(resource_type, fields):
        fields.setdefault(key, None)
    secret_vars: List[str] = []
    body = _render_block(fields, var_prefix=label, secret_vars=secret_vars)
    inner = "\n".join(body)
    variables = "".join(_variable_block(v) for v in secret_vars)
    return f'{variables}resource "{tf_type}" "{label}" {{\n{inner}\n}}\n'


def _data_block(tf_type: str, label: str, fields: Dict[str, Any]) -> str:
    # Data sources only take lookup arguments; the name is enough to find it.
    body = _render_block({"name": fields["name"]} if fields.get("name") else {})
    inner = "\n".join(body)
    return f'data "{tf_type}" "{label}" {{\n{inner}\n}}\n'


# ---------------------------------------------------------------------------
# Provider headers
# ---------------------------------------------------------------------------


def _header(product: str) -> str:
    return f'''\
# =============================================================================
# Zscaler {product.upper()} — Terraform configuration (auto-generated by zs-config)
# Provider docs: https://registry.terraform.io/providers/zscaler/{product}/latest
#
# IMPORTANT: This is a best-effort export.  Fields marked with TODO require
# cross-references to other resources.  Secrets are never exported: each one
# is a sensitive variable to supply via a .tfvars file or TF_VAR_* env vars.
# Review before applying.
# =============================================================================

terraform {{
  required_providers {{
    {product} = {{
      source  = "zscaler/{product}"
      version = "~> 4.0"
    }}
  }}
}}

provider "{product}" {{
  # Credentials come from environment variables; see the provider docs above.
}}

'''


ZIA_HEADER = _header("zia")
ZPA_HEADER = _header("zpa")

# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------


def _dedup_label(label: str, seen: Dict[str, int]) -> str:
    if label not in seen:
        seen[label] = 0
        return label
    seen[label] += 1
    return f"{label}_{seen[label]}"


def generate_zia(tenant_id: int) -> str:
    sections: List[str] = [ZIA_HEADER]
    seen_labels: Dict[str, int] = {}

    with get_session() as session:
        rows = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, is_deleted=False)
            .order_by(ZIAResource.resource_type, ZIAResource.name)
            .all()
        )

    current_type = None
    for row in rows:
        tf_type = ZIA_RESOURCE_MAP.get(row.resource_type)
        if not tf_type:
            continue

        if row.resource_type != current_type:
            current_type = row.resource_type
            sections.append(f"# {'─' * 72}\n# {tf_type}\n# {'─' * 72}\n")

        label = _dedup_label(_slug(row.name or row.zia_id or "resource"), seen_labels)
        fields = _normalize(row.raw_config or {})
        sections.append(_resource_block(tf_type, label, fields, row.resource_type))

    return "\n".join(sections)


def generate_zpa(tenant_id: int) -> str:
    sections: List[str] = [ZPA_HEADER]
    seen_labels: Dict[str, int] = {}

    with get_session() as session:
        rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, is_deleted=False)
            .order_by(ZPAResource.resource_type, ZPAResource.name)
            .all()
        )

    current_type = None
    for row in rows:
        tf_type = ZPA_RESOURCE_MAP.get(row.resource_type)
        is_data = row.resource_type in ZPA_DATA_MAP
        if not tf_type:
            tf_type = ZPA_DATA_MAP.get(row.resource_type)
            is_data = True
        if not tf_type:
            continue

        if row.resource_type != current_type:
            current_type = row.resource_type
            kind = "data" if is_data else "resource"
            sections.append(f"# {'─' * 72}\n# {tf_type}  ({kind})\n# {'─' * 72}\n")

        label = _dedup_label(_slug(row.name or row.zpa_id or "resource"), seen_labels)
        fields = _normalize(row.raw_config or {})
        if is_data:
            sections.append(_data_block(tf_type, label, fields))
        else:
            sections.append(_resource_block(tf_type, label, fields, row.resource_type))

    return "\n".join(sections)
