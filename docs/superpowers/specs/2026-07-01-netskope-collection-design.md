# Design — `mlowcher61.netskope` Ansible Collection (0.1.0)

**Date:** 2026-07-01
**Author:** mlowcher61
**Status:** Approved

## Purpose

Provide an Ansible Automation Platform (AAP) friendly collection for the Netskope
SSE / cloud security platform, which has no official Ansible collection today.
Wraps the Netskope REST API v2 (`https://<tenant>.goskope.com/api/v2/`, bearer
token in the `Netskope-API-Token` header).

## Scope of 0.1.0

Tier 1, read-only info modules only:

1. `netskope_urllist_info` — `GET /policy/urllist`, supports field filtering
2. `netskope_alert_info` — alerts/events (DLP, malware, policy categories)
3. `netskope_scim_info` — list SCIM users/groups
4. `netskope_publisher_info` — list Private Access publishers + health

Plus: shared `module_utils/netskope.py`, `galaxy.yml`, `meta/runtime.yml`,
per-module DOCUMENTATION/EXAMPLES/RETURN, AAP config-as-code, an execution
environment definition, unit tests, and GitHub Actions CI.

**Reference build order:** scaffold → `module_utils/netskope.py` →
`netskope_urllist_info` (module + unit test + podman sanity pass) **before** the
other three Tier 1 modules.

Tier 2 (`netskope_urllist`, `netskope_scim_group`, `netskope_steering_profile`)
and Tier 3 are explicitly out of scope for 0.1.0.

## Architecture

### Connection layer — `plugins/module_utils/netskope.py`

- `netskope_argument_spec()` — common argument spec: a `provider` dict
  (`tenant_url`, `api_token` with `no_log`) plus top-level `tenant_url` /
  `api_token` for convenience.
- **Credential resolution order:** explicit module param → `provider` dict →
  environment variables (`NETSKOPE_TENANT_URL`, `NETSKOPE_API_TOKEN`). This lets
  the AAP custom credential type inject secrets as env vars — no vault, no token
  in the playbook.
- `NetskopeClient` class:
  - Normalizes `tenant_url` → `https://<tenant>.goskope.com/api/v2`.
  - Injects the `Netskope-API-Token` header.
  - `request(method, path, params=None, data=None)` built on `open_url` from
    `ansible.module_utils.urls` — **zero external Python deps**, runs in any EE.
  - Error mapping: 401 → auth failed, 403 → forbidden, 429 → respect
    `Retry-After` + backoff, other HTTP errors → parsed `fail_json`.
  - `get_paginated(path, params=None)` — Netskope v2 `limit`/`offset` pagination,
    accumulating until a short page is returned.

### Info modules

Each module is a thin wrapper: build the client, call the endpoint, apply field
filtering, return the list plus useful metadata. Read-only, so `changed=False`
always and `supports_check_mode=True`.

### AAP config-as-code — `config-as-code/`

- A Netskope **custom credential type** (via `ansible.platform`) with `tenant_url`
  and secret `api_token` inputs and env-var injectors.
- `configure_aap.yml` — stands up the credential type, project, EE image, and a
  sample job template with the Netskope credential attached. One playbook to
  configure a new controller.

### Execution environment — `execution-environment/`

`execution-environment.yml` (ansible-builder v3) bundling the collection.
Documented `podman` build. No extra Python deps required.

## Testing / quality

- `tests/unit/` — `NetskopeClient.request` mocked, no live API calls.
  `netskope_urllist_info` and the `module_utils` resolution/pagination/error
  tests fleshed out as the reference pattern; stubs for the rest.
- `ansible-test sanity --docker` (podman) after each module.
- `meta/runtime.yml` floors at `requires_ansible '>=2.15'`.
- GitHub Actions CI runs sanity + units.

## Versioning / license

- `galaxy.yml`: namespace `mlowcher61`, name `netskope`, version `0.1.0`.
- License **GPL-3.0-or-later** (required for modules importing Ansible).

## Non-goals

- Creating URL lists (the API cannot; documented in the future Tier 2 module).
- Any write / state-changing module in this release.
