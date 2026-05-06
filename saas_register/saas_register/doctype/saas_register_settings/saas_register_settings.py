import frappe
from frappe.model.document import Document


ROLE_KEYS = ("felix", "tech_lead", "dept_head", "hr")


class SaaSRegisterSettings(Document):
	pass


def resolve_role_user(role_key: str, employee: str | None = None) -> str | None:
	"""Map a role_key → a User. Falls back to None if unset.

	Department head resolution:
	- if `employee` is given, look up Department.lft head and resolve user_id of that Employee
	- otherwise fall back to settings.dept_head_default_user
	"""
	settings = frappe.get_cached_doc("SaaS Register Settings")

	mapping = {
		"felix": settings.felix_user,
		"tech_lead": settings.tech_lead_user,
		"hr": settings.hr_user,
	}

	if role_key in mapping:
		return mapping[role_key]

	if role_key == "dept_head":
		if employee:
			dept = frappe.db.get_value("Employee", employee, "department")
			if dept:
				# Department head Employee → user
				head_emp = frappe.db.get_value("Department", dept, "head_of_department") if frappe.db.has_column("Department", "head_of_department") else None
				if head_emp:
					user = frappe.db.get_value("Employee", head_emp, "user_id")
					if user:
						return user
		return settings.dept_head_default_user

	return None
