"""Migrate SaaS Access.tier_or_plan from free-text Data to Link → SaaS Tier.

Before:    tier_or_plan was a Data field with autosuggest from existing values.
After:     tier_or_plan is a Link to the SaaS Tier doctype.

For each distinct (saas_application, tier_or_plan) pair on existing SaaS Access
rows, we create a SaaS Tier row (if one doesn't already exist) and relink the
access row to point at that tier's name. Free-text values that don't make sense
(empty strings, whitespace) are cleared.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("SaaS Access", "tier_or_plan"):
		return

	# Distinct (app, tier-text) pairs currently in use.
	pairs = frappe.db.sql(
		"""
		SELECT DISTINCT saas_application, tier_or_plan
		FROM `tabSaaS Access`
		WHERE tier_or_plan IS NOT NULL AND TRIM(tier_or_plan) != ''
		""",
		as_dict=True,
	)

	migrated = 0
	cleared = 0

	for pair in pairs:
		app = pair["saas_application"]
		text = (pair["tier_or_plan"] or "").strip()
		if not app or not text:
			# Clear nonsensical leftovers.
			frappe.db.sql(
				"UPDATE `tabSaaS Access` SET tier_or_plan = NULL WHERE saas_application = %s AND tier_or_plan = %s",
				(app, pair["tier_or_plan"]),
			)
			cleared += 1
			continue

		# If text already matches a SaaS Tier name, reuse it.
		if frappe.db.exists("SaaS Tier", text):
			tier_app = frappe.db.get_value("SaaS Tier", text, "saas_application")
			if tier_app == app:
				# Already a valid Link value — just normalise.
				frappe.db.sql(
					"UPDATE `tabSaaS Access` SET tier_or_plan = %s WHERE saas_application = %s AND tier_or_plan = %s",
					(text, app, pair["tier_or_plan"]),
				)
				migrated += 1
				continue

		# Look for an existing SaaS Tier with this tier_name scoped to this app.
		tier_name = frappe.db.get_value(
			"SaaS Tier",
			{"saas_application": app, "tier_name": text},
			"name",
		)
		if not tier_name:
			tier = frappe.get_doc(
				{
					"doctype": "SaaS Tier",
					"saas_application": app,
					"tier_name": text,
					"is_active": 1,
				}
			)
			tier.flags.ignore_permissions = True
			tier.insert(ignore_permissions=True)
			tier_name = tier.name

		# Relink the access rows. Use the original (pre-trim) text in the WHERE
		# so we catch the exact rows.
		frappe.db.sql(
			"UPDATE `tabSaaS Access` SET tier_or_plan = %s WHERE saas_application = %s AND tier_or_plan = %s",
			(tier_name, app, pair["tier_or_plan"]),
		)
		migrated += 1

	frappe.db.commit()
	frappe.logger().info(
		f"saas_register: migrated {migrated} tier pairs, cleared {cleared} empty values."
	)
