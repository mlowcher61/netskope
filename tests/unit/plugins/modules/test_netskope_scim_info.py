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
    netskope_scim_info as mod,
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


USERS = [{"id": "1", "userName": "jdoe"}, {"id": "2", "userName": "asmith"}]


def test_lists_users_by_default():
    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "t"}), \
            patch.object(mod.NetskopeClient, "get_scim_paginated", return_value=USERS), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["changed"] is False
    assert result["count"] == 2
    assert result["resources"] == USERS


def test_groups_use_the_groups_path():
    seen = {}

    def fake(path, params=None, count=100):
        seen["path"] = path
        return []

    with module_args({
        "tenant_url": "https://acme.goskope.com",
        "api_token": "t",
        "object_type": "groups",
    }), \
            patch.object(mod.NetskopeClient, "get_scim_paginated", side_effect=fake), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson):
            mod.main()
    assert seen["path"] == "scim/Groups"


def test_filter_is_passed_through():
    seen = {}

    def fake(path, params=None, count=100):
        seen["params"] = params
        return []

    with module_args({
        "tenant_url": "https://acme.goskope.com",
        "api_token": "t",
        "filter": 'userName eq "jdoe"',
    }), \
            patch.object(mod.NetskopeClient, "get_scim_paginated", side_effect=fake), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson):
            mod.main()
    assert seen["params"] == {"filter": 'userName eq "jdoe"'}
