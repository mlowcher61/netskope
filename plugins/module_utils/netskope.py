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
import re
import time

from ansible.module_utils.common.text.converters import to_native
from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.six.moves.urllib.parse import urlencode
from ansible.module_utils.urls import open_url

NETSKOPE_ENV_TENANT = "NETSKOPE_TENANT_URL"
NETSKOPE_ENV_TOKEN = "NETSKOPE_API_TOKEN"
NETSKOPE_ENV_V1_TOKEN = "NETSKOPE_API_V1_TOKEN"

# The v1 API carries its token as a query parameter, so any URL echoed back in
# an error message must have it stripped first.
TOKEN_QUERY_RE = re.compile(r"(token=)[^&]+")

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


def flatten_quarantined_files(payload):
    """Flatten the v1 quarantine ``op=get-files`` envelope into one flat list.

    The endpoint groups files under ``data.quarantined[*].files``; each
    returned file dict is annotated with its holding profile's id and name so
    callers do not need to walk the nesting. Shared by the quarantine modules.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    profiles = data.get("quarantined") if isinstance(data, dict) else None
    files = []
    for profile in profiles or []:
        for record in profile.get("files") or []:
            row = dict(record)
            row.setdefault(
                "quarantine_profile_id", profile.get("quarantine_profile_id")
            )
            row.setdefault(
                "quarantine_profile_name", profile.get("quarantine_profile_name")
            )
            files.append(row)
    return files


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


def netskope_v1_argument_spec():
    """Return the argument spec for modules that call the legacy REST API v1.

    A handful of features (quarantine management, for one) were never ported
    to REST API v2 and authenticate with a separate v1 token, so these modules
    take ``api_v1_token`` instead of ``api_token``.
    """
    return dict(
        tenant_url=dict(type="str"),
        api_v1_token=dict(type="str", no_log=True),
        provider=dict(
            type="dict",
            options=dict(
                tenant_url=dict(type="str"),
                api_v1_token=dict(type="str", no_log=True),
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


def resolve_v1_credentials(module):
    """Resolve tenant_url and the legacy v1 api token.

    Same precedence as :func:`resolve_credentials` (parameter -> provider ->
    environment). The resolved token is registered with the module's no_log
    machinery because, unlike the v2 header token, it travels in URLs and an
    environment-sourced value would otherwise not be masked in output.
    """
    provider = module.params.get("provider") or {}
    tenant_url = (
        module.params.get("tenant_url")
        or provider.get("tenant_url")
        or os.environ.get(NETSKOPE_ENV_TENANT)
    )
    api_v1_token = (
        module.params.get("api_v1_token")
        or provider.get("api_v1_token")
        or os.environ.get(NETSKOPE_ENV_V1_TOKEN)
    )
    if not tenant_url:
        module.fail_json(
            msg="A Netskope tenant_url must be supplied via the 'tenant_url' "
            "parameter, the 'provider' dict, or the %s environment variable."
            % NETSKOPE_ENV_TENANT
        )
    if not api_v1_token:
        module.fail_json(
            msg="A Netskope api_v1_token must be supplied via the "
            "'api_v1_token' parameter, the 'provider' dict, or the %s "
            "environment variable. Note this is the legacy REST API v1 "
            "token, not the v2 token." % NETSKOPE_ENV_V1_TOKEN
        )
    no_log_values = getattr(module, "no_log_values", None)
    if no_log_values is not None:
        no_log_values.add(api_v1_token)
    return tenant_url, api_v1_token


class NetskopeClient:
    """A thin REST client for the Netskope API v2, built on :func:`open_url`.

    It deliberately avoids third-party dependencies (no ``requests``) so that it
    runs unchanged inside any execution environment.
    """

    API_SUFFIX = "/api/v2"

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

    @classmethod
    def _normalize_base_url(cls, tenant_url):
        """Turn a tenant hostname or URL into a full API base URL."""
        url = tenant_url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        if not url.endswith(cls.API_SUFFIX):
            url = url + cls.API_SUFFIX
        return url

    @staticmethod
    def _redact_url(url):
        """Strip credential material from a URL before it appears in output."""
        return TOKEN_QUERY_RE.sub(r"\1<redacted>", url)

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
        url = self._redact_url(url)
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


class NetskopeV1Client(NetskopeClient):
    """Client for the legacy Netskope REST API v1.

    A few features (quarantine management among them) were never ported to
    REST API v2. The v1 API differs from v2 in three ways this class absorbs:

    * the base path is ``/api/v1``;
    * authentication is a v1 token passed as the ``token`` query parameter on
      every call rather than a header;
    * responses use a ``status``/``data`` envelope and can report an error
      inside an HTTP 200, so the body must be checked as well.
    """

    API_SUFFIX = "/api/v1"

    def __init__(self, module):
        self.module = module
        tenant_url, api_v1_token = resolve_v1_credentials(module)
        self.base_url = self._normalize_base_url(tenant_url)
        self.token = api_v1_token
        self.headers = {"Accept": "application/json"}
        self.timeout = DEFAULT_TIMEOUT

    def request(self, method, path, params=None, data=None):
        params = dict(params or {})
        params["token"] = self.token
        payload = super(NetskopeV1Client, self).request(
            method, path, params=params, data=data
        )
        if isinstance(payload, dict) and payload.get("status") == "error":
            errors = payload.get("errors") or []
            self.module.fail_json(
                msg="Netskope API v1 request %s %s failed: %s"
                % (method, path, "; ".join(to_native(e) for e in errors) or "unknown error"),
                errors=errors,
            )
        return payload
