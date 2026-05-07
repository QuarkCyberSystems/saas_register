import frappe
from frappe.model.document import Document


class SaaSApplication(Document):
	def validate(self):
		self.compute_annual_cost()

	def compute_annual_cost(self):
		# Note: monthly_cost is computed by the SaaS Application Tier controller
		# (see saas_application_tier.recompute_parent). We just keep annual_cost
		# in sync here in case monthly_cost was edited directly (e.g. via
		# bench console / data import) without going through tier hooks.
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
