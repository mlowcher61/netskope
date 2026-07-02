# Netskope Collection for Ansible (`mlowcher61.netskope`)

Ansible content for the [Netskope](https://www.netskope.com/) SSE / cloud
security platform, built for **Ansible Automation Platform (AAP)**. It wraps the
Netskope **REST API v2** (`https://<tenant>.goskope.com/api/v2/`, bearer token in
the `Netskope-API-Token` header).

Netskope has no official Ansible collection today; this fills that gap with
read-only *info* modules plus modules that manage URL list entries and SCIM
groups.

> **Release 0.2.0** — adds the first state-changing modules
> (`netskope_urllist`, `netskope_scim_group`), with full `--check` and `--diff`
> support. More are planned (see [Roadmap](#roadmap)).

## Requirements

- `ansible-core >= 2.15`
- A Netskope tenant and a REST API v2 token
- Python 3.9+ on the execution node
- No third-party Python packages (the modules use only ansible-core + stdlib)

## Installation

```bash
# From this git repository
ansible-galaxy collection install git+https://github.com/mlowcher61/netskope.git

# ...or build and install locally
ansible-galaxy collection build
ansible-galaxy collection install mlowcher61-netskope-0.2.0.tar.gz
```

## Authentication

Every module needs a **tenant URL** and an **API token**. They are resolved in
this order (first match wins):

1. **Module parameters** — `tenant_url` / `api_token`
2. **`provider` dict** — `provider: {tenant_url: ..., api_token: ...}` (mirrors
   the provider pattern used in network collections)
3. **Environment variables** — `NETSKOPE_TENANT_URL` / `NETSKOPE_API_TOKEN`

### In AAP: use a custom credential (recommended)

Rather than vaulting the token, create the **Netskope API Token** custom
credential type shipped in [`config-as-code/`](config-as-code/). It stores the
tenant URL and token as a secret and injects them as the `NETSKOPE_*`
environment variables at run time. Playbooks then need **no** credential vars:

```yaml
- hosts: localhost
  tasks:
    - mlowcher61.netskope.netskope_urllist_info:
      register: result
```

### Outside AAP

```yaml
- hosts: localhost
  tasks:
    - mlowcher61.netskope.netskope_urllist_info:
        provider:
          tenant_url: https://acme.goskope.com
          api_token: "{{ netskope_api_token }}"   # from a vault or prompt
      register: result
```

or `export NETSKOPE_TENANT_URL=... NETSKOPE_API_TOKEN=...` and pass nothing.

## Modules

### Info (read-only)

| Module | Endpoint | Description | Since |
|---|---|---|---|
| `netskope_urllist_info` | `GET /policy/urllist` | URL lists, with client-side name/id filtering and field projection | 0.1.0 |
| `netskope_alert_info` | alerts / events | DLP, malware, policy alerts | 0.1.0 |
| `netskope_scim_info` | SCIM users / groups | List SCIM users and groups | 0.1.0 |
| `netskope_publisher_info` | Private Access publishers | Publishers + health status | 0.1.0 |

### Management (state-changing)

| Module | Endpoint | Description | Since |
|---|---|---|---|
| `netskope_urllist` | `PUT /policy/urllist/{id}` | Add/remove/reconcile URL entries on an **existing** list (the API cannot create lists) | 0.2.0 |
| `netskope_scim_group` | SCIM `/Groups` | Create/delete a SCIM group and manage its membership | 0.2.0 |

Both management modules support **check mode** (`--check` predicts `changed`
without writing) and **diff mode** (`--diff` shows before/after). They share
one idempotency model:

- `state: present` (default) ensures the thing the module owns exists /
  contains what you listed; `state: absent` removes it.
- `purge: true` reconciles exactly — anything you did *not* list is removed.
  With the default `purge: false`, existing extras are left alone.
- One deliberate difference: a URL list itself cannot be created or deleted via
  the API, so in `netskope_urllist` `state: absent` removes the supplied
  *entries* from the list. A SCIM group *is* deletable, so in
  `netskope_scim_group` `state: absent` deletes the *group*.

See each module's built-in docs for full options and return values:

```bash
ansible-doc mlowcher61.netskope.netskope_urllist_info
```

## Examples

Query a URL list:

```yaml
- name: Find a specific URL list, returning only id and name
  mlowcher61.netskope.netskope_urllist_info:
    name: Corporate-Allowlist
    fields:
      - id
      - name
  register: allowlist

- ansible.builtin.debug:
    var: allowlist.urllists
```

Manage its entries (run with `--check --diff` first to preview):

```yaml
- name: Ensure these URLs are on the allowlist (leaves other entries alone)
  mlowcher61.netskope.netskope_urllist:
    name: Corporate-Allowlist
    urls:
      - example.com
      - partner.example.org

- name: Make the allowlist contain exactly this set (removes anything else)
  mlowcher61.netskope.netskope_urllist:
    name: Corporate-Allowlist
    purge: true
    urls:
      - example.com
      - partner.example.org
```

Manage a SCIM group and its members (SCIM user ids):

```yaml
- name: Ensure the group exists with these members added
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    members:
      - "{{ scim_user_id_alice }}"
      - "{{ scim_user_id_bob }}"

- name: Delete the group entirely
  mlowcher61.netskope.netskope_scim_group:
    display_name: Old-Team
    state: absent
```

More in [`examples/`](examples/).

## Ansible Automation Platform setup

[`config-as-code/`](config-as-code/) contains a single playbook that stands up
the credential type, execution environment, and an optional demo project + job
template. [`execution-environment/`](execution-environment/) contains an
`ansible-builder` v3 definition to build an EE image that bundles this
collection.

```bash
cd config-as-code
export CONTROLLER_HOST=... CONTROLLER_USERNAME=... CONTROLLER_PASSWORD=...
ansible-playbook -i inventory.ini configure_aap.yml
```

## Development & testing

The collection must live at `.../ansible_collections/mlowcher61/netskope/` for
`ansible-test` to work.

```bash
# Sanity (uses Docker or Podman)
ansible-test sanity --docker

# Unit tests
ansible-test units --docker
```

CI (GitHub Actions) runs sanity across `stable-2.16` / `stable-2.17` plus units
on every push and pull request.

## Roadmap

- **Tier 1 (0.1.0)** — read-only info modules ✅ *done*
- **Tier 2 (0.2.0)** — `netskope_urllist`, `netskope_scim_group` ✅ *done*;
  `netskope_steering_profile` pending (its exact v2 endpoint and schema must be
  confirmed against the tenant's Swagger docs first)
- **Tier 3** — `netskope_publisher` (deploy ZTNA publishers),
  `netskope_quarantine`

Every state-changing module will check current state via the matching `_info`
logic before writing, so operations are idempotent.

## Changelog

See [CHANGELOG.rst](CHANGELOG.rst). Release notes are maintained with
[antsibull-changelog](https://github.com/ansible-community/antsibull-changelog):
add a fragment under `changelogs/fragments/` with each change, then run
`antsibull-changelog release` when cutting a version.

## License

GPL-3.0-or-later. See [COPYING](COPYING).

## Author

mlowcher61 &lt;mlowcher@hotmail.com&gt;
