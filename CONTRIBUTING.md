# Contributing to zs-config

Thanks for your interest in contributing.

## Getting Started

1. Fork the repository and create a branch from `dev` (not `main`)
2. Install dependencies: `pip install -r requirements.txt`
3. Launch: `python cli/z_config.py`
3. Make your changes, keeping the existing code style
4. Test manually against a real or sandbox Zscaler tenant where possible
5. Submit a pull request against `dev`

## Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable releases only |
| `dev` | Active development — all PRs target here |

## What to Work On

Check the [issues](../../issues) for open bugs and feature requests. If you want to add something new, open an issue first so we can discuss the approach before you invest time in it.

## Code Style

- Follow the patterns already in the codebase — services are pure business logic with no CLI concerns, menus handle only display and input
- All writes to the Zscaler API must be logged via `audit_service.log()`
- Table views should use `scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())` from `cli/scroll_view.py`
- questionary prompts use plain text only — no Rich markup tags in choice labels or prompt strings

## Reporting Bugs

Use the [bug report template](../../issues/new?template=bug_report.md). Include:
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS
- Zscaler product (ZPA / ZIA) and relevant configuration (sanitised)

## Feature Requests

Use the [feature request template](../../issues/new?template=feature_request.md).

## Security Issues

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md).
