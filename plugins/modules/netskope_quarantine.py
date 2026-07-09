#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_quarantine
short_description: Release or delete a file held in Netskope quarantine
version_added: "0.3.0"
description:
  - Take action on a quarantined file via the legacy
    C(GET /api/v1/quarantine?op=take-action) endpoint. V(allow) restores the
    original file for the user; V(block) permanently deletes it.
  - Quarantine management has no REST API v2 equivalent, so this module
    authenticates with the v1 token (see O(api_v1_token)).
  - The module is idempotent by membership. It first lists the quarantine
    with C(op=get-files); when O(file_id) is no longer quarantined the task
    reports ok (unchanged). Because both actions remove the file from
    quarantine, the module cannot verify that a previously taken action was
    the same one requested now.
  - Use C(mlowcher61.netskope.netskope_quarantine_info) to discover file ids.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope.v1
options:
  file_id:
    description:
      - The id of the quarantined file to act on, as reported by
        C(mlowcher61.netskope.netskope_quarantine_info) or a quarantine alert.
    type: str
    required: true
  quarantine_profile_id:
    description:
      - The id of the quarantine profile holding the file.
      - When omitted, it is resolved automatically from the quarantine
        listing; supply it to disambiguate if the same file id ever appears
        under more than one profile.
    type: str
  action:
    description:
      - V(allow) releases the file back to the user (restores the original).
      - V(block) permanently deletes the quarantined file.
    type: str
    choices: [allow, block]
    required: true
"""

EXAMPLES = r"""
- name: Release a quarantined file back to the user
  mlowcher61.netskope.netskope_quarantine:
    file_id: "9c29fd7ae2b4dbb4"
    action: allow

- name: Permanently delete a quarantined file from a specific profile
  mlowcher61.netskope.netskope_quarantine:
    file_id: "9c29fd7ae2b4dbb4"
    quarantine_profile_id: "1"
    action: block
"""

RETURN = r"""
file:
  description:
    - The quarantine record the action was applied to.
    - Empty when the file was not found in quarantine (nothing to do).
  returned: success
  type: dict
  sample:
    file_id: "9c29fd7ae2b4dbb4"
    original_file_name: report.docx
    quarantine_profile_id: "1"
    quarantine_profile_name: DefaultQuarantineProfile
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeV1Client,
    find_record,
    flatten_quarantined_files,
    netskope_v1_argument_spec,
)

QUARANTINE_PATH = "quarantine"


def find_quarantined_file(files, file_id, quarantine_profile_id):
    """Locate the quarantined file this task should act on (pure, no I/O).

    Returns the matching record or None. Absence means the file has already
    been released or blocked (or never existed), which the module treats as
    nothing-to-do so that replayed tasks stay idempotent.
    """
    def match(record):
        if record.get("file_id") != file_id:
            return False
        if quarantine_profile_id is not None and str(
            record.get("quarantine_profile_id")
        ) != str(quarantine_profile_id):
            return False
        return True

    return find_record(files, match)


def run_module():
    argument_spec = netskope_v1_argument_spec()
    argument_spec.update(
        file_id=dict(type="str", required=True),
        quarantine_profile_id=dict(type="str"),
        action=dict(type="str", required=True, choices=["allow", "block"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    file_id = module.params["file_id"]
    quarantine_profile_id = module.params["quarantine_profile_id"]
    action = module.params["action"]

    client = NetskopeV1Client(module)
    payload = client.request("GET", QUARANTINE_PATH, params={"op": "get-files"})
    current = find_quarantined_file(
        flatten_quarantined_files(payload), file_id, quarantine_profile_id
    )

    if current is None:
        module.exit_json(
            changed=False,
            file={},
            msg="File %s is not in quarantine; assuming the action was "
                "already taken." % file_id,
            diff={"before": {}, "after": {}},
        )

    diff = {"before": current, "after": {}}
    if module.check_mode:
        module.exit_json(changed=True, file=current, diff=diff)

    client.request(
        "GET",
        QUARANTINE_PATH,
        params={
            "op": "take-action",
            "action": action,
            "file_id": file_id,
            "quarantine_profile_id": (
                quarantine_profile_id or current.get("quarantine_profile_id")
            ),
        },
    )
    module.exit_json(changed=True, file=current, diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
