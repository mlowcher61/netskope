#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_publisher
short_description: Manage Netskope Private Access publishers
version_added: "0.3.0"
description:
  - Create, update, and delete Netskope Private Access (NPA) publishers via the
    C(/api/v2/infrastructure/publishers) endpoints.
  - Optionally generates a registration token for installing the publisher on a
    host with O(generate_token).
  - Use C(mlowcher61.netskope.netskope_publisher_info) to inspect publishers
    without changing anything.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - The publisher name; used to locate or create the publisher.
    type: str
    required: true
  lbrokerconnect:
    description:
      - Whether the publisher connects through the local broker.
      - When omitted, the tenant default is used on create and the current
        value is left untouched on update.
    type: bool
  state:
    description:
      - With V(present), ensure the publisher exists with the given attributes.
      - With V(absent), delete the publisher.
    type: str
    choices: [present, absent]
    default: present
  generate_token:
    description:
      - When V(true) and the publisher is present, generate a registration
        token and return it as RV(token).
      - The API issues a new token on every call, so a task with this option
        always reports changed. Only enable it when you are about to register
        the publisher.
    type: bool
    default: false
"""

EXAMPLES = r"""
- name: Ensure a publisher exists
  mlowcher61.netskope.netskope_publisher:
    name: dc1-publisher-01

- name: Create a publisher and fetch its registration token
  mlowcher61.netskope.netskope_publisher:
    name: dc1-publisher-02
    generate_token: true
  register: publisher

- name: Delete a retired publisher
  mlowcher61.netskope.netskope_publisher:
    name: dc1-publisher-01
    state: absent
"""

RETURN = r"""
publisher:
  description: The publisher object after the change (predicted under check mode).
  returned: success
  type: dict
token:
  description:
    - The registration token for installing the publisher.
    - Treat it as a secret; it grants registration against your tenant.
  returned: when O(generate_token=true), the publisher is present, and not in check mode
  type: str
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)

PUBLISHERS_PATH = "infrastructure/publishers"


def extract_publishers(payload):
    """Pull the publisher list out of the API response envelope."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return data.get("publishers", [])
    if isinstance(data, list):
        return data
    return []


def plan_publisher_changes(current, name, lbrokerconnect, state):
    """Compute the change plan for a publisher (pure, no I/O)."""
    if state == "absent":
        changed = current is not None
        return {
            "changed": changed,
            "action": "delete" if changed else "none",
            "before": current or {},
            "after": {} if changed else (current or {}),
        }

    if current is None:
        after = {"publisher_name": name}
        if lbrokerconnect is not None:
            after["lbrokerconnect"] = lbrokerconnect
        return {"changed": True, "action": "create", "before": {}, "after": after}

    needs_update = (
        lbrokerconnect is not None
        and bool(current.get("lbrokerconnect")) != lbrokerconnect
    )
    after = dict(current)
    if needs_update:
        after["lbrokerconnect"] = lbrokerconnect
    return {
        "changed": needs_update,
        "action": "update" if needs_update else "none",
        "before": current,
        "after": after,
    }


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str", required=True),
        lbrokerconnect=dict(type="bool"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        generate_token=dict(type="bool", default=False),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    name = module.params["name"]
    lbrokerconnect = module.params["lbrokerconnect"]
    state = module.params["state"]
    generate_token = module.params["generate_token"] and state == "present"

    client = NetskopeClient(module)
    payload = client.request("GET", PUBLISHERS_PATH)
    current = find_record(
        extract_publishers(payload), lambda p: p.get("publisher_name") == name
    )

    plan = plan_publisher_changes(current, name, lbrokerconnect, state)
    diff = {"before": plan["before"], "after": plan["after"]}
    changed = plan["changed"] or generate_token

    if module.check_mode:
        module.exit_json(changed=changed, publisher=plan["after"], diff=diff)

    action = plan["action"]
    publisher = current or {}
    if action == "create":
        body = {"name": name}
        if lbrokerconnect is not None:
            body["lbrokerconnect"] = lbrokerconnect
        resp = client.request("POST", PUBLISHERS_PATH, data=body)
        publisher = (resp or {}).get("data") or plan["after"]
    elif action == "update":
        body = {"name": name, "lbrokerconnect": lbrokerconnect}
        resp = client.request(
            "PATCH", "%s/%s" % (PUBLISHERS_PATH, current["publisher_id"]), data=body
        )
        publisher = (resp or {}).get("data") or plan["after"]
    elif action == "delete":
        client.request("DELETE", "%s/%s" % (PUBLISHERS_PATH, current["publisher_id"]))
        module.exit_json(changed=True, publisher={}, diff=diff)

    result = {"changed": changed, "publisher": publisher, "diff": diff}
    if generate_token:
        publisher_id = publisher.get("publisher_id")
        if publisher_id is None:
            module.fail_json(
                msg="Cannot generate a registration token: the API response "
                    "did not include a publisher_id for '%s'." % name
            )
        resp = client.request(
            "POST", "%s/%s/registration_token" % (PUBLISHERS_PATH, publisher_id)
        )
        result["token"] = ((resp or {}).get("data") or {}).get("token")
    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
