"""Employee lifecycle hooks for the SaaS Register app.

When an Employee's status transitions to a terminal state (e.g. ``Left``), one
ToDo is created **per (active SaaS Access × app's offboarding step)** for the
User resolved from the step's ``assigned_role_key``. All active access rows for
the employee are flipped to ``Pending Revoke`` so they show up on the IT/HR
queue.

Why ToDos instead of Project + Task: SaaS offboarding is a stream of small
single-owner actions, not a project. ToDos land in each owner's inbox and bell
notification with no project-management overhead, which is what the HR team
asked for.
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
	"""doc_events handler bound to Employee `on_update` and `after_insert`."""
	if not _is_terminal(doc.status):
		return

	if not _just_transitioned(doc):
		return

	# Never let offboarding logic block the Employee save itself.
	try:
		_create_offboarding_todos(doc)
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


def _create_offboarding_todos(employee) -> None:
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
	hr_fallback = settings.hr_manager

	todos_created = 0
	rotations = 0

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
			# Always create at least one fallback ToDo per app so nothing slips through.
			steps = [
				{
					"step_description": "Revoke account in admin panel",
					"assigned_role_key": "it_manager",
					"estimated_minutes": 5,
					"requires_password_rotation": 0,
					"sequence": 1,
				}
			]

		for step in steps:
			assignee = resolve_role_user(step["assigned_role_key"], employee.name) or hr_fallback
			if not assignee:
				continue

			description = (
				f"<b>{row.app_name or row.saas_application}</b> — {step['step_description']}<br>"
				f"<i>Offboarding for {employee.employee_name or employee.name}</i>"
			)
			if step.get("requires_password_rotation"):
				description += " <span style='color:#E53935'><b>· password rotation required</b></span>"

			created = _create_or_update_todo(
				assignee=assignee,
				ref_type="SaaS Access",
				ref_name=row.name,
				description=description,
				due=due,
				priority="High" if step.get("requires_password_rotation") else "Medium",
			)
			if created:
				todos_created += 1
				if step.get("requires_password_rotation"):
					rotations += 1

	_notify_owner(employee, len(access_rows), todos_created, rotations)


def _create_or_update_todo(
	assignee: str,
	ref_type: str,
	ref_name: str,
	description: str,
	due: str,
	priority: str = "Medium",
) -> bool:
	"""Create a fresh ToDo per offboarding step.

	We deliberately bypass `frappe.desk.form.assign_to.add` here — that helper
	dedupes on (user, ref) so multiple steps for the same assignee on the same
	SaaS Access row collapse into a single ToDo. For offboarding we want one
	ToDo per step so each action is independently checkable in the assignee's
	inbox.
	"""
	try:
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": assignee,
				"assigned_by": frappe.session.user,
				"description": description,
				"reference_type": ref_type,
				"reference_name": ref_name,
				"date": due,
				"priority": priority,
				"status": "Open",
			}
		)
		todo.insert(ignore_permissions=True)
		return True
	except Exception:
		frappe.log_error(
			title=f"saas_register: ToDo create failed for {ref_type} {ref_name} → {assignee}",
			message=frappe.get_traceback(),
		)
		return False


def _notify_owner(employee, app_count: int, todo_count: int, rotations: int) -> None:
	settings = frappe.get_cached_doc("SaaS Register Settings")
	# v3: offboarding_alert_recipients is a comma-separated email list. Fall back
	# to it_manager's user (which is an email anyway in Frappe) if not configured.
	raw = (settings.offboarding_alert_recipients or "").strip()
	recipients = [r.strip() for r in raw.split(",") if r.strip()]
	if not recipients and settings.it_manager:
		recipients = [settings.it_manager]
	if not recipients:
		return

	frappe.sendmail(
		recipients=recipients,
		subject=_("Offboarding ToDos created for {0}").format(employee.employee_name or employee.name),
		message=_(
			"<p>Offboarding ToDos have been created.</p>"
			"<ul>"
			"<li>Employee: <b>{employee}</b> ({status})</li>"
			"<li>Apps with active access: {apps}</li>"
			"<li>ToDos created: {todos} ({rotations} require password rotation)</li>"
			"</ul>"
			"<p>Open <a href='/app/todo'>/app/todo</a> to see the queue.</p>"
		).format(
			employee=frappe.utils.escape_html(employee.employee_name or employee.name),
			status=frappe.utils.escape_html(employee.status or ""),
			apps=app_count,
			todos=todo_count,
			rotations=rotations,
		),
		now=False,
		delayed=True,
	)
