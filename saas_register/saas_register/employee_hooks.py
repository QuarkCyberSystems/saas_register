"""Employee lifecycle hooks for the SaaS Register app.

When an Employee's status transitions to a terminal state (e.g. ``Left``),
ToDos are created **per (active SaaS Access × app's offboarding step)** for the
User resolved from the step's ``assigned_role_key``. Active access rows are
flipped to ``Pending Revoke`` so they show up on the IT/HR queue immediately.

Service accounts and shared mailboxes (rows with ``revoke_on_offboarding = 0``)
are skipped from ToDo creation but listed in the IT Manager's summary email so
they remain visible for manual handling.

Why ToDos instead of Project + Task: SaaS offboarding is a stream of small
single-owner actions, not a project. ToDos land in each owner's inbox and bell
notification with no project-management overhead, which is what the HR team
asked for.

We also cascade Employee.department changes onto the denormalised
``SaaS Access.department`` field via a bulk SQL update — used by the HR-Manager
permission query and the Spend-by-Department report.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, today

from saas_register.saas_register.doctype.saas_register_settings.saas_register_settings import (
	resolve_role_user,
)


# Employee.status values that mean "this person has left and access must be revoked".
# Stock ERPNext only ships with "Left"; HRMS keeps the same enum. We also accept
# Resigned / Terminated for customers who add those values via Custom Field.
TERMINAL_STATUSES = {"Left", "Resigned", "Terminated"}


def on_employee_update(doc, method=None):
	"""doc_events handler bound to Employee `on_update` and `after_insert`."""
	# Always cascade department changes — cheap and unrelated to offboarding.
	_cascade_department_change(doc)

	if not _is_terminal(doc.status):
		return

	if not _just_transitioned(doc):
		return

	# Skip during bulk imports so loading historical leavers doesn't fire dozens
	# of stale offboarding notifications.
	if getattr(frappe.flags, "in_import", False) or getattr(frappe.flags, "in_migrate", False):
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
	# Tolerate customer custom values containing those tokens (e.g. "Left - Voluntary").
	return any(token.lower() in status.lower() for token in TERMINAL_STATUSES)


def _just_transitioned(doc) -> bool:
	"""True only if `status` changed in the save we are currently committing."""
	old = doc.get_doc_before_save()
	if not old:
		# Insert with a terminal status — still trigger.
		return True
	return (old.get("status") or "") != (doc.get("status") or "")


def _cascade_department_change(employee) -> None:
	"""Mirror Employee.department onto the denormalised SaaS Access.department.

	Bulk SQL — not a per-row Frappe ORM update — so we don't fire SaaS Access
	on_update hooks for every row. The denormalised field powers the HR Manager
	permission query and Spend-by-Department aggregation.
	"""
	old = employee.get_doc_before_save()
	if not old:
		return
	old_dept = old.get("department")
	new_dept = employee.department
	if (old_dept or "") == (new_dept or ""):
		return

	# Single UPDATE — no per-row hook cascade.
	frappe.db.sql(
		"""
		UPDATE `tabSaaS Access`
		SET `department` = %s, `modified` = %s
		WHERE `employee` = %s
		""",
		(new_dept, frappe.utils.now(), employee.name),
	)


def _create_offboarding_todos(employee) -> None:
	settings = frappe.get_cached_doc("SaaS Register Settings")

	# Idempotency: if we created offboarding ToDos for this employee within the
	# configured window, don't create another batch. Handles re-saves of the same
	# Employee, and status flips (e.g. Left → Active → Left) inside the window.
	window_days = int(settings.offboarding_idempotency_window_days or 7)
	if _recent_offboarding_exists(employee.name, window_days):
		frappe.logger().info(
			f"saas_register: skipping offboarding for {employee.name} — "
			f"existing ToDos within {window_days}-day window."
		)
		return

	all_access = frappe.get_all(
		"SaaS Access",
		filters={"employee": employee.name, "revoke_status": "Active"},
		fields=["name", "saas_application", "app_name", "revoke_on_offboarding"],
	)

	if not all_access:
		_notify_summary(
			employee=employee,
			settings=settings,
			revocable=[],
			skipped=[],
			todos_by_assignee={},
		)
		return

	# Split by the revoke_on_offboarding flag. Skipped rows are shared service
	# accounts / bot users / break-glass admins — they need a human to transfer
	# ownership, not an auto-revoke.
	revocable = [a for a in all_access if a.revoke_on_offboarding]
	skipped = [a for a in all_access if not a.revoke_on_offboarding]

	sla_days = int(settings.default_offboarding_sla_days or 1)
	due = add_days(today(), sla_days)
	hr_fallback = settings.hr_manager
	todos_by_assignee: dict[str, list[str]] = defaultdict(list)

	for row in revocable:
		# Flip status so it shows up in queues immediately.
		try:
			frappe.db.set_value(
				"SaaS Access",
				row.name,
				{"revoke_status": "Pending Revoke"},
				update_modified=True,
			)
		except Exception:
			frappe.log_error(
				title=f"saas_register: failed to flip revoke_status on {row.name}",
				message=frappe.get_traceback(),
			)
			# One bad row must not block the rest.
			continue

		steps = frappe.get_all(
			"SaaS Offboarding Step",
			filters={"parent": row.saas_application, "parenttype": "SaaS Application"},
			fields=["step_description", "assigned_role_key", "estimated_minutes", "requires_password_rotation", "sequence"],
			order_by="sequence asc, idx asc",
		)
		if not steps:
			steps = [_generic_step()]

		for step in steps:
			try:
				assignee = resolve_role_user(step["assigned_role_key"], employee.name) or hr_fallback
				if not assignee:
					continue

				description = _format_todo_description(row, step, employee)
				priority = "High" if step.get("requires_password_rotation") else "Medium"

				if _create_todo(assignee, "SaaS Access", row.name, description, due, priority):
					todos_by_assignee[assignee].append(
						f"{row.app_name or row.saas_application}: {step['step_description']}"
					)
			except Exception:
				frappe.log_error(
					title=f"saas_register: ToDo creation failed for {row.name}",
					message=frappe.get_traceback(),
				)
				# Continue — one bad app must not block others.

	_notify_summary(
		employee=employee,
		settings=settings,
		revocable=revocable,
		skipped=skipped,
		todos_by_assignee=todos_by_assignee,
	)


def _recent_offboarding_exists(employee: str, window_days: int) -> bool:
	"""True if any SaaS-Access-linked ToDo was created within the window for an
	access row owned by this employee. Used as the idempotency guard.
	"""
	cutoff = add_days(today(), -window_days)
	access_names = frappe.get_all(
		"SaaS Access",
		filters={"employee": employee},
		pluck="name",
	)
	if not access_names:
		return False
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": "SaaS Access",
				"reference_name": ("in", access_names),
				"creation": (">=", cutoff),
			},
		)
	)


def _generic_step() -> dict:
	return {
		"step_description": "Revoke account (no specific playbook)",
		"assigned_role_key": "it_manager",
		"estimated_minutes": 10,
		"requires_password_rotation": 0,
		"sequence": 1,
	}


def _format_todo_description(row, step, employee) -> str:
	description = (
		f"<b>{row.app_name or row.saas_application}</b> — {step['step_description']}<br>"
		f"<i>Offboarding for {employee.employee_name or employee.name}</i>"
	)
	if step.get("requires_password_rotation"):
		description += " <span style='color:#E53935'><b>· password rotation required</b></span>"
	return description


def _create_todo(
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
	ToDo per step so each action is independently checkable.
	"""
	try:
		frappe.get_doc(
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
		).insert(ignore_permissions=True)
		return True
	except Exception:
		frappe.log_error(
			title=f"saas_register: ToDo create failed for {ref_type} {ref_name} → {assignee}",
			message=frappe.get_traceback(),
		)
		return False


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def _notify_summary(
	*,
	employee,
	settings,
	revocable: list,
	skipped: list,
	todos_by_assignee: dict[str, list[str]],
) -> None:
	"""Send:
	- one summary email per assignee with their full task list, and
	- one summary email to offboarding_alert_recipients (IT Manager) with the
	  full picture, including the list of skipped service-account rows.
	"""
	employee_label = employee.employee_name or employee.name

	# Per-assignee digest — replaces the firehose of one email per ToDo.
	for assignee, tasks in todos_by_assignee.items():
		try:
			frappe.sendmail(
				recipients=[assignee],
				subject=_("SaaS offboarding tasks for {0}").format(employee_label),
				message=_format_assignee_email(employee_label, tasks),
				now=False,
				delayed=True,
			)
		except Exception:
			frappe.log_error(
				title=f"saas_register: per-assignee email failed for {assignee}",
				message=frappe.get_traceback(),
			)

	# IT Manager / alert recipients summary
	raw = (settings.offboarding_alert_recipients or "").strip()
	recipients = [r.strip() for r in raw.split(",") if r.strip()]
	if not recipients and settings.it_manager:
		recipients = [settings.it_manager]
	if not recipients:
		return

	total_todos = sum(len(v) for v in todos_by_assignee.values())
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=_("Offboarding workflow for {0}").format(employee_label),
			message=_format_manager_email(
				employee_label=employee_label,
				status=employee.status or "",
				revocable=revocable,
				skipped=skipped,
				todo_count=total_todos,
			),
			now=False,
			delayed=True,
		)
	except Exception:
		frappe.log_error(
			title="saas_register: IT Manager summary email failed",
			message=frappe.get_traceback(),
		)


