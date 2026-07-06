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
    netskope_quarantine_info as mod,
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


PAYLOAD = {
    "status": "success",
    "data": {
        "quarantined": [
            {
                "quarantine_profile_id": "1",
                "quarantine_profile_name": "DefaultQuarantineProfile",
                "files": [
                    {"file_id": "f1", "original_file_name": "a.docx", "policy": "dlp-pci"},
                    {"file_id": "f2", "original_file_name": "b.xlsx", "policy": "dlp-phi"},
                ],
            },
            {
                "quarantine_profile_id": "2",
                "quarantine_profile_name": "LegalHold",
                "files": [
                    {"file_id": "f3", "original_file_name": "c.pdf", "policy": "legal"},
                ],
            },
        ]
    },
}


# --- flatten_quarantined_files() ---------------------------------------------

def test_flatten_annotates_profile_details():
    files = mod.flatten_quarantined_files(PAYLOAD)
    assert [f["file_id"] for f in files] == ["f1", "f2", "f3"]
    assert files[0]["quarantine_profile_id"] == "1"
    assert files[0]["quarantine_profile_name"] == "DefaultQuarantineProfile"
    assert files[2]["quarantine_profile_name"] == "LegalHold"


def test_flatten_tolerates_empty_and_malformed_payloads():
    assert mod.flatten_quarantined_files({}) == []
    assert mod.flatten_quarantined_files({"data": {}}) == []
    assert mod.flatten_quarantined_files({"data": {"quarantined": []}}) == []
    assert mod.flatten_quarantined_files({"data": {"quarantined": [{"files": None}]}}) == []
    assert mod.flatten_quarantined_files(None) == []


# --- filter_files() ----------------------------------------------------------

def test_filter_by_profile_id():
    files = mod.flatten_quarantined_files(PAYLOAD)
    assert [f["file_id"] for f in mod.filter_files(files, "2", None)] == ["f3"]


def test_filter_by_file_id():
    files = mod.flatten_quarantined_files(PAYLOAD)
    assert [f["file_id"] for f in mod.filter_files(files, None, "f2")] == ["f2"]


def test_filter_none_returns_all():
    files = mod.flatten_quarantined_files(PAYLOAD)
    assert mod.filter_files(files, None, None) == files


# --- run_module() wiring -----------------------------------------------------

def _run(args):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path, kwargs.get("params")))
        return PAYLOAD

    with module_args(dict({"tenant_url": "https://acme.goskope.com",
                           "api_v1_token": "v1tok"}, **args)), \
            patch.object(mod.NetskopeV1Client, "request", fake_request), \
            patch.object(basic.AnsibleModule, "exit_json", exit_json), \
            patch.object(basic.AnsibleModule, "fail_json", fail_json):
        try:
            mod.main()
        except AnsibleExitJson as exc:
            return exc.args[0], calls
    raise AssertionError("module did not exit")


def test_lists_all_files():
    result, calls = _run({})
    assert result["changed"] is False
    assert result["count"] == 3
    assert calls == [("GET", "quarantine",
                      {"op": "get-files", "starttime": None, "endtime": None})]


def test_time_window_is_passed_through():
    result, calls = _run({"start_time": 100, "end_time": 200})
    assert calls[0][2] == {"op": "get-files", "starttime": 100, "endtime": 200}


def test_profile_filter_applies():
    result, _ = _run({"quarantine_profile_id": "1"})
    assert result["count"] == 2
    assert all(f["quarantine_profile_id"] == "1" for f in result["files"])
