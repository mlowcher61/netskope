# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Shared connection helper for the mlowcher61.netskope collection.

This module centralises authentication, request handling, error mapping, and
pagination for the Netskope REST API v2 so that every module presents a
consistent interface and behaviour.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
import os
import time

from ansible.module_utils.common.text.converters import to_native
from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.six.moves.urllib.parse import urlencode
from ansible.module_utils.urls import open_url

NETSKOPE_ENV_TENANT = "NETSKOPE_TENANT_URL"
NETSKOPE_ENV_TOKEN = "NETSKOPE_API_TOKEN"

DEFAULT_PAGE_LIMIT = 100
DEFAULT_TIMEOUT = 30
MAX_RATE_LIMIT_RETRIES = 3


def find_record(records, match):
    """Return the first record for which ``match(record)`` is truthy, else None.

    A small shared helper so every module resolves "does this resource already
    exist?" the same way against a list fetched from the API.
    """
    for record in records:
        if match(record):
            return record
    return None


def netskope_argument_spec():
    """Return the argument spec shared by every module in this collection.

    Credentials may be supplied three ways; see :func:`resolve_credentials` for
    the precedence order.
    """
    return dict(
        tenant_url=dict(type="str"),
        api_token=dict(type="str", no_log=True),
        provider=dict(
            type="dict",
            options=dict(
                tenant_url=dict(type="str"),
                api_token=dict(type="str", no_log=True),
            ),
        ),
    )


def resolve_credentials(module):
    """Resolve tenant_url and api_token using a fixed precedence.

    Order: explicit module parameter -> ``provider`` dict -> environment
    variable. This lets an AAP custom credential type inject secrets as
    environment variables without ever placing the token in a playbook or vault.
    """
    provider = module.params.get("provider") or {}
    tenant_url = (
        module.params.get("tenant_url")
        or provider.get("tenant_url")
        or os.environ.get(NETSKOPE_ENV_TENANT)
    )
    api_token = (
        module.params.get("api_token")
        or provider.get("api_token")
        or os.environ.get(NETSKOPE_ENV_TOKEN)
    )
    if not tenant_url:
        module.fail_json(
            msg="A Netskope tenant_url must be supplied via the 'tenant_url' "
            "parameter, the 'provider' dict, or the %s environment variable."
            % NETSKOPE_ENV_TENANT
        )
    if not api_token:
        module.fail_json(
            msg="A Netskope api_token must be supplied via the 'api_token' "
            "parameter, the 'provider' dict, or the %s environment variable."
            % NETSKOPE_ENV_TOKEN
        )
    return tenant_url, api_token


class NetskopeClient:
    """A thin REST client for the Netskope API v2, built on :func:`open_url`.

    It deliberately avoids third-party dependencies (no ``requests``) so that it
    runs unchanged inside any execution environment.
    """

    def __init__(self, module):
        self.module = module
        tenant_url, api_token = resolve_credentials(module)
        self.base_url = self._normalize_base_url(tenant_url)
        self.headers = {
            "Netskope-API-Token": api_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.timeout = DEFAULT_TIMEOUT

    @staticmethod
    def _normalize_base_url(tenant_url):
        """Turn a tenant hostname or URL into a full ``.../api/v2`` base URL."""
        url = tenant_url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        if not url.endswith("/api/v2"):
            url = url + "/api/v2"
        return url

    def request(self, method, path, params=None, data=None):
        """Perform a single API call and return the decoded JSON body."""
        url = self.base_url + "/" + path.lstrip("/")
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = url + "?" + urlencode(clean, doseq=True)
        body = json.dumps(data) if data is not None else None

        attempt = 0
        while True:
            try:
                response = open_url(
                    url,
                    method=method,
                    headers=self.headers,
                    data=body,
                    timeout=self.timeout,
                    validate_certs=True,
                )
                return self._parse_body(response.read())
            except HTTPError as error:
                if error.code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                    attempt += 1
                    self._sleep_for_rate_limit(error, attempt)
                    continue
                self._fail_for_http_error(error, method, url)
            except URLError as error:
                self.module.fail_json(
                    msg="Could not connect to Netskope tenant at %s: %s"
                    % (self.base_url, to_native(error.reason))
                )

    def get_paginated(self, path, params=None):
        """Fetch every page of a list endpoint using limit/offset pagination."""
        params = dict(params or {})
        limit = int(params.get("limit") or DEFAULT_PAGE_LIMIT)
        params["limit"] = limit
        offset = int(params.get("offset") or 0)

        results = []
        while True:
            params["offset"] = offset
            payload = self.request("GET", path, params=params)
            page = self._extract_items(payload)
            results.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return results

    def get_scim_paginated(self, path, params=None, count=DEFAULT_PAGE_LIMIT):
        """Fetch every page of a SCIM list endpoint.

        SCIM uses 1-based ``startIndex``/``count`` paging and a ``Resources``
        envelope, which is different from the limit/offset scheme used elsewhere.
        """
        params = dict(params or {})
        params["count"] = count
        start = int(params.get("startIndex") or 1)

        results = []
        while True:
            params["startIndex"] = start
            payload = self.request("GET", path, params=params)
            page = payload.get("Resources", []) if isinstance(payload, dict) else []
            results.extend(page)
            total = payload.get("totalResults") if isinstance(payload, dict) else None
            if len(page) < count:
                break
            start += count
            if total is not None and start > total:
                break
        return results

    @staticmethod
    def _parse_body(raw):
        if not raw:
            return {}
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}

    @staticmethod
    def _extract_items(payload):
        """Pull the list of records out of a Netskope response envelope."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "result", "results", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _sleep_for_rate_limit(self, error, attempt):
        """Back off after a 429, honouring Retry-After when the server sends it.

        Default policy: use the Retry-After header if present and numeric,
        otherwise fall back to exponential backoff (2 ** attempt seconds).
        """
        retry_after = error.headers.get("Retry-After") if error.headers else None
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = 2 ** attempt
        time.sleep(delay)

    def _fail_for_http_error(self, error, method, url):
        try:
            detail = error.read().decode("utf-8")
        except Exception:
            detail = ""
        parsed = detail
        if detail:
            try:
                parsed = json.loads(detail)
            except ValueError:
                parsed = detail

        messages = {
            401: "Authentication failed (401): the Netskope-API-Token was "
            "rejected. Check the api_token and that it is valid for this tenant.",
            403: "Authorization failed (403): the token is valid but lacks the "
            "privileges required for %s %s." % (method, url),
            429: "Rate limit exceeded (429) and retries were exhausted for "
            "%s %s." % (method, url),
        }
        msg = messages.get(
            error.code,
            "Netskope API request %s %s failed with HTTP %s."
            % (method, url, error.code),
        )
        self.module.fail_json(msg=msg, status_code=error.code, response=parsed)
