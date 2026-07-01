#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_scim_info
short_description: List Netskope SCIM users or groups
version_added: "0.1.0"
description:
  - Gather SCIM users or groups from a Netskope tenant via the C(/api/v2/scim/)
    endpoints.
  - This is a read-only module and never changes tenant state.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  object_type:
    description:
      - Whether to list SCIM users or SCIM groups.
    type: str
    choices:
      - users
      - groups
    default: users
  filter:
    description:
      - An optional SCIM filter expression, for example C(userName eq "jdoe").
      - When omitted, every resource of the selected type is returned.
    type: str
  count:
    description:
      - The number of resources requested per page while paginating.
    type: int
    default: 100
"""

EXAMPLES = r"""
- name: List all SCIM users
  mlowcher61.netskope.netskope_scim_info:
    object_type: users
  register: scim_users

- name: Find a SCIM group by displayName
  mlowcher61.netskope.netskope_scim_info:
    object_type: groups
    filter: 'displayName eq "Engineering"'
  register: eng_group
"""

RETURN = r"""
resources:
  description: The list of SCIM resources returned.
  returned: success
  type: list
  elements: dict
  sample:
    - id: "abc123"
      userName: jdoe
      active: true
count:
  description: The number of resources returned.
  returned: success
  type: int
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
)

SCIM_PATHS = {
    "users": "scim/Users",
    "groups": "scim/Groups",
}


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        object_type=dict(type="str", choices=["users", "groups"], default="users"),
        filter=dict(type="str"),
        count=dict(type="int", default=100),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = NetskopeClient(module)
    path = SCIM_PATHS[module.params["object_type"]]
    params = {}
    if module.params["filter"]:
        params["filter"] = module.params["filter"]

    resources = client.get_scim_paginated(
        path, params=params, count=module.params["count"]
    )
    module.exit_json(changed=False, resources=resources, count=len(resources))


def main():
    run_module()


if __name__ == "__main__":
    main()
