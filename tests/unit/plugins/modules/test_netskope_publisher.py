# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import contextlib
import json

from unittest.mock import patch

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

from ansible_collections.mlowcher61.netskope.plugins.modules import (
    netskope_publisher as mod,
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


PUBLISHER = {"publisher_id": 42, "publisher_name": "dc1-pub-01",
             "lbrokerconnect": False, "status": "connected"}


# --- plan_publisher_changes() -----------------------------------------------

def test_absent_existing_publisher_deletes():
    plan = mod.plan_publisher_changes(PUBLISHER, "dc1-pub-01", None, "absent")
    assert plan["changed"] is True
    assert plan["action"] == "delete"


def test_absent_missing_publisher_is_noop():
    plan = mod.plan_publisher_changes(None, "dc1-pub-01", None, "absent")
    assert plan["changed"] is False
    assert plan["action"] == "none"


def test_present_missing_publisher_creates():
    plan = mod.plan_publisher_changes(None, "new-pub", True, "present")
    assert plan["changed"] is True
    assert plan["action"] == "create"
    assert plan["after"] == {"publisher_name": "new-pub", "lbrokerconnect": True}


def test_present_existing_publisher_is_idempotent():
    plan = mod.plan_publisher_changes(PUBLISHER, "dc1-pub-01", None, "present")
    assert plan["changed"] is False
    assert plan["action"] == "none"


def test_present_matching_attribute_is_idempotent():
    plan = mod.plan_publisher_changes(PUBLISHER, "dc1-pub-01", False, "present")
    assert plan["changed"] is False


def test_present_changed_attribute_updates():
    plan = mod.plan_publisher_changes(PUBLISHER, "dc1-pub-01", True, "present")
    assert plan["changed"] is True
    assert plan["action"] == "update"
    assert plan["after"]["lbrokerconnect"] is True


# --- extract_publishers() ----------------------------------------------------

def test_extract_publishers_nested_and_flat():
    assert mod.extract_publishers({"data": {"publishers": [PUBLISHER]}}) == [PUBLISHER]
    assert mod.extract_publishers({"data": [PUBLISHER]}) == [PUBLISHER]
    assert mod.extract_publishers({}) == []


# --- run_module() wiring -----------------------------------------------------

def _run(args, publishers, write_responses=None):
    calls = []
    responses = list(write_responses or [])

    def fake_request(self, method, path, **kwargs):
        if method == "GET" and path == mod.PUBLISHERS_PATH:
            return {"data": {"publishers": publishers}}
        calls.append((method, path, kwargs.get("data")))
        return responses.pop(0) if responses else {}

    with module_args(dict({"tenant_url": "https://acme.goskope.com",
                           "api_token": "t"}, **args)), \
            patch.object(mod.NetskopeClient, "request", fake_request), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        try:
            mod.main()
        except AnsibleExitJson as exc:
            return exc.args[0], calls
    raise AssertionError("module did not exit")


def test_create_posts_new_publisher():
    result, calls = _run(
        {"name": "new-pub"}, [],
        write_responses=[{"data": {"publisher_id": 7, "publisher_name": "new-pub"}}],
    )
    assert result["changed"] is True
    assert calls == [("POST", "infrastructure/publishers", {"name": "new-pub"})]
    assert result["publisher"]["publisher_id"] == 7


def test_delete_calls_delete():
    result, calls = _run({"name": "dc1-pub-01", "state": "absent"}, [PUBLISHER])
    assert result["changed"] is True
    assert calls == [("DELETE", "infrastructure/publishers/42", None)]


def test_update_patches_attribute():
    result, calls = _run({"name": "dc1-pub-01", "lbrokerconnect": True}, [PUBLISHER])
    assert result["changed"] is True
    assert calls == [("PATCH", "infrastructure/publishers/42",
                      {"name": "dc1-pub-01", "lbrokerconnect": True})]


def test_no_change_skips_writes():
    result, calls = _run({"name": "dc1-pub-01"}, [PUBLISHER])
    assert result["changed"] is False
    assert calls == []


def test_check_mode_skips_writes():
    result, calls = _run({"name": "new-pub", "_ansible_check_mode": True}, [])
    assert result["changed"] is True
    assert calls == []


def test_generate_token_on_existing_publisher():
    result, calls = _run(
        {"name": "dc1-pub-01", "generate_token": True}, [PUBLISHER],
        write_responses=[{"data": {"token": "reg-token-xyz"}}],
    )
    assert result["changed"] is True
    assert result["token"] == "reg-token-xyz"
    assert calls == [("POST", "infrastructure/publishers/42/registration_token", None)]


def test_generate_token_after_create_uses_new_id():
    result, calls = _run(
        {"name": "new-pub", "generate_token": True}, [],
        write_responses=[
            {"data": {"publisher_id": 7, "publisher_name": "new-pub"}},
            {"data": {"token": "reg-token-new"}},
        ],
    )
    assert result["token"] == "reg-token-new"
    assert calls[1] == ("POST", "infrastructure/publishers/7/registration_token", None)
