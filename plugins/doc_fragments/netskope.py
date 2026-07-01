# -*- coding: utf-8 -*-
# Copyright: (c) 2026, mlowcher61 <mlowcher@hotmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


class ModuleDocFragment(object):

    # Shared connection options for every module in the collection.
    DOCUMENTATION = r"""
options:
  tenant_url:
    description:
      - The base URL of the Netskope tenant, for example C(https://acme.goskope.com).
      - May also be supplied via the I(provider) dict or the
        E(NETSKOPE_TENANT_URL) environment variable.
    type: str
  api_token:
    description:
      - The Netskope REST API v2 token, sent in the C(Netskope-API-Token) header.
      - May also be supplied via the I(provider) dict or the
        E(NETSKOPE_API_TOKEN) environment variable.
      - In Ansible Automation Platform, inject this through a custom credential
        type rather than storing it in a vault.
    type: str
  provider:
    description:
      - A dict of connection details, mirroring the provider pattern used in
        network collections.
      - The individual I(tenant_url) and I(api_token) parameters take precedence
        over the matching values inside this dict.
    type: dict
    suboptions:
      tenant_url:
        description: The base URL of the Netskope tenant.
        type: str
      api_token:
        description: The Netskope REST API v2 token.
        type: str
notes:
  - "Credential precedence is: explicit parameter, then I(provider) dict, then
    environment variable."
  - This collection targets the Netskope REST API v2 only.
"""
