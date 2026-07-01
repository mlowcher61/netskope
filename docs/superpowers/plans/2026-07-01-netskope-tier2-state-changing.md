# Netskope Tier 2 State-Changing Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the collection's first state-changing modules — `netskope_urllist` and `netskope_scim_group` — following one shared, check_mode + diff-capable, idempotent pattern.

**Architecture:** Each module splits into a pure, network-free **change planner** (fed a "current state" dict + desired params, returns a change plan with `changed`, add/remove sets, and before/after snapshots) plus a thin `run_module()` that GETs current state, calls the planner, honors `check_mode`, and executes the plan via `NetskopeClient.request()`. A shared `find_record()` helper in `module_utils` gives all modules one existence-check idiom.

**Tech Stack:** Ansible module (Python 2/6-compatible boilerplate, `AnsibleModule`), `NetskopeClient` on `open_url` (no third-party deps), pytest unit tests, `ansible-test sanity --docker`.

## Global Constraints

- Target Ansible Automation Platform / ansible-core; no third-party Python deps (must run in any EE). Copied from collection reference pattern.
- Every module file begins with the shebang + UTF-8 + GPLv3 header + `from __future__ import ...` / `__metaclass__ = type` boilerplate exactly as existing modules do.
- Credentials come from `netskope_argument_spec()`; modules `extends_documentation_fragment: mlowcher61.netskope.netskope`.
- All modules set `supports_check_mode=True` and must never call a write endpoint under `module.check_mode`.
- Semantic versioning from 0.1.0; new modules use `version_added: "0.2.0"`.
- `state` model (from spec): `state` acts on the most-specific thing the module owns (entries for urllist; the group for scim_group). `purge` always means "reconcile the managed set exactly". Default `purge=false`.
- **Scope note:** `netskope_steering_profile` is intentionally **excluded** from this plan — its exact v2 CRUD endpoint and `config` schema must be confirmed against the tenant Swagger first (spec Open Item #3). It gets its own plan once verified.
- **Test execution:** unit tests run under system `python3` (ansible-core 2.21 + pytest 9) with the collection rsync'd to an `ansible_collections/mlowcher61/netskope` root on `PYTHONPATH`; sanity runs via `ansible-test sanity --docker default --python 3.11`. See the `netskope-collection-test-workflow` memory for the exact rsync/PYTHONPATH steps. Commands below assume you are at the collection root inside that `ansible_collections` tree.

---

## Task 1: Shared `find_record()` helper

**Files:**
- Modify: `plugins/module_utils/netskope.py` (add a module-level function after the imports / before `netskope_argument_spec`)
- Test: `tests/unit/plugins/module_utils/test_netskope.py` (append)

**Interfaces:**
- Produces: `find_record(records, match) -> dict | None` — returns the first element of `records` for which `match(element)` is truthy, else `None`. `records` is a list of dicts; `match` is a callable taking one dict.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/plugins/module_utils/test_netskope.py`:

```python
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    find_record,
)


def test_find_record_returns_first_match():
    records = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert find_record(records, lambda r: r.get("name") == "b") == {"id": 2, "name": "b"}


def test_find_record_returns_none_when_absent():
    records = [{"id": 1}]
    assert find_record(records, lambda r: r.get("id") == 99) is None


def test_find_record_empty_list_returns_none():
    assert find_record([], lambda r: True) is None
```

(If a `find_record` import already exists at the top of the file, add these three test functions only.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/plugins/module_utils/test_netskope.py -k find_record -v`
Expected: FAIL — `ImportError: cannot import name 'find_record'`.

- [ ] **Step 3: Write minimal implementation**

In `plugins/module_utils/netskope.py`, add after the constants (before `def netskope_argument_spec`):

```python
def find_record(records, match):
    """Return the first record for which ``match(record)`` is truthy, else None.

    A small shared helper so every module resolves "does this resource already
    exist?" the same way against a list fetched from the API.
    """
    for record in records:
        if match(record):
            return record
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/plugins/module_utils/test_netskope.py -k find_record -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/module_utils/netskope.py tests/unit/plugins/module_utils/test_netskope.py
git commit -m "Add find_record helper for resource existence checks"
```

---

## Task 2: `netskope_urllist` module

