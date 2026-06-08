"""Controller for SaaS Tier — a tier inside a SaaS Application.

Solves the mixed-tier case: one Shared contract (e.g. Claude.ai) where
individual users sit on different tiers (Max, Pro, etc.). Each SaaS Access
points at a SaaS Tier via `tier_or_plan`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from saas_register.saas_register.doctype.saas_application.saas_application import (
	recompute_monthly_cost_for,
)


class SaaSTier(Document):
	def validate(self):
		self._enforce_unique_within_app()

	def on_update(self):
		# Changing a tier's per-seat price (or toggling is_active) reflows the
		# cost of every access row sitting on it.
		recompute_monthly_cost_for(self.saas_application)

	def on_trash(self):
		recompute_monthly_cost_for(self.saas_application)

	def _enforce_unique_within_app(self):
		existing = frappe.db.exists(
			"SaaS Tier",
			{
				"saas_application": self.saas_application,
				"tier_name": self.tier_name,
				"name": ("!=", self.name),
			},
		)
		if existing:
			frappe.throw(
				_("Tier {0} already exists on {1}.").format(
					frappe.bold(self.tier_name),
					frappe.bold(self.saas_application),
				),
				title=_("Duplicate Tier"),
			)
