import frappe
from frappe.model.document import Document
from frappe.utils import get_first_day, getdate, now


class SaaSMonthlyCost(Document):
	def validate(self):
		# Normalize `month` to first-of-month so (parent, month) uniqueness works.
		if self.month:
			self.month = get_first_day(getdate(self.month))

		# Stamp audit fields on every save.
		self.last_edited_by = frappe.session.user
		self.last_edited_at = now()
