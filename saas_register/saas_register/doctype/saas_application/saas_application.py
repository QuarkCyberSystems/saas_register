import frappe
from frappe.model.document import Document


class SaaSApplication(Document):
	def validate(self):
		self.compute_annual_cost()

	def compute_annual_cost(self):
		if not self.monthly_cost:
			self.annual_cost = 0
			return
		self.annual_cost = float(self.monthly_cost) * 12

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
