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
    netskope_private_app as mod,
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


APP = {
    "app_id": 9,
    "app_name": "intranet-wiki",
    "host": "wiki.corp.example.com",
    "protocols": [{"type": "tcp", "port": "443"}],
    "publishers": [{"publisher_id": "42", "publisher_name": "dc1-pub-01"}],
    "use_publisher_dns": True,
}

PUBLISHER = {"publisher_id": 42, "publisher_name": "dc1-pub-01"}


# --- plan_private_app_changes() ----------------------------------------------

def test_absent_existing_app_deletes():
    plan = mod.plan_private_app_changes(APP, {"app_name": "intranet-wiki"}, "absent")
    assert plan["changed"] is True
    assert plan["action"] == "delete"


def test_absent_missing_app_is_noop():
    plan = mod.plan_private_app_changes(None, {"app_name": "x"}, "absent")
    assert plan["changed"] is False


def test_present_missing_app_creates():
    plan = mod.plan_private_app_changes(None, {"app_name": "new"}, "present")
    assert plan["action"] == "create"


def test_present_matching_app_is_idempotent():
    desired = {
        "app_name": "intranet-wiki",
        "host": "wiki.corp.example.com",
        "protocols": [{"type": "tcp", "port": "443"}],
        "publishers": [{"publisher_id": "42", "publisher_name": "dc1-pub-01"}],
        "use_publisher_dns": True,
    }
    plan = mod.plan_private_app_changes(APP, desired, "present")
    assert plan["changed"] is False


def test_present_host_order_and_spacing_is_idempotent():
    current = dict(APP, host="a.example.com, b.example.com")
    desired = {"app_name": "intranet-wiki", "host": "b.example.com,a.example.com"}
    plan = mod.plan_private_app_changes(current, desired, "present")
    assert plan["changed"] is False


def test_present_changed_field_updates():
    desired = {"app_name": "intranet-wiki", "use_publisher_dns": False}
    plan = mod.plan_private_app_changes(APP, desired, "present")
    assert plan["action"] == "update"
    assert plan["after"]["use_publisher_dns"] is False


def test_present_unspecified_fields_ignored():
    plan = mod.plan_private_app_changes(APP, {"app_name": "intranet-wiki"}, "present")
    assert plan["changed"] is False


def test_publisher_comparison_by_name():
    desired = {
        "app_name": "intranet-wiki",
        "publishers": [{"publisher_id": "999", "publisher_name": "dc1-pub-01"}],
    }
    plan = mod.plan_private_app_changes(APP, desired, "present")
    assert plan["changed"] is False


# --- desired_body() / build_update_body() -------------------------------------

def test_desired_body_full():
    params = {
        "name": "app1", "host": ["a.example.com", "b.example.com"],
        "real_host": None,
        "protocols": [{"type": "tcp", "port": "80,443"}],
        "publishers": ["dc1-pub-01"],
        "use_publisher_dns": False, "clientless_access": None,
        "trust_self_signed_certs": None, "tags": ["prod"],
    }
    body = mod.desired_body(params, {"dc1-pub-01": 42})
    assert body == {
        "app_name": "app1",
        "host": "a.example.com,b.example.com",
        "protocols": [{"type": "tcp", "port": "80,443"}],
        "publishers": [{"publisher_id": "42", "publisher_name": "dc1-pub-01"}],
        "use_publisher_dns": False,
        "tags": [{"tag_name": "prod"}],
    }


def test_build_update_body_merges_current():
    desired = {"app_name": "intranet-wiki", "use_publisher_dns": False}
    body = mod.build_update_body(APP, desired)
    assert body["use_publisher_dns"] is False
    assert body["host"] == "wiki.corp.example.com"
    assert body["publishers"] == APP["publishers"]


# --- run_module() wiring -------------------------------------------------------

def _run(args, apps, publishers=None, write_responses=None):
    calls = []
    responses = list(write_responses or [])

    def fake_request(self, method, path, **kwargs):
        if method == "GET" and path == mod.PRIVATE_APPS_PATH:
            return {"data": {"private_apps": apps}}
        if method == "GET" and path == mod.PUBLISHERS_PATH:
            return {"data": {"publishers": publishers or []}}
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


def test_create_posts_new_app():
    result, calls = _run(
        {"name": "new-app", "host": ["h.example.com"],
         "protocols": [{"type": "tcp", "port": "443"}],
         "publishers": ["dc1-pub-01"]},
        [], publishers=[PUBLISHER],
        write_responses=[{"data": {"app_id": 7, "app_name": "new-app"}}],
    )
    assert result["changed"] is True
    method, path, data = calls[0]
    assert (method, path) == ("POST", "steering/apps/private")
    assert data["host"] == "h.example.com"
    assert data["publishers"] == [{"publisher_id": "42",
                                   "publisher_name": "dc1-pub-01"}]


def test_create_without_host_fails():
    with pytest.raises(AnsibleFailJson) as exc:
        _run({"name": "new-app"}, [])
    assert "host and protocols" in exc.value.args[0]["msg"]


def test_unknown_publisher_fails():
    with pytest.raises(AnsibleFailJson) as exc:
        _run({"name": "new-app", "publishers": ["nope"]}, [], publishers=[PUBLISHER])
    assert "nope" in exc.value.args[0]["msg"]


def test_delete_calls_delete():
    result, calls = _run({"name": "intranet-wiki", "state": "absent"}, [APP])
    assert result["changed"] is True
    assert calls == [("DELETE", "steering/apps/private/9", None)]


def test_update_puts_merged_body():
    result, calls = _run(
        {"name": "intranet-wiki", "use_publisher_dns": False}, [APP],
    )
    method, path, data = calls[0]
    assert (method, path) == ("PUT", "steering/apps/private/9")
    assert data["use_publisher_dns"] is False
    assert data["host"] == "wiki.corp.example.com"


def test_no_change_skips_writes():
    result, calls = _run({"name": "intranet-wiki", "use_publisher_dns": True}, [APP])
    assert result["changed"] is False
    assert calls == []


def test_check_mode_skips_writes():
    result, calls = _run(
        {"name": "intranet-wiki", "use_publisher_dns": False,
         "_ansible_check_mode": True},
        [APP],
    )
    assert result["changed"] is True
    assert calls == []
