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
    netskope_scim_group as mod,
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


GROUP = {"id": "g-1", "displayName": "Engineering", "externalId": "ext-9",
         "members": [{"value": "u-1"}, {"value": "u-2"}]}


# --- plan_scim_group_changes() ---------------------------------------------

def test_absent_existing_group_deletes():
    plan = mod.plan_scim_group_changes(GROUP, "Engineering", None, [], "absent", False)
    assert plan["changed"] is True
    assert plan["action"] == "delete"


def test_absent_missing_group_is_noop():
    plan = mod.plan_scim_group_changes(None, "Engineering", None, [], "absent", False)
    assert plan["changed"] is False
    assert plan["action"] == "none"


def test_present_missing_group_creates_with_members():
    plan = mod.plan_scim_group_changes(None, "Engineering", "ext-9", ["u-1"], "present", False)
    assert plan["changed"] is True
    assert plan["action"] == "create"
    assert plan["members_to_add"] == ["u-1"]


def test_present_adds_missing_member_only():
    plan = mod.plan_scim_group_changes(GROUP, "Engineering", None, ["u-2", "u-3"], "present", False)
    assert plan["action"] == "patch"
    assert plan["members_to_add"] == ["u-3"]
    assert plan["members_to_remove"] == []


def test_present_idempotent_when_members_match():
    plan = mod.plan_scim_group_changes(GROUP, "Engineering", None, ["u-1"], "present", False)
    assert plan["changed"] is False
    assert plan["action"] == "none"


def test_present_purge_removes_extra_members():
    plan = mod.plan_scim_group_changes(GROUP, "Engineering", None, ["u-1"], "present", True)
    assert plan["action"] == "patch"
    assert plan["members_to_remove"] == ["u-2"]
    assert plan["members_to_add"] == []


# --- build_patch_ops() -----------------------------------------------------

def test_build_patch_ops_add_and_remove():
    ops = mod.build_patch_ops(["u-3"], ["u-2"])
    assert {"op": "add", "path": "members",
            "value": [{"value": "u-3"}]} in ops
    assert {"op": "remove", "path": 'members[value eq "u-2"]'} in ops


def test_build_patch_ops_empty():
    assert mod.build_patch_ops([], []) == []


# --- run_module() wiring ---------------------------------------------------

def _run(args, groups):
    with module_args(dict({"tenant_url": "https://acme.goskope.com",
                           "api_token": "t"}, **args)), \
            patch.object(mod.NetskopeClient, "get_scim_paginated",
                         return_value=groups), \
            patch.object(mod.NetskopeClient, "request") as req, \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        try:
            mod.main()
        except AnsibleExitJson as exc:
            return exc.args[0], req
    raise AssertionError("module did not exit")


def test_create_posts_new_group():
    result, req = _run({"display_name": "New", "members": ["u-9"]}, [])
    assert result["changed"] is True
    assert req.call_args[0][0] == "POST"
    assert req.call_args[0][1] == "scim/Groups"
    assert req.call_args[1]["data"]["displayName"] == "New"


def test_delete_calls_delete():
    result, req = _run({"display_name": "Engineering", "state": "absent"}, [GROUP])
    assert result["changed"] is True
    assert req.call_args[0][0] == "DELETE"
    assert req.call_args[0][1] == "scim/Groups/g-1"


def test_patch_adds_member():
    result, req = _run({"display_name": "Engineering", "members": ["u-1", "u-3"]}, [GROUP])
    assert result["changed"] is True
    assert req.call_args[0][0] == "PATCH"
    assert req.call_args[0][1] == "scim/Groups/g-1"
    ops = req.call_args[1]["data"]["Operations"]
    assert ops == [{"op": "add", "path": "members", "value": [{"value": "u-3"}]}]


def test_no_change_skips_request():
    result, req = _run({"display_name": "Engineering", "members": ["u-1"]}, [GROUP])
    assert result["changed"] is False
    req.assert_not_called()


def test_check_mode_skips_request():
    result, req = _run(
        {"display_name": "Engineering", "members": ["u-1", "u-3"],
         "_ansible_check_mode": True},
        [GROUP],
    )
    assert result["changed"] is True
    req.assert_not_called()
