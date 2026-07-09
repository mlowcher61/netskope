#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_quarantine_info
short_description: List files held in Netskope quarantine
version_added: "0.3.0"
description:
  - Gather the files currently held in Netskope quarantine via the legacy
    C(GET /api/v1/quarantine?op=get-files) endpoint.
  - Quarantine management has no REST API v2 equivalent, so this module
    authenticates with the v1 token (see O(api_v1_token)).
  - This is a read-only module and never changes tenant state.
  - Use C(mlowcher61.netskope.netskope_quarantine) to release (allow) or
    delete (block) a quarantined file.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope.v1
options:
  quarantine_profile_id:
    description:
      - Restrict the result to files held under this quarantine profile id.
    type: str
  file_id:
    description:
      - Restrict the result to the file with this exact id.
    type: str
  start_time:
    description:
      - Only return files quarantined at or after this Unix epoch time.
    type: int
  end_time:
    description:
      - Only return files quarantined at or before this Unix epoch time.
    type: int
"""

EXAMPLES = r"""
- name: List every quarantined file
  mlowcher61.netskope.netskope_quarantine_info:
  register: quarantine

- name: List files quarantined under one profile in the last day
  mlowcher61.netskope.netskope_quarantine_info:
    quarantine_profile_id: "1"
    start_time: "{{ (now(utc=true).timestamp() | int) - 86400 }}"
  register: recent
"""

RETURN = r"""
files:
  description:
    - The quarantined files matching the requested filters.
    - Each file is annotated with the C(quarantine_profile_id) and
      C(quarantine_profile_name) of the profile holding it.
  returned: success
  type: list
  elements: dict
  sample:
    - file_id: "9c29fd7ae2b4dbb4"
      original_file_name: report.docx
      policy: DLP-PCI
      quarantine_profile_id: "1"
      quarantine_profile_name: DefaultQuarantineProfile
count:
  description: The number of files returned.
  returned: success
  type: int
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeV1Client,
    flatten_quarantined_files,
    netskope_v1_argument_spec,
)

QUARANTINE_PATH = "quarantine"


def filter_files(files, quarantine_profile_id, file_id):
    """Filter quarantined files client-side by profile id and/or file id."""
    filtered = files
    if quarantine_profile_id is not None:
        filtered = [
            f for f in filtered
            if str(f.get("quarantine_profile_id")) == str(quarantine_profile_id)
        ]
    if file_id is not None:
        filtered = [f for f in filtered if f.get("file_id") == file_id]
    return filtered


def run_module():
    argument_spec = netskope_v1_argument_spec()
    argument_spec.update(
        quarantine_profile_id=dict(type="str"),
        file_id=dict(type="str"),
        start_time=dict(type="int"),
        end_time=dict(type="int"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = NetskopeV1Client(module)
    payload = client.request(
        "GET",
        QUARANTINE_PATH,
        params={
            "op": "get-files",
            "starttime": module.params["start_time"],
            "endtime": module.params["end_time"],
        },
    )
    files = filter_files(
        flatten_quarantined_files(payload),
        module.params["quarantine_profile_id"],
        module.params["file_id"],
    )
    module.exit_json(changed=False, files=files, count=len(files))


def main():
    run_module()


if __name__ == "__main__":
    main()