def _format_assignee_email(employee_label: str, tasks: list[str]) -> str:
	task_lines = "".join(f"<li>{frappe.utils.escape_html(t)}</li>" for t in tasks)
	return _(
		"<p>SaaS offboarding tasks have been created in your queue for "
		"<b>{employee}</b>.</p>"
		"<ul>{tasks}</ul>"
		"<p>Open <a href='/app/todo?status=Open'>/app/todo</a> to work through them.</p>"
	).format(employee=frappe.utils.escape_html(employee_label), tasks=task_lines)


def _format_manager_email(
	*,
	employee_label: str,
	status: str,
	revocable: list,
	skipped: list,
	todo_count: int,
) -> str:
	skipped_html = (
		"".join(
			f"<li>{frappe.utils.escape_html(s.app_name or s.saas_application)} "
			f"<i>(revoke_on_offboarding unchecked)</i></li>"
			for s in skipped
		)
		or "<li><i>(none)</i></li>"
	)
	return _(
		"<p>Offboarding workflow has been triggered.</p>"
		"<ul>"
		"<li>Employee: <b>{employee}</b> ({status})</li>"
		"<li>Apps to revoke: <b>{revocable}</b></li>"
		"<li>ToDos created: <b>{todos}</b></li>"
		"</ul>"
		"<p><b>Apps skipped — need manual handling (transfer ownership):</b></p>"
		"<ul>{skipped}</ul>"
		"<p>Queue: <a href='/app/todo?status=Open'>/app/todo</a></p>"
	).format(
		employee=frappe.utils.escape_html(employee_label),
		status=frappe.utils.escape_html(status),
		revocable=len(revocable),
		todos=todo_count,
		skipped=skipped_html,
	)
