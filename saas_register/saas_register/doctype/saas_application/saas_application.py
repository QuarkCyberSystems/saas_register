"""Controller for SaaS Application.

Validations & recompute on save:
- monthly_costs: (parent, month) is unique
- cost_allocations: sum of allocation_percent == 100 when any row exists
- avg_monthly_cost: recomputed from last 3 monthly_costs rows, converted to
  base currency via each row's `exchange_rate_to_base`. Reports cleanly even
  when AWS bills in USD and reporting is AED.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_first_day, getdate


class SaaSApplication(Document):
	def validate(self):
		self._normalize_monthly_cost_months()
		self._enforce_unique_months()
		self._default_monthly_cost_currency()
		self._validate_allocation_sum()
		self._recompute_avg_monthly_cost()

	def _normalize_monthly_cost_months(self):
		for row in self.get("monthly_costs") or []:
			if row.month:
				row.month = get_first_day(getdate(row.month))

	def _enforce_unique_months(self):
		seen: dict[str, int] = {}
		for row in self.get("monthly_costs") or []:
			if not row.month:
				continue
			key = str(row.month)
			if key in seen:
				frappe.throw(
					_("Two monthly cost rows for {0}. Each month must appear at most once.").format(
						frappe.bold(key)
					),
					title=_("Duplicate Month"),
				)
			seen[key] = 1

	def _default_monthly_cost_currency(self):
		"""Fill currency from the parent app when blank; default exchange rate to 1.0.

		Lets existing rows (which predate per-row currency) save cleanly and
		makes new manual entries effortless when the app's currency is the
		base currency.
		"""
		default_currency = self.currency or "AED"
		for row in self.get("monthly_costs") or []:
			if not row.currency:
				row.currency = default_currency
			if not row.exchange_rate_to_base:
				row.exchange_rate_to_base = 1.0

	def _validate_allocation_sum(self):
		rows = self.get("cost_allocations") or []
		if not rows:
			return
		total = sum(flt(r.allocation_percent or 0) for r in rows)
		# Allow tiny rounding drift
		if abs(total - 100.0) > 0.01:
			frappe.throw(
				_("Cost Allocations must sum to 100%. Currently: {0}%.").format(
					frappe.bold(f"{total:.2f}")
				),
				title=_("Allocation Mismatch"),
			)

	def _recompute_avg_monthly_cost(self):
		rows = sorted(
			(r for r in (self.get("monthly_costs") or []) if r.month),
			key=lambda r: getdate(r.month),
			reverse=True,
		)
		last3 = rows[:3]
		if not last3:
			self.avg_monthly_cost = 0
			return
		# Convert each row to base currency before averaging. AWS bills in USD;
		# reporting still rolls up cleanly in AED via exchange_rate_to_base.
		converted = [
			flt(r.amount or 0) * flt(r.exchange_rate_to_base or 1.0)
			for r in last3
		]
		self.avg_monthly_cost = sum(converted) / len(converted)

	def recompute_seats_active(self):
		count = frappe.db.count(
			"SaaS Access",
			{"saas_application": self.name, "revoke_status": "Active"},
		)
		if (self.seats_active or 0) != count:
			frappe.db.set_value("SaaS Application", self.name, "seats_active", count, update_modified=False)


def recompute_seats_for(app_name: str):
	if not app_name or not frappe.db.exists("SaaS Application", app_name):
		return
	count = frappe.db.count(
		"SaaS Access",
		{"saas_application": app_name, "revoke_status": "Active"},
	)
	frappe.db.set_value("SaaS Application", app_name, "seats_active", count, update_modified=False)


def compute_monthly_cost(app_name: str) -> float:
	"""Sum the per-seat cost of every *billable* SaaS Access on this app.

	A row is billable when subscription_status == "Active". Paused and
	Cancelled subscriptions don't bill this month.

	Per-seat cost resolution, in order:
	  1. The access row's own `monthly_cost_share` when > 0 (negotiated override).
	  2. Otherwise the tier's `monthly_cost_per_seat` (the usual price source —
	     e.g. Claude, whose access rows leave the share blank).
	  3. Otherwise 0.
	"""
	rows = frappe.get_all(
		"SaaS Access",
		filters={
			"saas_application": app_name,
			"subscription_status": "Active",
		},
		fields=["monthly_cost_share", "tier_or_plan"],
	)
	tier_price: dict[str, float] = {}
	total = 0.0
	for row in rows:
		share = flt(row.monthly_cost_share)
		if share > 0:
			total += share
			continue
		if row.tier_or_plan:
			if row.tier_or_plan not in tier_price:
				tier_price[row.tier_or_plan] = flt(
					frappe.db.get_value("SaaS Tier", row.tier_or_plan, "monthly_cost_per_seat")
				)
			total += tier_price[row.tier_or_plan]
	return flt(total)


def recompute_monthly_cost_for(app_name: str):
	"""Recompute and persist `monthly_cost` from this app's active access rows.

	Seat-based models (Per-User, and Shared apps that define tiers) are always
	overwritten — including down to 0 when the last seat is removed. A Shared
	app with no tiers and no per-seat shares keeps its manually-entered flat
	fee, and Usage-Based apps are never touched (their cost lives in the
	monthly_costs time-series).
	"""
	if not app_name or not frappe.db.exists("SaaS Application", app_name):
		return
	model = frappe.db.get_value("SaaS Application", app_name, "subscription_model")
	if model == "Usage-Based":
		return

	total = compute_monthly_cost(app_name)

	if model == "Shared" and total == 0:
		has_tiers = frappe.db.exists(
			"SaaS Tier", {"saas_application": app_name, "is_active": 1}
		)
		if not has_tiers:
			# Flat-fee shared contract not derived from seats — leave it alone.
			return

	frappe.db.set_value(
		"SaaS Application", app_name, "monthly_cost", total, update_modified=False
	)


# ---------------------------------------------------------------------------
# Form-button entry point (called from saas_application.js)
# ---------------------------------------------------------------------------


def recompute_all_monthly_costs() -> dict:
	"""Maintenance helper: recompute `monthly_cost` for every app from its
	active SaaS Access rows. Run after deploying the auto-cost feature, or any
	time the field drifts. Safe to re-run (idempotent)."""
	updated = 0
	for name in frappe.get_all("SaaS Application", pluck="name"):
		recompute_monthly_cost_for(name)
		updated += 1
	frappe.db.commit()
	return {"apps_recomputed": updated}


@frappe.whitelist()
def recompute(name: str) -> dict:
	"""Manually re-run seats_active and avg_monthly_cost for one app.

	Useful after data migrations or when a hook didn't fire (rare). The same
	logic runs automatically on every save and on every SaaS Access change.
	"""
	doc = frappe.get_doc("SaaS Application", name)
	doc.check_permission("write")
	recompute_seats_for(doc.name)
	recompute_monthly_cost_for(doc.name)
	doc._recompute_avg_monthly_cost()
	frappe.db.set_value(
		"SaaS Application",
		doc.name,
		"avg_monthly_cost",
		flt(doc.avg_monthly_cost),
		update_modified=False,
	)
	doc.reload()
	return {
		"name": doc.name,
		"seats_active": doc.seats_active,
		"monthly_cost": doc.monthly_cost,
		"avg_monthly_cost": doc.avg_monthly_cost,
	}
