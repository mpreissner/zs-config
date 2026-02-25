# Security Policy

## Supported Versions

Only the latest release is actively maintained.

| Version | Supported |
|---|---|
| 0.0.1 (latest) | Yes |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, open a [GitHub Security Advisory](../../security/advisories/new) or contact the maintainers privately. Include as much detail as possible:

- Type of vulnerability (e.g. credential exposure, injection, path traversal)
- Steps to reproduce
- Potential impact

You can expect an acknowledgement within 72 hours and a status update within 7 days.

## Scope

This tool stores Zscaler API credentials encrypted at rest using Fernet symmetric encryption. The encryption key is stored at `~/.config/zscaler-cli/secret.key` (chmod 600) or provided via the `ZSCALER_SECRET_KEY` environment variable.

Security-relevant areas to be aware of:
- Credential storage (`services/config_service.py`, `~/.config/zscaler-cli/secret.key`)
- File path handling in CSV import and certificate rotation flows
- API credential transmission via the zscaler-sdk-python library
