import frappe
from frappe.model.document import Document


# Aligned with v3 spec §2.8
ROLE_KEYS = ("it_manager", "tech_lead", "finance_manager", "hr_manager", "dept_head")


class SaaSRegisterSettings(Document):
	pass


def resolve_role_user(role_key: str, employee: str | None = None) -> str | None:
	"""Map a role_key → a User. Falls back to None if unset.

	Department head resolution:
	- if `employee` is given, look up the head of that department's Employee → user_id
	- otherwise fall back to settings.dept_head
	"""
	settings = frappe.get_cached_doc("SaaS Register Settings")

	mapping = {
		"it_manager": settings.it_manager,
		"tech_lead": settings.tech_lead,
		"finance_manager": settings.finance_manager,
		"hr_manager": settings.hr_manager,
	}

	if role_key in mapping:
		return mapping[role_key]

	if role_key == "dept_head":
		if employee:
			dept = frappe.db.get_value("Employee", employee, "department")
			if dept and frappe.db.has_column("Department", "head_of_department"):
				head_emp = frappe.db.get_value("Department", dept, "head_of_department")
				if head_emp:
					user = frappe.db.get_value("Employee", head_emp, "user_id")
					if user:
						return user
		return settings.dept_head

	# Unknown role_key: fall back to it_manager so nothing slips through silently.
	return settings.it_manager
