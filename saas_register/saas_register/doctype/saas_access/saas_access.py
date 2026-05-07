import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from saas_register.saas_register.doctype.saas_application.saas_application import (
	recompute_seats_for,
)


REVOKED_STATES = {"Pending Revoke", "In Progress", "Revoked"}


class SaaSAccess(Document):
	def validate(self):
		self.enforce_unique_active_access()
		self.validate_tier_against_app()
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

	def validate_tier_against_app(self):
		"""If a tier is set, hard-validate it belongs to the chosen application
		and auto-derive `monthly_cost_share` from that tier's per-seat cost when
		the user hasn't filled it in. The Link field guarantees the tier doc
		exists; we still must check it points at the same app."""
		if not self.tier:
			return

		tier = frappe.db.get_value(
			"SaaS Application Tier",
			self.tier,
			["saas_application", "tier_name", "seats_paid", "monthly_cost", "currency"],
			as_dict=True,
		)

		if not tier:
			# Link target was deleted between client load and save.
			frappe.throw(
				_("Tier {0} no longer exists.").format(frappe.bold(self.tier)),
				title=_("Tier Not Found"),
			)

		if tier.saas_application != self.saas_application:
			frappe.throw(
				_("Tier {0} belongs to {1}, not {2}.").format(
					frappe.bold(tier.tier_name),
					frappe.bold(tier.saas_application),
					frappe.bold(self.saas_application),
				),
				title=_("Tier / Application Mismatch"),
			)

		# Auto-derive per-seat cost share if user left it blank or zero.
		if not flt(self.monthly_cost_share) and flt(tier.seats_paid):
			self.monthly_cost_share = flt(tier.monthly_cost) / flt(tier.seats_paid)

		if not self.currency and tier.currency:
			self.currency = tier.currency

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
