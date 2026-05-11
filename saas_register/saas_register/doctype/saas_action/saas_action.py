import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SaaSAction(Document):
	def validate(self):
		self._enforce_done_savings()

	def _enforce_done_savings(self):
		"""Per v3 §3.4 lifecycle: actual_monthly_saving must be set when Done."""
		if self.status != "Done":
			return
		if not flt(self.actual_monthly_saving):
			frappe.throw(
				_("Actual Monthly Saving is required when an Action is marked Done."),
				title=_("Saving required"),
			)
