# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from unittest.mock import MagicMock, patch

from ansible_collections.mlowcher61.netskope.plugins.module_utils import netskope as ns


class FakeModule:
    """A stand-in for AnsibleModule that raises on fail_json like the real one."""

    def __init__(self, params):
        self.params = params
        self.fail_kwargs = None

    def fail_json(self, **kwargs):
        self.fail_kwargs = kwargs
        raise SystemExit(1)


def make_module(**params):
    base = dict(tenant_url=None, api_token=None, provider=None)
    base.update(params)
    return FakeModule(base)


# --- credential resolution precedence -------------------------------------

def test_explicit_params_win_over_provider_and_env(monkeypatch):
    monkeypatch.setenv(ns.NETSKOPE_ENV_TENANT, "https://env.goskope.com")
    monkeypatch.setenv(ns.NETSKOPE_ENV_TOKEN, "env-token")
    module = make_module(
        tenant_url="https://param.goskope.com",
        api_token="param-token",
        provider=dict(tenant_url="https://prov.goskope.com", api_token="prov-token"),
    )
    assert ns.resolve_credentials(module) == ("https://param.goskope.com", "param-token")


def test_provider_used_when_params_absent(monkeypatch):
    monkeypatch.delenv(ns.NETSKOPE_ENV_TENANT, raising=False)
    monkeypatch.delenv(ns.NETSKOPE_ENV_TOKEN, raising=False)
    module = make_module(
        provider=dict(tenant_url="https://prov.goskope.com", api_token="prov-token"),
    )
    assert ns.resolve_credentials(module) == ("https://prov.goskope.com", "prov-token")


def test_environment_used_as_last_resort(monkeypatch):
    monkeypatch.setenv(ns.NETSKOPE_ENV_TENANT, "https://env.goskope.com")
    monkeypatch.setenv(ns.NETSKOPE_ENV_TOKEN, "env-token")
    module = make_module()
    assert ns.resolve_credentials(module) == ("https://env.goskope.com", "env-token")


def test_missing_tenant_fails(monkeypatch):
    monkeypatch.delenv(ns.NETSKOPE_ENV_TENANT, raising=False)
    module = make_module(api_token="tok")
    with pytest.raises(SystemExit):
        ns.resolve_credentials(module)
    assert "tenant_url" in module.fail_kwargs["msg"]


# --- base URL normalization -----------------------------------------------

@pytest.mark.parametrize("supplied,expected", [
    ("https://acme.goskope.com", "https://acme.goskope.com/api/v2"),
    ("https://acme.goskope.com/", "https://acme.goskope.com/api/v2"),
    ("acme.goskope.com", "https://acme.goskope.com/api/v2"),
    ("https://acme.goskope.com/api/v2", "https://acme.goskope.com/api/v2"),
])
def test_normalize_base_url(supplied, expected):
    assert ns.NetskopeClient._normalize_base_url(supplied) == expected


# --- response envelope handling -------------------------------------------

@pytest.mark.parametrize("payload,expected", [
    ([{"id": 1}], [{"id": 1}]),
    ({"data": [{"id": 1}]}, [{"id": 1}]),
    ({"result": [{"id": 2}]}, [{"id": 2}]),
    ({"nothing": True}, []),
])
def test_extract_items(payload, expected):
    assert ns.NetskopeClient._extract_items(payload) == expected


# --- pagination ------------------------------------------------------------

def test_get_paginated_walks_until_short_page():
    module = make_module(tenant_url="https://acme.goskope.com", api_token="tok")
    client = ns.NetskopeClient(module)
    pages = [[{"id": i} for i in range(100)], [{"id": 100}]]
    seen_offsets = []

    def fake_request(method, path, params=None, data=None):
        seen_offsets.append(params["offset"])
        return {"data": pages.pop(0)}

    client.request = fake_request
    result = client.get_paginated("policy/urllist")
    assert len(result) == 101
    assert seen_offsets == [0, 100]


# --- error handling / retries ---------------------------------------------

@patch("ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope.time.sleep")
@patch("ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope.open_url")
def test_request_retries_on_429_then_succeeds(mock_open_url, mock_sleep):
    module = make_module(tenant_url="https://acme.goskope.com", api_token="tok")
    client = ns.NetskopeClient(module)
    rate_limited = ns.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "0"}, None)
    ok = MagicMock()
    ok.read.return_value = b'{"data": []}'
    mock_open_url.side_effect = [rate_limited, ok]

    assert client.request("GET", "policy/urllist") == {"data": []}
    assert mock_open_url.call_count == 2
    mock_sleep.assert_called_once()


@patch("ansible_collections.mlowcher61.netskope.plugins.module_utils.netskope.open_url")
def test_request_maps_401_to_helpful_message(mock_open_url):
    module = make_module(tenant_url="https://acme.goskope.com", api_token="bad")
    client = ns.NetskopeClient(module)
    mock_open_url.side_effect = ns.HTTPError("u", 401, "Unauthorized", {}, None)
    with pytest.raises(SystemExit):
        client.request("GET", "policy/urllist")
    assert module.fail_kwargs["status_code"] == 401
    assert "Authentication failed" in module.fail_kwargs["msg"]


# --- find_record helper ---------------------------------------------------

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
