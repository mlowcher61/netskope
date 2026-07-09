=================================
mlowcher61.netskope Release Notes
=================================

.. contents:: Topics

v0.3.1
======

Release Summary
---------------

Documentation-only release that works around a galaxy.ansible.com rendering bug affecting five module doc pages. No functional changes.

Bugfixes
--------

- module documentation - replaced ``M(...)`` module cross-references with ``C(...)`` so module docs render on galaxy.ansible.com, which currently fails with "Documentation Syntax Error" on any doc containing a module reference (https://github.com/ansible/ansible-hub-ui/issues/5586). The documentation itself was always valid; this only works around the Galaxy UI bug.

v0.3.0
======

Release Summary
---------------

Tier 3 release: NPA infrastructure management (``netskope_publisher``, ``netskope_private_app``) and quarantine management (``netskope_quarantine``, ``netskope_quarantine_info``). The quarantine modules use the legacy REST API v1 because quarantine management was never ported to REST API v2; they need the separate v1 token.

Minor Changes
-------------

- config-as-code - the Netskope API Token custom credential type gained an optional REST API v1 token field, injected as ``NETSKOPE_API_V1_TOKEN``.
- module_utils - added ``NetskopeV1Client`` and v1 credential handling (``api_v1_token`` / ``NETSKOPE_API_V1_TOKEN``) so modules can call the few legacy REST API v1 endpoints that have no v2 equivalent, such as quarantine management. v1 URLs are redacted in error output because the v1 token travels as a query parameter.

Bugfixes
--------

- netskope_urllist_info - the ``fields`` option now projects each URL list down to the requested top-level keys; previously it was accepted but had no effect.

New Modules
-----------

- mlowcher61.netskope.netskope_private_app - Manage Netskope Private Access private applications.
- mlowcher61.netskope.netskope_publisher - Manage Netskope Private Access publishers.
- mlowcher61.netskope.netskope_quarantine - Release or delete a file held in Netskope quarantine.
- mlowcher61.netskope.netskope_quarantine_info - List files held in Netskope quarantine.

v0.2.0
======

Release Summary
---------------

First state-changing modules. Both support check mode, ``--diff``, idempotent re-runs, and a uniform ``state``/``purge`` model, and ship with example playbooks under ``examples/``.

Minor Changes
-------------

- module_utils - added a shared ``find_record`` helper used by state-changing modules to resolve existing resources by attribute.

New Modules
-----------

- mlowcher61.netskope.netskope_scim_group - Manage a Netskope SCIM group and its membership
- mlowcher61.netskope.netskope_urllist - Manage entries on an existing Netskope URL list

v0.1.0
======

Release Summary
---------------

Initial release of the mlowcher61.netskope collection for the Netskope REST API v2. Ships read-only lookup modules, shared credential handling (Ansible Automation Platform custom credential injection via environment variables, or an explicit ``provider`` dict), an execution environment definition, and AAP config-as-code.

New Modules
-----------

- mlowcher61.netskope.netskope_alert_info - Retrieve Netskope alerts
- mlowcher61.netskope.netskope_publisher_info - List Netskope Private Access publishers
- mlowcher61.netskope.netskope_scim_info - List Netskope SCIM users or groups
- mlowcher61.netskope.netskope_urllist_info - Retrieve Netskope URL lists
