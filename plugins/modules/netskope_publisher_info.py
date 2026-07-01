#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_publisher_info
short_description: List Netskope Private Access publishers
version_added: "0.1.0"
description:
  - Gather Netskope Private Access (NPA) publishers and their health/status via
    the C(GET /api/v2/infrastructure/publishers) endpoint.
  - This is a read-only module and never changes tenant state.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - Restrict the result to the publisher with this exact name.
      - When omitted, every publisher is returned.
    type: str
  id:
    description:
      - Restrict the result to the publisher with this numeric id.
      - When omitted, every publisher is returned.
    type: int
"""

EXAMPLES = r"""
- name: List all Private Access publishers and their status
  mlowcher61.netskope.netskope_publisher_info:
  register: publishers

- name: Look up a single publisher by name
  mlowcher61.netskope.netskope_publisher_info:
    name: dc1-publisher-01
  register: publisher
"""

RETURN = r"""
publishers:
  description: The list of publishers matching the requested filters.
  returned: success
  type: list
  elements: dict
  sample:
    - publisher_id: 42
      publisher_name: dc1-publisher-01
      common_name: dc1-publisher-01
      status: connected
      registered: true
count:
  description: The number of publishers returned.
  returned: success
  type: int
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
)


def extract_publishers(payload):
    """Pull the publisher list out of the API response envelope.

    The endpoint may return the list directly under ``data`` or nested under
    ``data.publishers``.
    """
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return data.get("publishers", [])
    if isinstance(data, list):
        return data
    return []


def filter_publishers(publishers, name, publisher_id):
    """Filter publishers client-side by name and/or id."""
    filtered = publishers
    if name is not None:
        filtered = [p for p in filtered if p.get("publisher_name") == name]
    if publisher_id is not None:
        filtered = [p for p in filtered if p.get("publisher_id") == publisher_id]
    return filtered


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
        id=dict(type="int"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = NetskopeClient(module)
    payload = client.request("GET", "infrastructure/publishers")
    publishers = extract_publishers(payload)
    publishers = filter_publishers(
        publishers, module.params["name"], module.params["id"]
    )
    module.exit_json(changed=False, publishers=publishers, count=len(publishers))


def main():
    run_module()


if __name__ == "__main__":
    main()
