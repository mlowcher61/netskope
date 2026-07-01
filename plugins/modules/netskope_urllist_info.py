#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_urllist_info
short_description: Retrieve Netskope URL lists
version_added: "0.1.0"
description:
  - Gather information about URL lists defined in a Netskope tenant via the
    C(GET /api/v2/policy/urllist) endpoint.
  - This is a read-only module and never changes tenant state.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - Restrict the result to the URL list with this exact name.
      - When omitted, every URL list is returned.
    type: str
  id:
    description:
      - Restrict the result to the URL list with this numeric id.
      - When omitted, every URL list is returned.
    type: int
  fields:
    description:
      - An optional list of top-level field names to keep for each URL list.
      - When omitted, every field returned by the API is included.
    type: list
    elements: str
"""

EXAMPLES = r"""
- name: Retrieve all URL lists
  mlowcher61.netskope.netskope_urllist_info:
    tenant_url: https://acme.goskope.com
    api_token: "{{ netskope_api_token }}"
  register: all_lists

- name: Retrieve a single URL list by name, keeping only id and name
  mlowcher61.netskope.netskope_urllist_info:
    provider:
      tenant_url: https://acme.goskope.com
      api_token: "{{ netskope_api_token }}"
    name: Corporate-Allowlist
    fields:
      - id
      - name
  register: allowlist

- name: Retrieve URL lists using environment-injected credentials (AAP custom credential)
  mlowcher61.netskope.netskope_urllist_info:
  register: lists
"""

RETURN = r"""
urllists:
  description: The list of URL lists matching the requested filters.
  returned: success
  type: list
  elements: dict
  sample:
    - id: 12
      name: Corporate-Allowlist
      data:
        urls:
          - example.com
          - internal.acme.com
        type: exact
count:
  description: The number of URL lists returned.
  returned: success
  type: int
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
)


def filter_records(records, name, record_id):
    """Filter the URL lists client-side by name and/or id."""
    filtered = records
    if name is not None:
        filtered = [r for r in filtered if r.get("name") == name]
    if record_id is not None:
        filtered = [r for r in filtered if r.get("id") == record_id]
    return filtered


def filter_fields(records, fields):
    """Project each URL list down to the requested top-level fields.

    TODO (learning-mode contribution): implement this.

    Given ``records`` (a list of URL-list dicts) and ``fields`` (a list of
    top-level key names, or None), return a new list where each record contains
    only the requested keys. Decide the semantics that make sense for an
    operator, for example:
      - When ``fields`` is None or empty, return the records unchanged.
      - Should a requested field that is missing from a record be skipped, or
        included as null?
      - Should identifying fields like ``id``/``name`` always be preserved?

    The current placeholder is a no-op so the module runs; replace it.
    """
    if not fields:
        return records
    return records  # <-- replace with your projection logic


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
        id=dict(type="int"),
        fields=dict(type="list", elements="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = NetskopeClient(module)
    records = client.get_paginated("policy/urllist")
    records = filter_records(records, module.params["name"], module.params["id"])
    records = filter_fields(records, module.params["fields"])

    module.exit_json(changed=False, urllists=records, count=len(records))


def main():
    run_module()


if __name__ == "__main__":
    main()
