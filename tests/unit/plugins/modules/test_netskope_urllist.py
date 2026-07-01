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
    netskope_urllist as mod,
)

try:
    from ansible.module_utils.testing import patch_module_args
except ImportError:  # pragma: no cover - older ansible-core
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


CURRENT = {"id": 12, "name": "Corp-Allowlist",
           "data": {"urls": ["a.com", "b.com"], "type": "exact"}}


# --- plan_urllist_changes() ------------------------------------------------

def test_present_adds_missing_only():
    plan = mod.plan_urllist_changes(CURRENT, ["b.com", "c.com"], "present", False)
    assert plan["changed"] is True
    assert plan["to_add"] == ["c.com"]
    assert plan["to_remove"] == []
    assert plan["result_urls"] == ["a.com", "b.com", "c.com"]


def test_present_no_change_is_idempotent():
    plan = mod.plan_urllist_changes(CURRENT, ["a.com"], "present", False)
    assert plan["changed"] is False
    assert plan["result_urls"] == ["a.com", "b.com"]


def test_present_purge_reconciles_exactly():
    plan = mod.plan_urllist_changes(CURRENT, ["b.com", "c.com"], "present", True)
    assert plan["changed"] is True
    assert plan["to_add"] == ["c.com"]
    assert plan["to_remove"] == ["a.com"]
    assert plan["result_urls"] == ["b.com", "c.com"]


def test_absent_removes_supplied_only():
    plan = mod.plan_urllist_changes(CURRENT, ["a.com", "z.com"], "absent", False)
    assert plan["changed"] is True
    assert plan["to_remove"] == ["a.com"]
    assert plan["result_urls"] == ["b.com"]


def test_before_after_snapshots():
    plan = mod.plan_urllist_changes(CURRENT, ["c.com"], "present", False)
    assert plan["before"] == {"urls": ["a.com", "b.com"]}
    assert plan["after"] == {"urls": ["a.com", "b.com", "c.com"]}


# --- run_module() wiring ---------------------------------------------------

def _run(args):
    with module_args(dict({"tenant_url": "https://acme.goskope.com",
                           "api_token": "t"}, **args)), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with patch.object(mod.NetskopeClient, "get_paginated",
                          return_value=[CURRENT]), \
                patch.object(mod.NetskopeClient, "request") as req:
            try:
                mod.main()
            except AnsibleExitJson as exc:
                return "exit", exc.args[0], req
            except AnsibleFailJson as exc:
                return "fail", exc.args[0], req
    raise AssertionError("module did not exit")


def test_missing_list_fails():
    with module_args({"tenant_url": "https://acme.goskope.com",
                      "api_token": "t", "name": "nope", "urls": ["x.com"]}), \
            patch.object(mod.NetskopeClient, "get_paginated", return_value=[]), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleFailJson) as exc:
            mod.main()
    assert "cannot create URL lists" in exc.value.args[0]["msg"]


def test_no_change_reports_unchanged_and_skips_put():
    kind, result, req = _run({"name": "Corp-Allowlist", "urls": ["a.com"]})
    assert kind == "exit"
    assert result["changed"] is False
    req.assert_not_called()


def test_check_mode_predicts_change_without_put():
    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "t",
                      "name": "Corp-Allowlist", "urls": ["c.com"], "_ansible_check_mode": True}), \
            patch.object(mod.NetskopeClient, "get_paginated", return_value=[CURRENT]), \
            patch.object(mod.NetskopeClient, "request") as req, \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    assert exc.value.args[0]["changed"] is True
    assert exc.value.args[0]["urllist"]["data"]["urls"] == ["a.com", "b.com", "c.com"]
    req.assert_not_called()


def test_present_executes_put_with_reconciled_urls():
    kind, result, req = _run({"id": 12, "state": "present", "purge": True,
                              "urls": ["b.com", "c.com"]})
    assert kind == "exit"
    assert result["changed"] is True
    method, path = req.call_args[0][0], req.call_args[0][1]
    assert method == "PUT"
    assert path == "policy/urllist/12"
    assert req.call_args[1]["data"]["data"]["urls"] == ["b.com", "c.com"]
