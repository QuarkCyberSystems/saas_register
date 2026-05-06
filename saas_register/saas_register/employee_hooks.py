"""Employee lifecycle hooks for the SaaS Register app.

When an Employee's status transitions to a terminal state (e.g. ``Left``), an
offboarding Project is created with one Task per (active SaaS Access × app's
offboarding step). All active access rows for the employee are flipped to
``Pending Revoke`` so they show up on Felix's queue.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, today

from saas_register.saas_register.doctype.saas_register_settings.saas_register_settings import (
	resolve_role_user,
)


# Employee.status values that mean "this person has left and access must be revoked".
# Stock ERPNext only ships with "Left", but customers often add custom values like
# "Resigned" / "Terminated" — we accept any value containing those words.
TERMINAL_STATUSES = {"Left", "Resigned", "Terminated"}


def on_employee_update(doc, method=None):
	"""doc_events handler bound to Employee `on_update` in hooks.py."""
	if not _is_terminal(doc.status):
		return

	if not _just_transitioned(doc):
		return

	# Never let offboarding logic block the Employee save itself.
	try:
		_create_offboarding_workflow(doc)
	except Exception:
		frappe.log_error(
			title="SaaS Register: offboarding trigger failed",
			message=frappe.get_traceback(),
		)


def _is_terminal(status: str | None) -> bool:
	if not status:
		return False
	if status in TERMINAL_STATUSES:
		return True
	return any(token.lower() in status.lower() for token in TERMINAL_STATUSES)


def _just_transitioned(doc) -> bool:
	"""True only if `status` changed in the save we are currently committing."""
	old = doc.get_doc_before_save()
	if not old:
		# Insert with a terminal status — still trigger.
		return True
	return (old.get("status") or "") != (doc.get("status") or "")


def _create_offboarding_workflow(employee) -> None:
	access_rows = frappe.get_all(
		"SaaS Access",
		filters={"employee": employee.name, "revoke_status": "Active"},
		fields=["name", "saas_application", "app_name"],
	)

	if not access_rows:
		return

	settings = frappe.get_cached_doc("SaaS Register Settings")
	sla_days = int(settings.default_offboarding_sla_days or 1)
	due = add_days(today(), sla_days)

	project = frappe.new_doc("Project")
	project.project_name = _("Offboarding — {0} — {1}").format(employee.employee_name or employee.name, today())
	project.expected_start_date = today()
	project.expected_end_date = due
	if settings.default_cost_center:
		project.cost_center = settings.default_cost_center
	if settings.felix_user:
		project.owner = settings.felix_user
	project.insert(ignore_permissions=True)

	tasks_created = 0
	password_rotation_tasks = 0

	for row in access_rows:
		# Flip status so it shows up in queues immediately.
		frappe.db.set_value(
			"SaaS Access",
			row.name,
			{"revoke_status": "Pending Revoke"},
			update_modified=True,
		)

		steps = frappe.get_all(
			"SaaS Offboarding Step",
			filters={"parent": row.saas_application, "parenttype": "SaaS Application"},
			fields=["step_description", "assigned_role_key", "estimated_minutes", "requires_password_rotation", "sequence"],
			order_by="sequence asc, idx asc",
		)

		if not steps:
			# Always create at least one fallback task per app so nothing slips through.
			steps = [
				{
					"step_description": "Revoke account in admin panel",
					"assigned_role_key": "felix",
					"estimated_minutes": 5,
					"requires_password_rotation": 0,
					"sequence": 1,
				}
			]

		for step in steps:
			task = frappe.new_doc("Task")
			task.subject = f"{row.app_name or row.saas_application} — {step['step_description']}"
			task.project = project.name
			task.exp_start_date = today()
			task.exp_end_date = due
			task.priority = "High"
			if step.get("estimated_minutes"):
				task.expected_time = float(step["estimated_minutes"]) / 60.0

			assignee = resolve_role_user(step["assigned_role_key"], employee.name)
			task.insert(ignore_permissions=True)

			if assignee:
				from frappe.desk.form.assign_to import add as assign

				assign(
					{
						"assign_to": [assignee],
						"doctype": "Task",
						"name": task.name,
						"description": task.subject,
						"date": due,
					}
				)

			if step.get("requires_password_rotation"):
				_add_tag(task.doctype, task.name, "password-rotation")
				password_rotation_tasks += 1

			tasks_created += 1

	_notify_owner(employee, project, len(access_rows), tasks_created, password_rotation_tasks)


def _add_tag(doctype: str, docname: str, tag: str) -> None:
	try:
		from frappe.desk.doctype.tag.tag import DocTags

		DocTags(doctype).add(docname, tag)
	except Exception:
		# Tagging is best-effort
		pass


def _notify_owner(employee, project, app_count: int, task_count: int, rotations: int) -> None:
	settings = frappe.get_cached_doc("SaaS Register Settings")
	recipient = settings.notify_email or settings.felix_user
	if not recipient:
		return

	frappe.sendmail(
		recipients=[recipient],
		subject=_("Offboarding workflow created for {0}").format(employee.employee_name or employee.name),
		message=_(
			"<p>An offboarding workflow has been created.</p>"
			"<ul>"
			"<li>Employee: <b>{employee}</b> ({status})</li>"
			"<li>Project: <a href='/app/project/{project}'>{project}</a></li>"
			"<li>Apps: {apps}</li>"
			"<li>Tasks: {tasks} ({rotations} require password rotation)</li>"
			"</ul>"
		).format(
			employee=frappe.utils.escape_html(employee.employee_name or employee.name),
			status=frappe.utils.escape_html(employee.status or ""),
			project=project.name,
			apps=app_count,
			tasks=task_count,
			rotations=rotations,
		),
		now=False,
		delayed=True,
	)