**Files:**
- Create: `plugins/modules/netskope_urllist.py`
- Test: `tests/unit/plugins/modules/test_netskope_urllist.py`

**Interfaces:**
- Consumes: `NetskopeClient`, `netskope_argument_spec` from `module_utils.netskope`; `find_record` from `module_utils.netskope`.
- Produces: `plan_urllist_changes(current, urls, state, purge) -> dict` with keys `changed` (bool), `to_add` (list[str]), `to_remove` (list[str]), `result_urls` (list[str]), `before` ({"urls": list}), `after` ({"urls": list}). `current` is a URL-list dict shaped `{"id": int, "name": str, "data": {"urls": [...], "type": str}}`.

- [ ] **Step 1: Write the failing planner tests**

Create `tests/unit/plugins/modules/test_netskope_urllist.py`:

```python
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
```

- [ ] **Step 2: Run planner tests to verify they fail**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_urllist.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for `netskope_urllist`.

- [ ] **Step 3: Create the module with the planner and wiring**

Create `plugins/modules/netskope_urllist.py`:

```python
#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_urllist
short_description: Manage entries on an existing Netskope URL list
version_added: "0.2.0"
description:
  - Add, remove, or reconcile the URL entries of an existing URL list via the
    C(policy/urllist) endpoints.
  - The Netskope API cannot create or delete URL lists, so the target list must
    already exist; this module only manages its entries. Use
    M(mlowcher61.netskope.netskope_urllist_info) to discover lists.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  name:
    description:
      - The name of the existing URL list to modify.
      - Exactly one of O(name) or O(id) is required.
    type: str
  id:
    description:
      - The numeric id of the existing URL list to modify.
      - Exactly one of O(name) or O(id) is required.
    type: int
  urls:
    description:
      - The URL entries to add, remove, or reconcile against.
    type: list
    elements: str
    required: true
  state:
    description:
      - With V(present), ensure the given O(urls) are on the list.
      - With V(absent), ensure the given O(urls) are not on the list.
    type: str
    choices: [present, absent]
    default: present
  purge:
    description:
      - Only meaningful with O(state=present). When V(true), the list is
        reconciled to contain exactly O(urls), removing any other entries.
    type: bool
    default: false
"""

EXAMPLES = r"""
- name: Ensure two URLs are present on an existing list
  mlowcher61.netskope.netskope_urllist:
    name: Corp-Allowlist
    urls:
      - partner.example.com
      - vendor.example.com

- name: Make a list contain exactly these URLs (config as code)
  mlowcher61.netskope.netskope_urllist:
    id: 12
    state: present
    purge: true
    urls:
      - a.example.com
      - b.example.com

- name: Remove a URL from a list
  mlowcher61.netskope.netskope_urllist:
    name: Corp-Allowlist
    state: absent
    urls:
      - old.example.com
"""

RETURN = r"""
urllist:
  description: The URL list object after the change (predicted under check mode).
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)


def plan_urllist_changes(current, urls, state, purge):
    """Compute the change plan for a URL list's entries (pure, no I/O)."""
    urls = urls or []
    existing = list((current.get("data") or {}).get("urls") or [])
    existing_set = set(existing)
    desired_set = set(urls)

    if state == "present":
        to_add = [u for u in urls if u not in existing_set]
        # de-dup while preserving order of supplied urls
        seen = set()
        to_add = [u for u in to_add if not (u in seen or seen.add(u))]
        to_remove = [u for u in existing if u not in desired_set] if purge else []
    else:  # absent
        to_add = []
        to_remove = [u for u in existing if u in desired_set]

    remove_set = set(to_remove)
    result = [u for u in existing if u not in remove_set]
    for u in to_add:
        if u not in result:
            result.append(u)

    return {
        "changed": bool(to_add or to_remove),
        "to_add": to_add,
        "to_remove": to_remove,
        "result_urls": result,
        "before": {"urls": existing},
        "after": {"urls": result},
    }


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
        id=dict(type="int"),
        urls=dict(type="list", elements="str", required=True),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        purge=dict(type="bool", default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[["name", "id"]],
        mutually_exclusive=[["name", "id"]],
    )

    name = module.params["name"]
    list_id = module.params["id"]

    client = NetskopeClient(module)
    records = client.get_paginated("policy/urllist")
    if list_id is not None:
        current = find_record(records, lambda r: r.get("id") == list_id)
    else:
        current = find_record(records, lambda r: r.get("name") == name)

    if current is None:
        module.fail_json(
            msg="URL list %s was not found. This module can only modify entries "
            "on an existing list; the Netskope API cannot create URL lists. "
            "Create the list in the UI first." % (name if name is not None else list_id)
        )

    plan = plan_urllist_changes(
        current, module.params["urls"], module.params["state"], module.params["purge"]
    )
    diff = {"before": plan["before"], "after": plan["after"]}

    if not plan["changed"]:
        module.exit_json(changed=False, urllist=current, diff=diff)

    predicted = dict(current)
    predicted["data"] = dict(current.get("data") or {}, urls=plan["result_urls"])

    if module.check_mode:
        module.exit_json(changed=True, urllist=predicted, diff=diff)

    payload = {
        "name": current.get("name"),
        "data": dict(current.get("data") or {}, urls=plan["result_urls"]),
    }
    updated = client.request("PUT", "policy/urllist/%s" % current["id"], data=payload)
    module.exit_json(changed=True, urllist=updated or predicted, diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run planner tests to verify they pass**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_urllist.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Add end-to-end wiring tests**

Append to `tests/unit/plugins/modules/test_netskope_urllist.py`:

```python
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
                return "exit", exc.value.args[0], req
            except AnsibleFailJson as exc:
                return "fail", exc.value.args[0], req
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
```

- [ ] **Step 6: Run the full module test file**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_urllist.py -v`
Expected: PASS (9 passed).

