"""Backfill SaaS Monthly Cost rows that predate the per-row currency fields.

Two cases:
1. `currency` is NULL (rows imported before the field existed) — populate from
   the parent SaaS Application's currency, falling back to AED.
2. `exchange_rate_to_base` is NULL or 0 — set to 1.0.
"""

from __future__ import annotations

import frappe


def execute():
	# 1. Backfill currency from the parent app
	frappe.db.sql(
		"""
		UPDATE `tabSaaS Monthly Cost` mc
		LEFT JOIN `tabSaaS Application` app ON app.name = mc.parent AND mc.parenttype = 'SaaS Application'
		SET mc.currency = COALESCE(app.currency, 'AED')
		WHERE mc.currency IS NULL OR mc.currency = ''
		"""
	)

	# 2. Default exchange rate
	frappe.db.sql(
		"""
		UPDATE `tabSaaS Monthly Cost`
		SET exchange_rate_to_base = 1.0
		WHERE exchange_rate_to_base IS NULL OR exchange_rate_to_base = 0
		"""
	)

	frappe.db.commit()
