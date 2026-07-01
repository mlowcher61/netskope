# Design: Netskope Tier 2 — State-Changing Modules

**Date:** 2026-07-01
**Collection:** `mlowcher61.netskope` (Netskope SSE, REST API v2)
**Status:** Approved design, ready for implementation planning

## Summary

Tier 2 adds the collection's **first state-changing modules**:

- `netskope_urllist` — add/remove/reconcile URL entries on an **existing** URL list (the API cannot create lists).
- `netskope_scim_group` — manage a SCIM 2.0 group (create/rename/delete) **and** its membership.
- `netskope_steering_profile` — manage a steering profile / client configuration (full CRUD).

Tier 1 was entirely read-only `_info` modules. Tier 2 introduces `check_mode`, `--diff`, idempotency, and correct `changed` semantics for the first time. This document defines a single shared pattern for all three, so the second and third modules are copies of a proven approach rather than new inventions.

## Goals

- One reusable **state-changing pattern** every Tier 2 module follows.
- Full `check_mode` support: predict `changed` correctly under `--check` **without** calling any write endpoint.
- Full `--diff` support: return before/after snapshots.
- Idempotency by set/attribute comparison — re-running a task makes no changes and reports `changed=false`.
- Uniform `state: present|absent` + `purge: bool` model across modules where entries/members are managed as sets.
- Pure, network-free helper functions so idempotency logic is unit-tested without HTTP.

## Non-Goals

- Creating URL lists (unsupported by the API; `netskope_urllist` operates on existing lists only).
- A generic reconciler base class / framework. Each module keeps its own readable planner.
- Tier 3 modules (`netskope_publisher`, `netskope_quarantine`) — out of scope.

## Architecture — Shared State-Changing Pattern

Each module follows the Tier 1 split (pure helpers + thin `run_module()`), extended for writes.

### Pure helper: the change planner

A per-module pure function takes **current state** (as fetched from the API) plus the **desired parameters** and returns a structured **change plan**:

```
plan = {
    "changed": bool,
    "to_add":    [...],   # entries/members/attributes to create
    "to_remove": [...],   # entries/members to delete
    "to_update": {...},   # attribute changes for full-resource updates
    "before":    {...},   # snapshot for --diff
    "after":     {...},   # snapshot for --diff
}
```

The planner performs **no I/O**. All idempotency and diff logic lives here, which makes it directly unit-testable.

### Thin `run_module()`

1. Build `argument_spec` from `netskope_argument_spec()` + module-specific options.
2. `AnsibleModule(..., supports_check_mode=True)`.
3. GET current state via `NetskopeClient`.
4. Call the pure planner → `plan`.
5. If `plan["changed"]` is `False`: `exit_json(changed=False, ...)`.
6. If `module.check_mode`: `exit_json(changed=True, diff=..., ...)` **without writing**.
7. Otherwise execute the plan through `NetskopeClient.request(...)` (POST/PUT/PATCH/DELETE), then `exit_json(changed=True, diff=..., <resource>=...)`.

`--diff` output is `{"before": plan["before"], "after": plan["after"]}`.

### Shared `module_utils` addition

Add one small helper to `plugins/module_utils/netskope.py`:

- `get_one(path, match)` — fetch a resource collection and return the single record matching a name/id predicate, or `None` if absent. Gives all three modules a consistent "does it exist?" resolution and keeps existence-checking out of each module.

No other changes to `NetskopeClient`; `request()` already supports write verbs with a JSON body.

**Chosen over:** (a) a generic reconciler base class — harder to read and test, over-abstracts three modules that differ in real ways; (b) duplicated diff logic per module — invites drift. A shared existence helper + per-module pure planners is the middle path.

## Module: `netskope_urllist`

Manage the URL entries of an **existing** URL list.

**Parameters**

| Name | Type | Notes |
|------|------|-------|
| `name` | str | List identity (mutually exclusive-ish with `id`; at least one required). |
| `id` | int | List identity. |
| `urls` | list[str] | The entries to add/remove/reconcile. |
| `state` | str | `present` (default) or `absent`. |
| `purge` | bool | Default `false`. Only meaningful with `state=present`. |

**Behaviour**

- Resolve the list via `get_one` on `policy/urllist`. If not found → `fail_json` with a message that the API cannot create lists and pointing at `netskope_urllist_info` / the UI.
- `state=present`, `purge=false`: add any `urls` not already present.
- `state=present`, `purge=true`: reconcile so the list's entries equal `urls` exactly (add missing, remove extra).
- `state=absent`: remove the supplied `urls` (leave the rest).
- Write via `PUT policy/urllist/{id}` with the updated `data.urls` (append/remove sub-endpoints may exist; confirm in planning and prefer them if they reduce clobber risk).
- Comparison is set-based on the URL strings; order-insensitive.