- [ ] **Step 7: Sanity-check the module docs**

Run: `ansible-test sanity --docker default --python 3.11 plugins/modules/netskope_urllist.py`
Expected: EXIT 0, no findings. (Fix any DOCUMENTATION/RETURN sanity errors before committing.)

- [ ] **Step 8: Commit**

```bash
git add plugins/modules/netskope_urllist.py tests/unit/plugins/modules/test_netskope_urllist.py
git commit -m "Add netskope_urllist module (manage entries on existing lists)"
```

---

## Task 3: `netskope_scim_group` module

**Files:**
- Create: `plugins/modules/netskope_scim_group.py`
- Test: `tests/unit/plugins/modules/test_netskope_scim_group.py`

**Interfaces:**
- Consumes: `NetskopeClient`, `netskope_argument_spec`, `find_record` from `module_utils.netskope`; `get_scim_paginated` for `scim/Groups`.
- Produces:
  - `plan_scim_group_changes(current, display_name, external_id, members, state, purge) -> dict` with keys `changed` (bool), `action` (one of `"create"`, `"delete"`, `"patch"`, `"none"`), `members_to_add` (list[str]), `members_to_remove` (list[str]), `before` (dict), `after` (dict). `current` is a SCIM group dict `{"id": str, "displayName": str, "externalId": str, "members": [{"value": str}, ...]}` or `None` when absent.
  - `build_patch_ops(members_to_add, members_to_remove) -> list[dict]` — SCIM 2.0 PatchOp `Operations`.

- [ ] **Step 1: Write the failing planner + patch-ops tests**

Create `tests/unit/plugins/modules/test_netskope_scim_group.py`:

```python
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
```

- [ ] **Step 2: Run planner tests to verify they fail**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_scim_group.py -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` for `netskope_scim_group`.

- [ ] **Step 3: Create the module**

Create `plugins/modules/netskope_scim_group.py`:

```python
#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: netskope_scim_group
short_description: Manage a Netskope SCIM group and its membership
version_added: "0.2.0"
description:
  - Create, delete, and manage the membership of a SCIM 2.0 group via the
    C(scim/Groups) endpoints.
  - Members are given as SCIM user ids (the C(value) of a member entry). Use
    M(mlowcher61.netskope.netskope_scim_info) to discover user ids.
author:
  - mlowcher61 (@mlowcher61)
extends_documentation_fragment:
  - mlowcher61.netskope.netskope
