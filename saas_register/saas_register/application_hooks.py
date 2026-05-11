"""Scheduled jobs operating on SaaS Applications.

Wired in hooks.py via `scheduler_events.daily`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, today


def check_expiring_apps():
	"""Daily: for every Active SaaS Application whose renewal_date == today,
	drop a ToDo on the business owner and Felix (with HR as fallback).

	Idempotent: skips if a ToDo already exists for the same (app, user) created
	today, so re-running the job within the same day doesn't duplicate.
	"""
	settings = frappe.get_cached_doc("SaaS Register Settings")
	today_d = today()

	apps = frappe.get_all(
		"SaaS Application",
		filters={"status": ("!=", "Kill-Replace"), "renewal_date": today_d},
		fields=["name", "app_name", "business_owner", "renewal_date"],
	)

	if not apps:
		return

	for app in apps:
		recipients = _resolve_recipients(app, settings)
		if not recipients:
			continue

		description = (
			f"<b>Renewal due TODAY</b>: {frappe.utils.escape_html(app.app_name)}.<br>"
			f"Verify, renew, or cancel before billing fires."
		)

		for user in recipients:
			if _todo_already_exists(app.name, user, today_d):
				continue
			_assign_todo(user, app.name, description, today_d)


def _resolve_recipients(app: dict, settings) -> list[str]:
	recipients: list[str] = []

	if app.get("business_owner"):
		owner_user = frappe.db.get_value("Employee", app["business_owner"], "user_id")
		if owner_user:
			recipients.append(owner_user)

	if settings.it_manager and settings.it_manager not in recipients:
		recipients.append(settings.it_manager)

	if not recipients and settings.hr_manager:
		recipients.append(settings.hr_manager)

	return recipients


def _todo_already_exists(app_name: str, user: str, today_d: str) -> bool:
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": "SaaS Application",
				"reference_name": app_name,
				"allocated_to": user,
				"creation": (">=", today_d),
			},
		)
	)


def _assign_todo(user: str, app_name: str, description: str, due: str) -> None:
	from frappe.desk.form.assign_to import add as assign

	try:
		assign(
			{
				"assign_to": [user],
				"doctype": "SaaS Application",
				"name": app_name,
				"description": description,
				"date": due,
				"priority": "High",
			}
		)
	except Exception:
		frappe.log_error(
			title=f"saas_register: renewal ToDo failed for {app_name} → {user}",
			message=frappe.get_traceback(),
		)
