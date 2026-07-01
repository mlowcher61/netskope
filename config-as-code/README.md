# Config as Code — Netskope on Ansible Automation Platform

This directory configures Ansible Automation Platform (AAP) so a new user can
start using the `mlowcher61.netskope` collection with minimal clicking.

## What it creates

| Resource | Module | Why |
|---|---|---|
| Organization | `ansible.platform.organization` | Owns the resources below |
| **Netskope API Token** credential type | `ansible.controller.credential_type` | Stores the tenant URL + token as a secret and injects them as `NETSKOPE_TENANT_URL` / `NETSKOPE_API_TOKEN` env vars — no vault, no token in playbooks |
| Execution environment | `ansible.controller.execution_environment` | Registers the EE image that bundles this collection |
| Demo project + job template | `ansible.controller.project`, `ansible.controller.job_template` | An example that runs `netskope_urllist_info` (optional) |

> Organizations are a gateway resource, so `ansible.platform` is used for them.
> Credential types, execution environments, projects and job templates are only
> provided by `ansible.controller`, so they are used for those.

## Run it

```bash
ansible-galaxy collection install ansible.platform ansible.controller

export CONTROLLER_HOST=https://aap.example.com
export CONTROLLER_USERNAME=admin
export CONTROLLER_PASSWORD='...'        # or CONTROLLER_OAUTH_TOKEN
export CONTROLLER_VERIFY_SSL=true

# Edit vars/aap_config.yml (EE image, demo settings), then:
ansible-playbook -i inventory.ini configure_aap.yml
```

After it runs, open the **Netskope API Token** credential in the controller,
create a credential with your tenant URL and token, and attach it to any job
template that runs Netskope modules.
