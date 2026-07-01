# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import contextlib
import json

import pytest

from unittest.mock import patch

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

from ansible_collections.mlowcher61.netskope.plugins.modules import (
    netskope_alert_info as mod,
)

try:
    from ansible.module_utils.testing import patch_module_args
except ImportError:  # pragma: no cover - older ansible-core (e.g. 2.16)
    patch_module_args = None


@contextlib.contextmanager
def module_args(args):
    if patch_module_args is not None:
        with patch_module_args(args):
            yield
    else:
        previous = basic._ANSIBLE_ARGS
        basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": args}))
        try:
            yield
        finally:
            basic._ANSIBLE_ARGS = previous


class AnsibleExitJson(Exception):
    pass


class AnsibleFailJson(Exception):
    pass


def exit_json(self, **kwargs):
    raise AnsibleExitJson(kwargs)


def fail_json(self, **kwargs):
    raise AnsibleFailJson(kwargs)


# ---------------------------------------------------------------------------
# build_query_params() - pure function, no AnsibleModule required
# ---------------------------------------------------------------------------

def test_default_window_uses_timeperiod():
    params = {
        "alert_type": None,
        "timeperiod": 3600,
        "start_time": None,
        "end_time": None,
        "query": None,
        "limit": 100,
    }
    result = mod.build_query_params(params)
    assert result == {"timeperiod": 3600, "limit": 100}


def test_explicit_window_overrides_timeperiod():
    params = {
        "alert_type": None,
        "timeperiod": 3600,
        "start_time": 1719792000,
        "end_time": 1719878400,
        "query": None,
        "limit": 100,
    }
    result = mod.build_query_params(params)
    assert result["starttime"] == 1719792000
    assert result["endtime"] == 1719878400
    assert "timeperiod" not in result


def test_alert_type_and_query_are_included_when_set():
    params = {
        "alert_type": "dlp",
        "timeperiod": 86400,
        "start_time": None,
        "end_time": None,
        "query": 'app eq "Dropbox"',
        "limit": 50,
    }
    result = mod.build_query_params(params)
    assert result["alert_type"] == "dlp"
    assert result["query"] == 'app eq "Dropbox"'
    assert result["timeperiod"] == 86400
    assert result["limit"] == 50


def test_empty_alert_type_and_query_are_omitted():
    params = {
        "alert_type": "",
        "timeperiod": 3600,
        "start_time": None,
        "end_time": None,
        "query": "",
        "limit": 100,
    }
    result = mod.build_query_params(params)
    assert "alert_type" not in result
    assert "query" not in result


# ---------------------------------------------------------------------------
# main() - end-to-end wiring with the client mocked out
# ---------------------------------------------------------------------------

ALERTS = [
    {"alert_type": "dlp", "app": "Dropbox", "user": "jdoe@example.com"},
    {"alert_type": "dlp", "app": "Box", "user": "asmith@example.com"},
]


def test_returns_alerts_and_count():
    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "t"}), \
            patch.object(mod.NetskopeClient, "get_paginated", return_value=ALERTS), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["changed"] is False
    assert result["count"] == 2
    assert result["alerts"] == ALERTS


def test_hits_the_alert_events_endpoint():
    seen = {}

    def fake(path, params=None):
        seen["path"] = path
        seen["params"] = params
        return []

    with module_args({
        "tenant_url": "https://acme.goskope.com",
        "api_token": "t",
        "alert_type": "malware",
        "timeperiod": 86400,
    }), \
            patch.object(mod.NetskopeClient, "get_paginated", side_effect=fake), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson):
            mod.main()
    assert seen["path"] == "events/data/alert"
    assert seen["params"]["alert_type"] == "malware"
    assert seen["params"]["timeperiod"] == 86400


def test_start_time_without_end_time_fails():
    with module_args({
        "tenant_url": "https://acme.goskope.com",
        "api_token": "t",
        "start_time": 1719792000,
    }), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleFailJson):
            mod.main()
