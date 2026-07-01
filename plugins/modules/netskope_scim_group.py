#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_scim_group
short_description: Manage a Netskope SCIM group and its membership
version_added: "0.2.0"
description:
  - Create, delete, and manage the membership of a SCIM 2.0 group via the
    C(scim/Groups) endpoints.
  - Members are given as SCIM user ids (the C(value) of a member entry). Use
    M(mlowcher61.netskope.netskope_scim_info) to discover user ids.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  display_name:
    description:
      - The SCIM group displayName; used to locate or create the group.
    type: str
    required: true
  external_id:
    description:
      - The SCIM externalId to set when creating the group.
    type: str
  members:
    description:
      - SCIM user ids to reconcile as members of the group.
    type: list
    elements: str
    default: []
  state:
    description:
      - With V(present), ensure the group exists and O(members) are members.
      - With V(absent), delete the group (O(members) is ignored).
    type: str
    choices: [present, absent]
    default: present
  purge:
    description:
      - Only meaningful with O(state=present). When V(true), the membership is
        reconciled to exactly O(members), removing any other members.
    type: bool
    default: false
"""

EXAMPLES = r"""
- name: Ensure a SCIM group exists with two members
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    external_id: eng-okta-001
    members:
      - 3f2a-user-id-1
      - 7b9c-user-id-2

- name: Reconcile group membership exactly (config as code)
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    state: present
    purge: true
    members:
      - 3f2a-user-id-1

- name: Delete a SCIM group
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    state: absent
"""

RETURN = r"""
scim_group:
  description: The SCIM group object after the change (predicted under check mode).
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)

SCIM_GROUPS_PATH = "scim/Groups"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"


def _member_ids(group):
    return [m.get("value") for m in (group.get("members") or []) if m.get("value")]


def plan_scim_group_changes(current, display_name, external_id, members, state, purge):
    """Compute the change plan for a SCIM group (pure, no I/O)."""
    members = members or []
    desired_set = set(members)

    if state == "absent":
        changed = current is not None
        return {
            "changed": changed,
            "action": "delete" if changed else "none",
            "members_to_add": [],
            "members_to_remove": [],
            "before": current or {},
            "after": {} if changed else (current or {}),
        }

    if current is None:
        seen = set()
        add = [m for m in members if not (m in seen or seen.add(m))]
        after = {"displayName": display_name, "members": add}
        if external_id is not None:
            after["externalId"] = external_id
        return {
            "changed": True,
            "action": "create",
            "members_to_add": add,
            "members_to_remove": [],
            "before": {},
            "after": after,
        }

    existing = _member_ids(current)
    existing_set = set(existing)
    to_add = [m for m in members if m not in existing_set]
    seen = set()
    to_add = [m for m in to_add if not (m in seen or seen.add(m))]
    to_remove = [m for m in existing if m not in desired_set] if purge else []

    remove_set = set(to_remove)
    result = [m for m in existing if m not in remove_set]
    for m in to_add:
        if m not in result:
            result.append(m)

    changed = bool(to_add or to_remove)
    return {
        "changed": changed,
        "action": "patch" if changed else "none",
        "members_to_add": to_add,
        "members_to_remove": to_remove,
        "before": {"members": existing},
        "after": {"members": result},
    }


def build_patch_ops(members_to_add, members_to_remove):
    """Build SCIM 2.0 PatchOp Operations for member add/remove."""
    ops = []
    if members_to_add:
        ops.append({
            "op": "add",
            "path": "members",
            "value": [{"value": m} for m in members_to_add],
        })
    for m in members_to_remove:
        ops.append({"op": "remove", "path": 'members[value eq "%s"]' % m})
    return ops


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        display_name=dict(type="str", required=True),
        external_id=dict(type="str"),
        members=dict(type="list", elements="str", default=[]),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        purge=dict(type="bool", default=False),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    display_name = module.params["display_name"]
    external_id = module.params["external_id"]

    client = NetskopeClient(module)
    groups = client.get_scim_paginated(
        SCIM_GROUPS_PATH,
        params={"filter": 'displayName eq "%s"' % display_name},
    )
    current = find_record(groups, lambda g: g.get("displayName") == display_name)

    plan = plan_scim_group_changes(
        current, display_name, external_id,
        module.params["members"], module.params["state"], module.params["purge"],
    )
    diff = {"before": plan["before"], "after": plan["after"]}

    if not plan["changed"]:
        module.exit_json(changed=False, scim_group=current or {}, diff=diff)

    if module.check_mode:
        module.exit_json(changed=True, scim_group=plan["after"], diff=diff)

    action = plan["action"]
    if action == "create":
        body = {
            "schemas": [GROUP_SCHEMA],
            "displayName": display_name,
            "members": [{"value": m} for m in plan["members_to_add"]],
        }
        if external_id is not None:
            body["externalId"] = external_id
        result = client.request("POST", SCIM_GROUPS_PATH, data=body)
        module.exit_json(changed=True, scim_group=result or body, diff=diff)
    elif action == "delete":
        client.request("DELETE", "%s/%s" % (SCIM_GROUPS_PATH, current["id"]))
        module.exit_json(changed=True, scim_group={}, diff=diff)
    else:  # patch
        body = {
            "schemas": [PATCH_SCHEMA],
            "Operations": build_patch_ops(
                plan["members_to_add"], plan["members_to_remove"]
            ),
        }
        result = client.request(
            "PATCH", "%s/%s" % (SCIM_GROUPS_PATH, current["id"]), data=body
        )
        module.exit_json(changed=True, scim_group=result or plan["after"], diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