options:
  display_name:
    description:
      - The SCIM group displayName; used to locate or create the group.
    type: str
    required: true
  external_id:
    description:
      - The SCIM externalId to set when creating the group.
    type: str
  members:
    description:
      - SCIM user ids to reconcile as members of the group.
    type: list
    elements: str
    default: []
  state:
    description:
      - With V(present), ensure the group exists and O(members) are members.
      - With V(absent), delete the group (O(members) is ignored).
    type: str
    choices: [present, absent]
    default: present
  purge:
    description:
      - Only meaningful with O(state=present). When V(true), the membership is
        reconciled to exactly O(members), removing any other members.
    type: bool
    default: false
"""

EXAMPLES = r"""
- name: Ensure a SCIM group exists with two members
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    external_id: eng-okta-001
    members:
      - 3f2a-user-id-1
      - 7b9c-user-id-2

- name: Reconcile group membership exactly (config as code)
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    state: present
    purge: true
    members:
      - 3f2a-user-id-1

- name: Delete a SCIM group
  mlowcher61.netskope.netskope_scim_group:
    display_name: Engineering
    state: absent
"""

RETURN = r"""
scim_group:
  description: The SCIM group object after the change (predicted under check mode).
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope import (
    NetskopeClient,
    netskope_argument_spec,
    find_record,
)

SCIM_GROUPS_PATH = "scim/Groups"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"


def _member_ids(group):
    return [m.get("value") for m in (group.get("members") or []) if m.get("value")]


def plan_scim_group_changes(current, display_name, external_id, members, state, purge):
    """Compute the change plan for a SCIM group (pure, no I/O)."""
    members = members or []
    desired_set = set(members)

    if state == "absent":
        changed = current is not None
        return {
            "changed": changed,
            "action": "delete" if changed else "none",
            "members_to_add": [],
            "members_to_remove": [],
            "before": current or {},
            "after": {} if changed else (current or {}),
        }

    if current is None:
        seen = set()
        add = [m for m in members if not (m in seen or seen.add(m))]
        after = {"displayName": display_name, "members": add}
        if external_id is not None:
            after["externalId"] = external_id
        return {
            "changed": True,
            "action": "create",
            "members_to_add": add,
            "members_to_remove": [],
            "before": {},
            "after": after,
        }

    existing = _member_ids(current)
    existing_set = set(existing)
    to_add = [m for m in members if m not in existing_set]
    seen = set()
    to_add = [m for m in to_add if not (m in seen or seen.add(m))]
    to_remove = [m for m in existing if m not in desired_set] if purge else []

    remove_set = set(to_remove)
    result = [m for m in existing if m not in remove_set]
    for m in to_add:
        if m not in result:
            result.append(m)

    changed = bool(to_add or to_remove)
    return {
        "changed": changed,
        "action": "patch" if changed else "none",
        "members_to_add": to_add,
        "members_to_remove": to_remove,
        "before": {"members": existing},
        "after": {"members": result},
    }


def build_patch_ops(members_to_add, members_to_remove):
    """Build SCIM 2.0 PatchOp Operations for member add/remove."""
    ops = []
    if members_to_add:
        ops.append({
            "op": "add",
            "path": "members",
            "value": [{"value": m} for m in members_to_add],
        })
    for m in members_to_remove:
        ops.append({"op": "remove", "path": 'members[value eq "%s"]' % m})
    return ops


