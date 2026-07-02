#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_private_app
short_description: Manage Netskope Private Access private applications
version_added: "0.3.0"
description:
  - Create, update, and delete NPA private application definitions via the
    C(/api/v2/steering/apps/private) endpoints.
  - Publishers are referenced by name and resolved to ids automatically.
  - On update, attributes you do not specify are kept at their current values.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - The private application name; used to locate or create the app.
    type: str
    required: true
  host:
    description:
      - Hostnames, IPs, or CIDR ranges the application is reachable at.
      - Required when creating a new application.
    type: list
    elements: str
  real_host:
    description:
      - The real host used for validating a signed certificate.
    type: str
  protocols:
    description:
      - Protocols and ports the application listens on.
      - Required when creating a new application.
    type: list
    elements: dict
    suboptions:
      type:
        description: The transport protocol.
        type: str
        choices: [tcp, udp]
        required: true
      port:
        description: Port or comma-separated ports/ranges, e.g. V(80,443).
        type: str
        required: true
  publishers:
    description:
      - Names of the publishers that serve this application.
      - Resolved to publisher ids via the publishers API.
    type: list
    elements: str
  use_publisher_dns:
    description:
      - Whether the publishers resolve DNS for the application hosts.
    type: bool
  clientless_access:
    description:
      - Whether browser (clientless) access is enabled.
    type: bool
  trust_self_signed_certs:
    description:
      - Whether self-signed certificates are trusted for this application.
    type: bool
  tags:
    description:
      - Tag names to associate with the application.
    type: list
    elements: str
  state:
    description:
      - With V(present), ensure the application exists with the given
        attributes. With V(absent), delete it.
    type: str
    choices: [present, absent]
    default: present
"""

EXAMPLES = r"""
- name: Publish an internal web app through two publishers
  mlowcher61.netskope.netskope_private_app:
    name: intranet-wiki
    host:
      - wiki.corp.example.com
    protocols:
      - type: tcp
        port: "443"
    publishers:
      - dc1-publisher-01
      - dc2-publisher-01
    use_publisher_dns: true

- name: Delete a retired private app
  mlowcher61.netskope.netskope_private_app:
    name: legacy-app
    state: absent
"""

RETURN = r"""
private_app:
  description: The private application object after the change (predicted under check mode).
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)

PRIVATE_APPS_PATH = "steering/apps/private"
PUBLISHERS_PATH = "infrastructure/publishers"

# Writable attributes carried over from the current object on update when the
# task does not specify them.
MANAGED_FIELDS = (
    "host", "real_host", "protocols", "publishers", "use_publisher_dns",
    "clientless_access", "trust_self_signed_certs", "tags",
)


