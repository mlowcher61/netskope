# Netskope Collection for Ansible (`mlowcher61.netskope`)

Ansible content for the [Netskope](https://www.netskope.com/) SSE / cloud
security platform, built for **Ansible Automation Platform (AAP)**. It wraps the
Netskope **REST API v2** (`https://<tenant>.goskope.com/api/v2/`, bearer token in
the `Netskope-API-Token` header).

Netskope has no official Ansible collection today; this fills that gap starting
with read-only *info* modules.

> **Release 0.1.0** — Tier 1, read-only modules only. State-changing modules are
> planned for later releases (see [Roadmap](#roadmap)).

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
ansible-galaxy collection install mlowcher61-netskope-0.1.0.tar.gz
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

| Module | Endpoint | Description | Status |
|---|---|---|---|
| `netskope_urllist_info` | `GET /policy/urllist` | URL lists, with client-side name/id filtering and field projection | ✅ 0.1.0 |
| `netskope_alert_info` | alerts / events | DLP, malware, policy alerts | 🔜 0.1.0 |
| `netskope_scim_info` | SCIM users / groups | List SCIM users and groups | 🔜 0.1.0 |
| `netskope_publisher_info` | Private Access publishers | Publishers + health status | 🔜 0.1.0 |

See each module's built-in docs for full options and return values:

```bash
ansible-doc mlowcher61.netskope.netskope_urllist_info
```

## Example

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

- **Tier 1 (0.1.0)** — read-only info modules *(in progress)*
- **Tier 2** — `netskope_urllist` (add/remove entries on an existing list only —
  the API cannot create URL lists), `netskope_scim_group`,
  `netskope_steering_profile`
- **Tier 3** — `netskope_publisher` (deploy ZTNA publishers),
  `netskope_quarantine`

Every state-changing module will check current state via the matching `_info`
logic before writing, so operations are idempotent.

## License

GPL-3.0-or-later. See [COPYING](COPYING).

## Author

mlowcher61 &lt;mlowcher@hotmail.com&gt;
