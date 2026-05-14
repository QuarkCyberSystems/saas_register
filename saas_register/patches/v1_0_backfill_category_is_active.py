"""Backfill SaaS Category.is_active for categories that predate the field."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("SaaS Category", "is_active"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSaaS Category`
		SET is_active = 1
		WHERE is_active IS NULL
		"""
	)
	frappe.db.commit()
