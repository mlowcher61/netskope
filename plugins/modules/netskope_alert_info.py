#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_alert_info
short_description: Retrieve Netskope alerts
version_added: "0.1.0"
description:
  - Gather alert events from a Netskope tenant via the
    C(GET /api/v2/events/data/alert) endpoint.
  - Supports filtering by alert category (for example DLP, malware, policy) and
    by time window.
  - This is a read-only module and never changes tenant state.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  alert_type:
    description:
      - Restrict the results to a single alert category.
      - Common values include C(dlp), C(malware), C(policy), C(watchlist),
        C(ctep), C(uba), C(quarantine), C(remediation) and
        C(securityassessment). The exact set depends on the tenant.
    type: str
  timeperiod:
    description:
      - The look-back window in seconds. Ignored when both I(start_time) and
        I(end_time) are supplied.
      - Netskope accepts a fixed set of values, commonly 3600, 86400, 604800 and
        2592000.
    type: int
    default: 3600
  start_time:
    description:
      - The start of an explicit time window, as a Unix epoch timestamp.
      - Must be used together with I(end_time).
    type: int
  end_time:
    description:
      - The end of an explicit time window, as a Unix epoch timestamp.
      - Must be used together with I(start_time).
    type: int
  query:
    description:
      - A raw Netskope query/filter expression passed through unchanged.
    type: str
  limit:
    description:
      - The number of alerts requested per page while paginating.
    type: int
    default: 100
"""

EXAMPLES = r"""
- name: Retrieve DLP alerts from the last 24 hours
  mlowcher61.netskope.netskope_alert_info:
    alert_type: dlp
    timeperiod: 86400
  register: dlp_alerts

- name: Retrieve alerts in an explicit time window with a custom query
  mlowcher61.netskope.netskope_alert_info:
    start_time: 1719792000
    end_time: 1719878400
    query: 'app eq "Dropbox"'
  register: window_alerts
"""

RETURN = r"""
alerts:
  description: The list of alert events returned.
  returned: success
  type: list
  elements: dict
  sample:
    - alert_type: dlp
      app: Dropbox
      user: jdoe@example.com
      timestamp: 1719800000
count:
  description: The number of alerts returned.
  returned: success
  type: int
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
)


def build_query_params(params):
    """Translate module parameters into Netskope alert query parameters."""
    query = {}
    if params.get("start_time") is not None and params.get("end_time") is not None:
        query["starttime"] = params["start_time"]
        query["endtime"] = params["end_time"]
    else:
        query["timeperiod"] = params["timeperiod"]
    if params.get("alert_type"):
        query["alert_type"] = params["alert_type"]
    if params.get("query"):
        query["query"] = params["query"]
    query["limit"] = params["limit"]
    return query


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        alert_type=dict(type="str"),
        timeperiod=dict(type="int", default=3600),
        start_time=dict(type="int"),
        end_time=dict(type="int"),
        query=dict(type="str"),
        limit=dict(type="int", default=100),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_together=[["start_time", "end_time"]],
    )

    client = NetskopeClient(module)
    params = build_query_params(module.params)
    alerts = client.get_paginated("events/data/alert", params=params)
    module.exit_json(changed=False, alerts=alerts, count=len(alerts))


def main():
    run_module()


if __name__ == "__main__":
    main()
