#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_urllist
short_description: Manage entries on an existing Netskope URL list
version_added: "0.2.0"
description:
  - Add, remove, or reconcile the URL entries of an existing URL list via the
    C(policy/urllist) endpoints.
  - The Netskope API cannot create or delete URL lists, so the target list must
    already exist; this module only manages its entries. Use
    M(mlowcher61.netskope.netskope_urllist_info) to discover lists.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - The name of the existing URL list to modify.
      - Exactly one of O(name) or O(id) is required.
    type: str
  id:
    description:
      - The numeric id of the existing URL list to modify.
      - Exactly one of O(name) or O(id) is required.
    type: int
  urls:
    description:
      - The URL entries to add, remove, or reconcile against.
    type: list
    elements: str
    required: true
  state:
    description:
      - With V(present), ensure the given O(urls) are on the list.
      - With V(absent), ensure the given O(urls) are not on the list.
    type: str
    choices: [present, absent]
    default: present
  purge:
    description:
      - Only meaningful with O(state=present). When V(true), the list is
        reconciled to contain exactly O(urls), removing any other entries.
    type: bool
    default: false
"""

EXAMPLES = r"""
- name: Ensure two URLs are present on an existing list
  mlowcher61.netskope.netskope_urllist:
    name: Corp-Allowlist
    urls:
      - partner.example.com
      - vendor.example.com

- name: Make a list contain exactly these URLs (config as code)
  mlowcher61.netskope.netskope_urllist:
    id: 12
    state: present
    purge: true
    urls:
      - a.example.com
      - b.example.com

- name: Remove a URL from a list
  mlowcher61.netskope.netskope_urllist:
    name: Corp-Allowlist
    state: absent
    urls:
      - old.example.com
"""

RETURN = r"""
urllist:
  description: The URL list object after the change (predicted under check mode).
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)


def plan_urllist_changes(current, urls, state, purge):
    """Compute the change plan for a URL list's entries (pure, no I/O)."""
    urls = urls or []
    existing = list((current.get("data") or {}).get("urls") or [])
    existing_set = set(existing)
    desired_set = set(urls)

    if state == "present":
        to_add = [u for u in urls if u not in existing_set]
        # de-dup while preserving order of supplied urls
        seen = set()
        to_add = [u for u in to_add if not (u in seen or seen.add(u))]
        to_remove = [u for u in existing if u not in desired_set] if purge else []
    else:  # absent
        to_add = []
        to_remove = [u for u in existing if u in desired_set]

    remove_set = set(to_remove)
    result = [u for u in existing if u not in remove_set]
    for u in to_add:
        if u not in result:
            result.append(u)

    return {
        "changed": bool(to_add or to_remove),
        "to_add": to_add,
        "to_remove": to_remove,
        "result_urls": result,
        "before": {"urls": existing},
        "after": {"urls": result},
    }


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
        id=dict(type="int"),
        urls=dict(type="list", elements="str", required=True),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        purge=dict(type="bool", default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[["name", "id"]],
        mutually_exclusive=[["name", "id"]],
    )

    name = module.params["name"]
    list_id = module.params["id"]

    client = NetskopeClient(module)
    records = client.get_paginated("policy/urllist")
    if list_id is not None:
        current = find_record(records, lambda r: r.get("id") == list_id)
    else:
        current = find_record(records, lambda r: r.get("name") == name)

    if current is None:
        module.fail_json(
            msg="URL list %s was not found. This module can only modify entries "
            "on an existing list; the Netskope API cannot create URL lists. "
            "Create the list in the UI first." % (name if name is not None else list_id)
        )

    plan = plan_urllist_changes(
        current, module.params["urls"], module.params["state"], module.params["purge"]
    )
    diff = {"before": plan["before"], "after": plan["after"]}

    if not plan["changed"]:
        module.exit_json(changed=False, urllist=current, diff=diff)

    predicted = dict(current)
    predicted["data"] = dict(current.get("data") or {}, urls=plan["result_urls"])

    if module.check_mode:
        module.exit_json(changed=True, urllist=predicted, diff=diff)

    payload = {
        "name": current.get("name"),
        "data": dict(current.get("data") or {}, urls=plan["result_urls"]),
    }
    updated = client.request("PUT", "policy/urllist/%s" % current["id"], data=payload)
    module.exit_json(changed=True, urllist=updated or predicted, diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