def extract_records(payload, key):
    """Pull a record list out of the API response envelope."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return data.get(key, [])
    if isinstance(data, list):
        return data
    return []


def _host_set(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split(",")
    return set(h.strip() for h in value if h and h.strip())


def _protocol_set(protocols):
    if protocols is None:
        return None
    return set(
        (p.get("type"), frozenset(str(p.get("port", "")).replace(" ", "").split(",")))
        for p in protocols
    )


def _publisher_names(publishers):
    if publishers is None:
        return None
    return set(p.get("publisher_name") for p in publishers)


def _tag_names(tags):
    if tags is None:
        return None
    return set(t.get("tag_name") if isinstance(t, dict) else t for t in tags)


def desired_body(params, publisher_map):
    """Build the writable request body from module params (pure, no I/O).

    ``publisher_map`` maps publisher name -> id for names used in the task.
    Keys the task did not specify are omitted.
    """
    body = {"app_name": params["name"]}
    if params["host"] is not None:
        body["host"] = ",".join(params["host"])
    if params["real_host"] is not None:
        body["real_host"] = params["real_host"]
    if params["protocols"] is not None:
        body["protocols"] = [
            {"type": p["type"], "port": p["port"]} for p in params["protocols"]
        ]
    if params["publishers"] is not None:
        body["publishers"] = [
            {"publisher_id": str(publisher_map[n]), "publisher_name": n}
            for n in params["publishers"]
        ]
    for key in ("use_publisher_dns", "clientless_access", "trust_self_signed_certs"):
        if params[key] is not None:
            body[key] = params[key]
    if params["tags"] is not None:
        body["tags"] = [{"tag_name": t} for t in params["tags"]]
    return body


def plan_private_app_changes(current, desired, state):
    """Compute the change plan for a private app (pure, no I/O)."""
    if state == "absent":
        changed = current is not None
        return {
            "changed": changed,
            "action": "delete" if changed else "none",
            "before": current or {},
            "after": {} if changed else (current or {}),
        }

    if current is None:
        return {"changed": True, "action": "create", "before": {}, "after": desired}

    comparators = {
        "host": _host_set,
        "protocols": _protocol_set,
        "publishers": _publisher_names,
        "tags": _tag_names,
    }
    changed_fields = []
    for field in MANAGED_FIELDS:
        if field not in desired:
            continue
        normalize = comparators.get(field, lambda v: v)
        if normalize(desired[field]) != normalize(current.get(field)):
            changed_fields.append(field)

    after = dict(current)
    for field in changed_fields:
        after[field] = desired[field]
    return {
        "changed": bool(changed_fields),
        "action": "update" if changed_fields else "none",
        "before": current,
        "after": after,
    }


def build_update_body(current, desired):
    """Merge unspecified managed fields from the current object into the body."""
    body = dict(desired)
    for field in MANAGED_FIELDS:
        if field not in body and current.get(field) is not None:
            body[field] = current[field]
    return body


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str", required=True),
        host=dict(type="list", elements="str"),
        real_host=dict(type="str"),
        protocols=dict(
            type="list",
            elements="dict",
            options=dict(
                type=dict(type="str", choices=["tcp", "udp"], required=True),
                port=dict(type="str", required=True),
            ),
        ),
        publishers=dict(type="list", elements="str"),
        use_publisher_dns=dict(type="bool"),
        clientless_access=dict(type="bool"),
        trust_self_signed_certs=dict(type="bool"),
        tags=dict(type="list", elements="str"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    name = module.params["name"]
    state = module.params["state"]

    client = NetskopeClient(module)

    publisher_map = {}
    if module.params["publishers"] and state == "present":
        payload = client.request("GET", PUBLISHERS_PATH)
        known = extract_records(payload, "publishers")
        for pub_name in module.params["publishers"]:
            record = find_record(
                known, lambda p: p.get("publisher_name") == pub_name
            )
            if record is None:
                module.fail_json(msg="Publisher '%s' was not found." % pub_name)
            publisher_map[pub_name] = record["publisher_id"]

    payload = client.request("GET", PRIVATE_APPS_PATH)
    current = find_record(
        extract_records(payload, "private_apps"),
        lambda a: a.get("app_name") == name,
    )

    desired = desired_body(module.params, publisher_map)
    plan = plan_private_app_changes(current, desired, state)
    diff = {"before": plan["before"], "after": plan["after"]}

    if plan["action"] == "create" and not (
        module.params["host"] and module.params["protocols"]
    ):
        module.fail_json(
            msg="Creating private app '%s' requires both host and protocols." % name
        )

    if not plan["changed"]:
        module.exit_json(changed=False, private_app=current or {}, diff=diff)

    if module.check_mode:
        module.exit_json(changed=True, private_app=plan["after"], diff=diff)

    action = plan["action"]
    if action == "create":
        resp = client.request("POST", PRIVATE_APPS_PATH, data=desired)
        result = (resp or {}).get("data") or plan["after"]
    elif action == "update":
        body = build_update_body(current, desired)
        resp = client.request(
            "PUT", "%s/%s" % (PRIVATE_APPS_PATH, current["app_id"]), data=body
        )
        result = (resp or {}).get("data") or plan["after"]
    else:  # delete
        client.request("DELETE", "%s/%s" % (PRIVATE_APPS_PATH, current["app_id"]))
        result = {}
    module.exit_json(changed=True, private_app=result, diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
