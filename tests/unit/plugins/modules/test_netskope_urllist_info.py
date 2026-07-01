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
    netskope_urllist_info as mod,
)

try:
    # ansible-core >= 2.19 requires a serialization profile; use the supported
    # context manager when it is available.
    from ansible.module_utils.testing import patch_module_args
except ImportError:  # pragma: no cover - older ansible-core (e.g. 2.16)
    patch_module_args = None


@contextlib.contextmanager
def module_args(args):
    """Inject module args in a way that works across ansible-core versions."""
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


SAMPLE = [
    {"id": 1, "name": "a", "data": {"urls": ["x.com"]}},
    {"id": 2, "name": "b", "data": {"urls": ["y.com"]}},
]


# --- pure helper: client-side filtering -----------------------------------

def test_filter_records_by_name():
    assert mod.filter_records(SAMPLE, "b", None) == [SAMPLE[1]]


def test_filter_records_by_id():
    assert mod.filter_records(SAMPLE, None, 1) == [SAMPLE[0]]


def test_filter_records_no_filter_returns_all():
    assert mod.filter_records(SAMPLE, None, None) == SAMPLE


@pytest.mark.xfail(reason="filter_fields is a pending learning-mode contribution", strict=False)
def test_filter_fields_projects_selected_keys():
    result = mod.filter_fields(SAMPLE, ["id", "name"])
    assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


# --- full module invocation ------------------------------------------------

def test_module_returns_all_lists():
    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "tok"}), \
            patch.object(mod.NetskopeClient, "get_paginated", return_value=SAMPLE), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["changed"] is False
    assert result["count"] == 2
    assert result["urllists"] == SAMPLE


def test_module_filters_by_name():
    args = {"tenant_url": "https://acme.goskope.com", "api_token": "tok", "name": "b"}
    with module_args(args), \
            patch.object(mod.NetskopeClient, "get_paginated", return_value=SAMPLE), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["count"] == 1
    assert result["urllists"][0]["name"] == "b"
