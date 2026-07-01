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
    netskope_publisher_info as mod,
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


PUBLISHERS = [
    {"publisher_id": 42, "publisher_name": "dc1-publisher-01", "status": "connected"},
    {"publisher_id": 43, "publisher_name": "dc2-publisher-01", "status": "disconnected"},
]


# ---------------------------------------------------------------------------
# extract_publishers() - tolerate the various response envelopes
# ---------------------------------------------------------------------------

def test_extract_from_data_dict_with_publishers_key():
    payload = {"data": {"publishers": PUBLISHERS}}
    assert mod.extract_publishers(payload) == PUBLISHERS


def test_extract_from_data_list():
    payload = {"data": PUBLISHERS}
    assert mod.extract_publishers(payload) == PUBLISHERS


def test_extract_from_bare_list():
    assert mod.extract_publishers(PUBLISHERS) == PUBLISHERS


def test_extract_missing_data_returns_empty_list():
    assert mod.extract_publishers({"data": {}}) == []
    assert mod.extract_publishers({}) == []


# ---------------------------------------------------------------------------
# filter_publishers() - client-side name/id filtering
# ---------------------------------------------------------------------------

def test_no_filters_returns_all():
    assert mod.filter_publishers(PUBLISHERS, None, None) == PUBLISHERS


def test_filter_by_name():
    result = mod.filter_publishers(PUBLISHERS, "dc1-publisher-01", None)
    assert len(result) == 1
    assert result[0]["publisher_id"] == 42


def test_filter_by_id():
    result = mod.filter_publishers(PUBLISHERS, None, 43)
    assert len(result) == 1
    assert result[0]["publisher_name"] == "dc2-publisher-01"


def test_filter_by_name_and_id_together():
    # Both must match the same record.
    assert mod.filter_publishers(PUBLISHERS, "dc1-publisher-01", 43) == []
    result = mod.filter_publishers(PUBLISHERS, "dc1-publisher-01", 42)
    assert len(result) == 1


def test_filter_no_match_returns_empty():
    assert mod.filter_publishers(PUBLISHERS, "nope", None) == []


# ---------------------------------------------------------------------------
# main() - end-to-end wiring with the client mocked out
# ---------------------------------------------------------------------------

def test_returns_all_publishers_by_default():
    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "t"}), \
            patch.object(mod.NetskopeClient, "request",
                         return_value={"data": {"publishers": PUBLISHERS}}), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["changed"] is False
    assert result["count"] == 2
    assert result["publishers"] == PUBLISHERS


def test_name_filter_applied_end_to_end():
    with module_args({
        "tenant_url": "https://acme.goskope.com",
        "api_token": "t",
        "name": "dc2-publisher-01",
    }), \
            patch.object(mod.NetskopeClient, "request",
                         return_value={"data": {"publishers": PUBLISHERS}}), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson) as exc:
            mod.main()
    result = exc.value.args[0]
    assert result["count"] == 1
    assert result["publishers"][0]["publisher_id"] == 43


def test_hits_the_publishers_endpoint():
    seen = {}

    def fake(method, path, **kwargs):
        seen["method"] = method
        seen["path"] = path
        return {"data": {"publishers": []}}

    with module_args({"tenant_url": "https://acme.goskope.com", "api_token": "t"}), \
            patch.object(mod.NetskopeClient, "request", side_effect=fake), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        with pytest.raises(AnsibleExitJson):
            mod.main()
    assert seen["method"] == "GET"
    assert seen["path"] == "infrastructure/publishers"
