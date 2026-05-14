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
		self.enforce_tier_belongs_to_app()
		self.enforce_tier_required_when_tiers_exist()
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

	def enforce_tier_belongs_to_app(self):
		"""Picker filter already does this on the form; revalidate server-side
		so REST/import callers can't create a SaaS Access pointing at a tier
		owned by a different app."""
		if not self.tier_or_plan:
			return
		tier_app = frappe.db.get_value("SaaS Tier", self.tier_or_plan, "saas_application")
		if tier_app and tier_app != self.saas_application:
			frappe.throw(
				_("Tier {0} belongs to {1}, not {2}.").format(
					frappe.bold(self.tier_or_plan),
					frappe.bold(tier_app),
					frappe.bold(self.saas_application),
				),
				title=_("Tier / App Mismatch"),
			)

	def enforce_tier_required_when_tiers_exist(self):
		"""If the parent app defines any active tiers, this access must pick one.
		Apps without tiers (the majority — most Shared apps are single-tier)
		stay unaffected."""
		if self.tier_or_plan:
			return
		has_tiers = frappe.db.exists(
			"SaaS Tier",
			{"saas_application": self.saas_application, "is_active": 1},
		)
		if has_tiers:
			frappe.throw(
				_("Pick a tier — {0} has tier rows defined.").format(
					frappe.bold(self.app_name or self.saas_application)
				),
				title=_("Tier Required"),
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
