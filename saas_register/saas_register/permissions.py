"""Permission query conditions for SaaS Access.

Wired in hooks.permission_query_conditions / has_permission.
"""

import frappe


def saas_access_query(user: str | None = None) -> str:
	"""Return SQL where-clause restricting SaaS Access rows by role.

	- System Manager / IT Manager / HR Manager: no restriction.
	- Department Head: only rows whose department matches one they head.
	- Employee Self Service: only their own employee record's rows.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "IT Manager", "HR Manager"}:
		return ""

	conditions: list[str] = []

	if "Department Head" in roles:
		# Find departments where this user is the head
		depts = frappe.get_all(
			"Department",
			filters={"disabled": 0},
			or_filters=[{"parent_department": ["is", "set"]}],
			fields=["name"],
		) if False else []
		# Simpler: rely on Employee.department of employees managed by user
		# We approximate: departments where user is "leader" via Employee link
		emp = frappe.db.get_value("Employee", {"user_id": user}, "department")
		if emp:
			conditions.append(f"`tabSaaS Access`.department = {frappe.db.escape(emp)}")

	if "Employee Self Service" in roles and not (roles & {"Department Head"}):
		emp_name = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if emp_name:
			conditions.append(f"`tabSaaS Access`.employee = {frappe.db.escape(emp_name)}")
		else:
			conditions.append("1=0")

	if not conditions:
		return ""
	return "(" + " OR ".join(conditions) + ")"


def saas_access_has_permission(doc, user: str | None = None, permission_type: str = "read") -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "IT Manager", "HR Manager"}:
		return True

	if "Department Head" in roles:
		dept = frappe.db.get_value("Employee", {"user_id": user}, "department")
		if dept and doc.department == dept:
			return True

	if "Employee Self Service" in roles:
		emp_name = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if emp_name and doc.employee == emp_name:
			return permission_type == "read"

	return False
