"""Backfill SaaS Access.revoke_on_offboarding for existing rows.

The field defaults to 1 (revoke) for newly created rows, but Frappe doesn't
backfill defaults on rows that predate the field. Default to 1 — the vast
majority of access rows are real humans whose accounts should be revoked.
Admins can flip individual rows for service accounts after migration.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("SaaS Access", "revoke_on_offboarding"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSaaS Access`
		SET revoke_on_offboarding = 1
		WHERE revoke_on_offboarding IS NULL
		"""
	)
	frappe.db.commit()
