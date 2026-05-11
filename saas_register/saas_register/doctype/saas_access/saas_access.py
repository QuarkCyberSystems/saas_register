import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from saas_register.saas_register.doctype.saas_application.saas_application import (
	recompute_seats_for,
)


class SaaSAccess(Document):
	def validate(self):
		self.enforce_unique_active_access()
		self.enforce_per_user_requirements()
		self.fill_revoke_metadata()

	def enforce_unique_active_access(self):
		filters = {
			"employee": self.employee,
			"saas_application": self.saas_application,
			"revoke_status": "Active",
			"name": ("!=", self.name),
		}
		if frappe.db.exists("SaaS Access", filters):
			frappe.throw(
				_("{0} already has active access to {1}.").format(
					frappe.bold(self.employee_name or self.employee),
					frappe.bold(self.app_name or self.saas_application),
				),
				title=_("Duplicate Access"),
			)

	def enforce_per_user_requirements(self):
		"""When the parent app is `Per-User`, this access record IS the contract.
		`per_user_renewal_date` and `monthly_cost_share` are required."""
		model = frappe.db.get_value("SaaS Application", self.saas_application, "subscription_model")
		if model != "Per-User":
			return

		missing: list[str] = []
		if not self.per_user_renewal_date:
			missing.append(_("Renewal Date"))
		if not flt(self.monthly_cost_share):
			missing.append(_("Monthly Cost Share"))

		if missing:
			frappe.throw(
				_("{0} is required when the application is Per-User.").format(", ".join(missing)),
				title=_("Per-User fields required"),
			)

	def fill_revoke_metadata(self):
		if self.revoke_status == "Revoked":
			if not self.revoked_date:
				self.revoked_date = nowdate()
			if not self.revoked_by:
				self.revoked_by = frappe.session.user
		elif self.revoke_status == "Active":
			self.revoked_date = None
			self.revoked_by = None

	def after_insert(self):
		recompute_seats_for(self.saas_application)

	def on_update(self):
		recompute_seats_for(self.saas_application)
		old = self.get_doc_before_save()
		if old and old.saas_application and old.saas_application != self.saas_application:
			recompute_seats_for(old.saas_application)

	def on_trash(self):
		recompute_seats_for(self.saas_application)


@frappe.whitelist()
def revoke_now(name: str, reason: str | None = None) -> dict:
	doc = frappe.get_doc("SaaS Access", name)
	doc.check_permission("write")
	doc.revoke_status = "Revoked"
	doc.revoked_date = nowdate()
	doc.revoked_by = frappe.session.user
	if reason:
		doc.revoke_reason = reason
	doc.save()
	return {"name": doc.name, "revoke_status": doc.revoke_status, "revoked_date": doc.revoked_date}


@frappe.whitelist()
def autocomplete_tier_or_plan(saas_application: str | None = None) -> list[str]:
	"""Return distinct tier_or_plan values for autosuggest. Scoped to one app if given."""
	filters = {"tier_or_plan": ("not in", ["", None])}
	if saas_application:
		filters["saas_application"] = saas_application
	rows = frappe.get_all(
		"SaaS Access",
		filters=filters,
		fields=["tier_or_plan"],
		distinct=True,
		order_by="tier_or_plan",
	)
	return [r.tier_or_plan for r in rows if r.tier_or_plan]
