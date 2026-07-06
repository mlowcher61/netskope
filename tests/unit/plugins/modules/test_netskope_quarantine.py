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
    netskope_quarantine as mod,
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


FILE_ONE = {"file_id": "f1", "original_file_name": "a.docx",
            "quarantine_profile_id": "1",
            "quarantine_profile_name": "DefaultQuarantineProfile"}
FILE_TWO = {"file_id": "f2", "original_file_name": "b.xlsx",
            "quarantine_profile_id": "2",
            "quarantine_profile_name": "LegalHold"}
FILES = [FILE_ONE, FILE_TWO]


# --- find_quarantined_file() -------------------------------------------------

def test_find_by_file_id():
    assert mod.find_quarantined_file(FILES, "f1", None) == FILE_ONE


def test_find_missing_file_returns_none():
    assert mod.find_quarantined_file(FILES, "nope", None) is None


def test_find_respects_profile_restriction():
    assert mod.find_quarantined_file(FILES, "f1", "2") is None
    assert mod.find_quarantined_file(FILES, "f1", "1") == FILE_ONE


def test_find_coerces_profile_id_types():
    record = dict(FILE_ONE, quarantine_profile_id=1)
    assert mod.find_quarantined_file([record], "f1", "1") == record


# --- run_module() wiring -----------------------------------------------------

def _payload(files_by_profile):
    quarantined = []
    for profile_id, files in files_by_profile.items():
        quarantined.append({
            "quarantine_profile_id": profile_id,
            "quarantine_profile_name": "profile-%s" % profile_id,
            "files": files,
        })
    return {"status": "success", "data": {"quarantined": quarantined}}


def _run(args, files_by_profile):
    calls = []

    def fake_request(self, method, path, **kwargs):
        params = kwargs.get("params") or {}
        calls.append((method, path, params))
        if params.get("op") == "get-files":
            return _payload(files_by_profile)
        return {"status": "success"}

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


def test_allow_takes_action():
    result, calls = _run(
        {"file_id": "f1", "action": "allow"},
        {"1": [{"file_id": "f1", "original_file_name": "a.docx"}]},
    )
    assert result["changed"] is True
    assert result["file"]["file_id"] == "f1"
    assert calls[1] == ("GET", "quarantine", {
        "op": "take-action", "action": "allow",
        "file_id": "f1", "quarantine_profile_id": "1",
    })


def test_block_passes_action_through():
    _, calls = _run(
        {"file_id": "f1", "action": "block"},
        {"1": [{"file_id": "f1"}]},
    )
    assert calls[1][2]["action"] == "block"


def test_explicit_profile_id_wins():
    _, calls = _run(
        {"file_id": "f1", "action": "allow", "quarantine_profile_id": "1"},
        {"1": [{"file_id": "f1"}]},
    )
    assert calls[1][2]["quarantine_profile_id"] == "1"


def test_missing_file_is_idempotent_noop():
    result, calls = _run({"file_id": "gone", "action": "allow"}, {"1": []})
    assert result["changed"] is False
    assert result["file"] == {}
    assert len(calls) == 1  # only the get-files lookup, no take-action


def test_check_mode_skips_take_action():
    result, calls = _run(
        {"file_id": "f1", "action": "block", "_ansible_check_mode": True},
        {"1": [{"file_id": "f1"}]},
    )
    assert result["changed"] is True
    assert len(calls) == 1
    assert result["diff"]["after"] == {}