**Return:** `urllist` (the resulting list object), `changed`, `diff`.

## Module: `netskope_scim_group`

Manage a SCIM 2.0 group and its membership.

**Parameters**

| Name | Type | Notes |
|------|------|-------|
| `display_name` | str | Group identity. |
| `external_id` | str | Alternate identity / set on create. |
| `members` | list[str] | User identifiers to add/remove/reconcile. |
| `state` | str | `present` (default) or `absent`. |
| `purge` | bool | Default `false`. Reconcile membership exactly when `true`. |

**Behaviour**

- Resolve the group via SCIM `/Groups` by `displayName` (and/or `externalId`).
- `state=present`: create the group (POST) if missing; the group *shell* (displayName/externalId) is otherwise treated as stable.
- Membership reconciled via SCIM **PATCH** add/remove member operations, using the same `present`/`absent` + `purge` semantics as `netskope_urllist`:
  - `present`+`purge=false`: PATCH-add missing members.
  - `present`+`purge=true`: PATCH so members equal `members` exactly.
  - `absent`: PATCH-remove the supplied members (group itself untouched unless...) — see note.
- `state=absent`: DELETE the group.
- **Sub-decision to pin down in the plan:** member identity resolution. `members` are given as user identifiers; the module must map them to SCIM member `value` (user id). Decide whether to accept raw SCIM user ids, usernames/emails (requiring a `/Users` lookup), or both. Default recommendation: accept SCIM user id directly first (no extra lookups), add username resolution only if needed.
- **Ruling — `state` vs `members` semantics (decided):** for `netskope_scim_group` the group is a deletable resource, so `state` governs the *group object*: `state=present` ensures the group exists; `state=absent` deletes the entire group and **ignores** `members`. Under `state=present`, membership is always reconciled toward `members`: add missing members, and with `purge=true` also remove any members not in `members`. There is no per-member `absent`; to shrink a group, run `state=present, purge=true` with the reduced desired set.
- **Deliberate difference from `netskope_urllist`:** in `netskope_urllist` the list itself is not deletable via the API, so there `state=absent` removes the supplied *entries*. In `netskope_scim_group` (and `netskope_steering_profile`) the container *is* deletable, so `state=absent` removes the *container*. The unifying rule is: **`state` acts on the most-specific thing this module actually owns** (entries for urllist, the group/profile for the others), and **`purge` always means "reconcile the managed set exactly."** This difference is documented in each module's `DOCUMENTATION` so operators are not surprised.

**Return:** `scim_group` (the resulting group object), `changed`, `diff`.

## Module: `netskope_steering_profile`

Manage a steering profile / client configuration (full CRUD).

**Parameters (provisional)**

| Name | Type | Notes |
|------|------|-------|
| `name` | str | Profile identity. |
| `config` | dict | Profile attributes (steer/bypass rules, targeting). |
| `state` | str | `present` (default) or `absent`. |

**Behaviour**

- Same full-resource shape as the `netskope_scim_group` group object: resolve by `name` → create if missing → update changed attributes → delete on `absent`.
- **API verification required (blocking for this module's plan, not for the others):** the exact v2 endpoint path and JSON schema for steering profiles live in the per-tenant Swagger (`Settings > Tools > REST API v2 > API Documentation`) and are not reliably public. Documented reads exist ("Get a steering configuration list", "Get Steering Configuration Information"); create/update/delete paths and the `config` schema must be confirmed against the tenant Swagger before implementing. Until confirmed, `config` is treated as an opaque attribute dict compared shallowly for idempotency.

**Return:** `steering_profile` (the resulting object), `changed`, `diff`.

## Testing

- **Unit tests** per module target the pure planner:
  - no-op idempotency (re-run → `changed=false`),
  - `present` add,
  - `present` + `purge` reconcile (add + remove),
  - `absent` remove/delete,
  - `check_mode` predicts `changed` without writing,
  - `--diff` before/after correctness.
- No network in unit tests; the planner is fed fixture "current state" dicts.
- `ansible-test sanity --docker default --python 3.11` clean on all three modules (same workflow as Tier 1; see the collection test-workflow note for the podman + rsync-to-`ansible_collections` gotchas).

## Open Items Carried Into Planning

1. `netskope_urllist`: confirm whether dedicated append/remove sub-endpoints exist and are preferable to full `PUT` (reduces clobber risk).
2. `netskope_scim_group`: member identity resolution (SCIM user id vs username/email) and the exact `state`/`members`/`purge` interaction wording.
3. `netskope_steering_profile`: confirm CRUD endpoint paths and `config` schema against the tenant Swagger.