def run_module():
    argument_spec = netskope_argument_spec()
    argument_spec.update(
        display_name=dict(type="str", required=True),
        external_id=dict(type="str"),
        members=dict(type="list", elements="str", default=[]),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        purge=dict(type="bool", default=False),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    display_name = module.params["display_name"]
    external_id = module.params["external_id"]

    client = NetskopeClient(module)
    groups = client.get_scim_paginated(
        SCIM_GROUPS_PATH,
        params={"filter": 'displayName eq "%s"' % display_name},
    )
    current = find_record(groups, lambda g: g.get("displayName") == display_name)

    plan = plan_scim_group_changes(
        current, display_name, external_id,
        module.params["members"], module.params["state"], module.params["purge"],
    )
    diff = {"before": plan["before"], "after": plan["after"]}

    if not plan["changed"]:
        module.exit_json(changed=False, scim_group=current or {}, diff=diff)

    if module.check_mode:
        module.exit_json(changed=True, scim_group=plan["after"], diff=diff)

    action = plan["action"]
    if action == "create":
        body = {
            "schemas": [GROUP_SCHEMA],
            "displayName": display_name,
            "members": [{"value": m} for m in plan["members_to_add"]],
        }
        if external_id is not None:
            body["externalId"] = external_id
        result = client.request("POST", SCIM_GROUPS_PATH, data=body)
        module.exit_json(changed=True, scim_group=result or body, diff=diff)
    elif action == "delete":
        client.request("DELETE", "%s/%s" % (SCIM_GROUPS_PATH, current["id"]))
        module.exit_json(changed=True, scim_group={}, diff=diff)
    else:  # patch
        body = {
            "schemas": [PATCH_SCHEMA],
            "Operations": build_patch_ops(
                plan["members_to_add"], plan["members_to_remove"]
            ),
        }
        result = client.request(
            "PATCH", "%s/%s" % (SCIM_GROUPS_PATH, current["id"]), data=body
        )
        module.exit_json(changed=True, scim_group=result or plan["after"], diff=diff)


def main():
    run_module()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run planner + patch-ops tests to verify they pass**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_scim_group.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Add end-to-end wiring tests**

Append to `tests/unit/plugins/modules/test_netskope_scim_group.py`:

```python
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
            return exc.value.args[0], req
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
```

- [ ] **Step 6: Run the full module test file**

Run: `python3 -m pytest tests/unit/plugins/modules/test_netskope_scim_group.py -v`
Expected: PASS (13 passed).

- [ ] **Step 7: Sanity-check the module docs**

Run: `ansible-test sanity --docker default --python 3.11 plugins/modules/netskope_scim_group.py`
Expected: EXIT 0, no findings.

- [ ] **Step 8: Commit**

```bash
git add plugins/modules/netskope_scim_group.py tests/unit/plugins/modules/test_netskope_scim_group.py
git commit -m "Add netskope_scim_group module (group + membership management)"
```

---

## Task 4: Full-suite verification and changelog

**Files:**
- Create: `changelogs/fragments/tier2-state-changing.yml` (only if `changelogs/` already exists in the repo; otherwise skip this file and note it in the commit)

**Interfaces:** none (verification task).

- [ ] **Step 1: Run the entire unit suite**

Run: `python3 -m pytest tests/unit -v`
Expected: PASS for all Tier 1 + Tier 2 tests; the pre-existing `filter_fields` learning-mode placeholder remains the only `xfail` (e.g. `NN passed, 1 xfailed`). If any Tier 1 test regressed, stop and investigate before continuing.

- [ ] **Step 2: Run sanity across both new modules together**

Run: `ansible-test sanity --docker default --python 3.11 plugins/modules/netskope_urllist.py plugins/modules/netskope_scim_group.py plugins/module_utils/netskope.py`
Expected: EXIT 0.

- [ ] **Step 3: Add a changelog fragment (only if `changelogs/` exists)**

Check: `ls changelogs/fragments/ 2>/dev/null`. If the directory exists, create `changelogs/fragments/tier2-state-changing.yml`:

```yaml
minor_changes:
  - netskope_urllist - new module to add, remove, or reconcile entries on an existing URL list.
  - netskope_scim_group - new module to manage a SCIM group and its membership.
```

If the directory does not exist, skip this step (the collection does not yet use the changelog framework).

- [ ] **Step 4: Commit (only if a changelog fragment was created)**

```bash
git add changelogs/fragments/tier2-state-changing.yml
git commit -m "Add changelog fragment for Tier 2 modules"
```

---

## Self-Review Notes (author)

- **Spec coverage:** shared pattern → Task 1 (`find_record`) + the planner/`run_module` split in Tasks 2–3; `netskope_urllist` → Task 2; `netskope_scim_group` (group + membership, PATCH add/remove, present/absent/purge, member ids accepted directly) → Task 3; check_mode + diff → tested in Tasks 2–3; testing/sanity → Tasks 2–4. `netskope_steering_profile` deliberately deferred (Global Constraints scope note) pending Swagger verification.
- **Deferred:** `netskope_steering_profile` gets its own plan once Open Item #3 (endpoint + schema) is resolved. `netskope_urllist` PUT-vs-append/remove sub-endpoint optimization (Open Item #1) is left as a follow-up; PUT of the full `data.urls` is correct and complete.
- **Type consistency:** planner return keys and `action` values referenced identically across module code and tests; `find_record(records, match)` signature identical in Task 1 and its consumers.
