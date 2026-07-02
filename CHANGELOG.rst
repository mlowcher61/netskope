=================================
mlowcher61.netskope Release Notes
=================================

.. contents:: Topics

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
