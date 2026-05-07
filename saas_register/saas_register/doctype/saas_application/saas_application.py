import frappe
from frappe import _
from frappe.model.document import Document


class SaaSApplication(Document):
	def validate(self):
		self.rollup_tiers()
		self.compute_annual_cost()

	def rollup_tiers(self):
		"""Sum tier rows into seats_paid + monthly_cost; build plan_summary."""
		tiers = self.get("tiers") or []
		if not tiers:
			# Allow apps with no tier breakdown — keep whatever was set manually
			# (validate() never zeroes out unless tiers exist, to avoid surprising users
			# during the migration from the old single-`plan` model).
			if self.plan_summary is None:
				self.plan_summary = ""
			return

		total_seats = 0
		total_cost = 0.0
		labels: list[str] = []

		for row in tiers:
			seats = int(row.seats_paid or 0)
			cost = float(row.monthly_cost or 0)
			total_seats += seats
			total_cost += cost
			label = (row.tier_name or "").strip() or _("Tier")
			labels.append(f"{label} {seats}" if seats else label)

		self.seats_paid = total_seats
		self.monthly_cost = total_cost
		self.plan_summary = " / ".join(labels)

	def compute_annual_cost(self):
		self.annual_cost = float(self.monthly_cost or 0) * 12

	def recompute_seats_active(self):
		count = frappe.db.count(
			"SaaS Access",
			{"saas_application": self.name, "revoke_status": "Active"},
		)
		if (self.seats_active or 0) != count:
			frappe.db.set_value("SaaS Application", self.name, "seats_active", count, update_modified=False)


def recompute_seats_for(app_name: str):
	if not app_name:
		return
	if not frappe.db.exists("SaaS Application", app_name):
		return
	count = frappe.db.count(
		"SaaS Access",
		{"saas_application": app_name, "revoke_status": "Active"},
	)
	frappe.db.set_value("SaaS Application", app_name, "seats_active", count, update_modified=False)


@frappe.whitelist()
def get_tiers(saas_application: str) -> list[dict]:
	"""Used by the SaaS Access form to populate the tier autocomplete."""
	if not saas_application:
		return []
	rows = frappe.get_all(
		"SaaS Application Tier",
		filters={"parent": saas_application, "parenttype": "SaaS Application"},
		fields=["tier_name", "seats_paid", "monthly_cost", "currency"],
		order_by="idx asc",
	)
	for r in rows:
		seats = int(r.get("seats_paid") or 0)
		cost = float(r.get("monthly_cost") or 0)
		r["per_seat_cost"] = (cost / seats) if seats else 0
	return rows
