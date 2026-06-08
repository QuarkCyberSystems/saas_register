"""SaaS Access Matrix — pivot of Employee × SaaS Application.

Each cell encodes the employee's revoke_status for that app:
  • Green ✓  ──  Active
  • Yellow ⏳ ──  Pending Revoke / In Progress
  • Red ✗   ──  Revoked
  • blank   ──  no access
The last column counts how many apps the employee currently has Active access to.

Filters: department, employee status, include_revoked.
"""

from __future__ import annotations

import frappe
from frappe import _


# Cell encoding for the matrix. The .js file re-styles these via the formatter.
CELL = {
	"Active": "✓",
	"Pending Revoke": "⏳",
	"In Progress": "⏳",
	"Revoked": "✗",
}


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})

	apps = _get_apps()
	employees = _get_employees(filters)
	matrix = _get_matrix(filters)

	columns = _build_columns(apps)
	rows = _build_rows(employees, apps, matrix, filters)
	summary = _build_summary(employees, apps, rows)
	chart = _build_chart(apps, rows)

	return columns, rows, None, chart, summary


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


def _get_apps() -> list[dict]:
	return frappe.get_all(
		"SaaS Application",
		filters={"status": ("!=", "Kill-Replace")},
		fields=["name", "app_name", "status"],
		order_by="app_name asc",
	)


def _get_employees(filters: dict) -> list[dict]:
	emp_filters: dict = {}
	if filters.get("department"):
		emp_filters["department"] = filters["department"]
	if filters.get("employee_status"):
		emp_filters["status"] = filters["employee_status"]
	else:
		# Default: show Active + recently Left employees so offboarding gaps are visible
		emp_filters["status"] = ("in", ["Active", "Left"])

	return frappe.get_all(
		"Employee",
		filters=emp_filters,
		fields=["name", "employee_name", "department", "designation", "status"],
		order_by="department asc, employee_name asc",
		limit_page_length=0,
	)


def _get_matrix(filters: dict) -> dict[tuple[str, str], dict]:
	"""(employee, saas_application) -> {revoke_status, tier_name}"""
	include_revoked = bool(filters.get("include_revoked"))
	access_filters: dict = {}
	if not include_revoked:
		access_filters["revoke_status"] = ("!=", "Revoked")

	rows = frappe.get_all(
		"SaaS Access",
		filters=access_filters,
		fields=["employee", "saas_application", "revoke_status", "tier_or_plan.tier_name as tier_name"],
		limit_page_length=0,
	)
	out: dict[tuple[str, str], dict] = {}
	for r in rows:
		# If multiple rows exist (shouldn't, but defensively), keep the most "permissive" status.
		key = (r.employee, r.saas_application)
		prior = out.get(key)
		if prior is None or _status_priority(r.revoke_status) < _status_priority(prior["revoke_status"]):
			out[key] = {"revoke_status": r.revoke_status, "tier_name": r.tier_name}
	return out


def _status_priority(s: str | None) -> int:
	"""Lower number = preferred to display. Active beats Pending beats Revoked."""
	return {"Active": 0, "Pending Revoke": 1, "In Progress": 1, "Revoked": 2}.get(s or "", 9)


# ---------------------------------------------------------------------------
# Columns / rows / summary / chart
# ---------------------------------------------------------------------------


def _build_columns(apps: list[dict]) -> list[dict]:
	cols: list[dict] = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
	]
	for a in apps:
		# The fieldname is the app's `name` (e.g. SAAS-0008) so filtering / parsing is stable.
		# The label is the human app_name.
		cols.append(
			{
				"label": a.app_name,
				"fieldname": a.name,
				"fieldtype": "Data",
				"width": 90,
				"align": "center",
			}
		)
	cols.append(
		{"label": _("Apps"), "fieldname": "_apps_active", "fieldtype": "Int", "width": 70}
	)
	return cols


def _build_rows(
	employees: list[dict],
	apps: list[dict],
	matrix: dict[tuple[str, str], dict],
	filters: dict,
) -> list[dict]:
	rows: list[dict] = []
	for emp in employees:
		row: dict = {
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"department": emp.department,
			"status": emp.status,
		}
		active_count = 0
		for a in apps:
			cell = matrix.get((emp.name, a.name))
			if not cell:
				row[a.name] = ""
				continue
			marker = CELL.get(cell["revoke_status"], "")
			tier = cell.get("tier_name") or ""
			# Encode status into the cell text so the .js formatter can style it.
			row[a.name] = f"{marker}|{cell['revoke_status']}|{tier}"
			if cell["revoke_status"] == "Active":
				active_count += 1
		row["_apps_active"] = active_count
		rows.append(row)

	# Hide rows with no access at all (unless `include_no_access` filter says otherwise)
	if not filters.get("include_no_access"):
		rows = [r for r in rows if r["_apps_active"] > 0 or r["status"] == "Left"]

	return rows


def _build_summary(employees: list[dict], apps: list[dict], rows: list[dict]) -> list[dict]:
	total_employees = len(employees)
	rows_with_access = len(rows)
	total_apps = len(apps)
	total_grants = sum(r.get("_apps_active", 0) for r in rows)

	left_with_open_revoke = 0
	for r in rows:
		if r.get("status") == "Left":
			# any pending revoke cell?
			for k, v in r.items():
				if isinstance(v, str) and "|" in v and ("Pending Revoke" in v or "In Progress" in v):
					left_with_open_revoke += 1
					break

	return [
		{"value": total_employees, "label": _("Employees"), "datatype": "Int", "indicator": "Blue"},
		{"value": total_apps, "label": _("Applications"), "datatype": "Int", "indicator": "Blue"},
		{"value": total_grants, "label": _("Active Access Rows"), "datatype": "Int", "indicator": "Green"},
		{"value": left_with_open_revoke, "label": _("Left w/ Open Revoke"), "datatype": "Int", "indicator": "Red"},
	]


def _build_chart(apps: list[dict], rows: list[dict]) -> dict | None:
	if not apps or not rows:
		return None
	app_active: dict[str, int] = {a.name: 0 for a in apps}
	for r in rows:
		for a in apps:
			v = r.get(a.name) or ""
			if isinstance(v, str) and v.startswith(CELL["Active"]):
				app_active[a.name] += 1

	labels = [a.app_name for a in apps]
	values = [app_active[a.name] for a in apps]

	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Active Users"), "values": values}],
		},
		"type": "bar",
		"colors": ["#28A745"],
	}
