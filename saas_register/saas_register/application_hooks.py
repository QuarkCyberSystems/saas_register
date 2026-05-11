"""Scheduled jobs operating on SaaS Applications.

Wired in hooks.py via `scheduler_events.daily`.

Two daily jobs:
- `check_expiring_apps`        — creates a ToDo on renewal_date day
- `emit_renewal_webhooks`      — POSTs to n8n at 30/14/7 days before renewal
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


WEBHOOK_PATH = "/saas/renewal-upcoming"


def check_expiring_apps():
	"""Daily: for every Active SaaS Application whose renewal_date == today,
	drop a ToDo on the business owner and IT Manager (with HR as fallback).

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


def emit_renewal_webhooks():
	"""Daily: for every Active SaaS Application whose renewal_date is exactly
	30 / 14 / 7 days out, POST a payload to the n8n webhook base URL if set.

	v3 §3.5 event #3. We POST manually (not via Frappe's Webhook doctype) because
	the Webhook doctype only fires on docevents, not on date-relative scheduled
	conditions. If `n8n_webhook_base_url` is blank, the function is a no-op.
	"""
	settings = frappe.get_cached_doc("SaaS Register Settings")
	base = (settings.n8n_webhook_base_url or "").rstrip("/")
	if not base:
		return

	today_d = getdate(today())
	for days_out in (30, 14, 7):
		target_date = add_days(today_d, days_out)
		apps = frappe.get_all(
			"SaaS Application",
			filters={"status": ("!=", "Kill-Replace"), "renewal_date": target_date},
			fields=["name", "app_name", "renewal_date", "auto_renew", "business_owner", "monthly_cost", "currency"],
		)
		for app in apps:
			owner_email = None
			if app.business_owner:
				owner_email = frappe.db.get_value("Employee", app.business_owner, "company_email") or frappe.db.get_value(
					"Employee", app.business_owner, "user_id"
				)
			_post_renewal_webhook(
				base,
				{
					"app": app.name,
					"app_name": app.app_name,
					"renewal_date": str(app.renewal_date),
					"days_out": days_out,
					"auto_renew": bool(app.auto_renew),
					"business_owner": app.business_owner,
					"business_owner_email": owner_email,
					"monthly_cost": float(app.monthly_cost or 0),
					"currency": app.currency,
				},
			)


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


def _post_renewal_webhook(base_url: str, payload: dict) -> None:
	"""Background-friendly POST. Failures are logged but never raised — the
	scheduler must not blow up on a flaky n8n endpoint."""
	import requests

	url = base_url + WEBHOOK_PATH
	try:
		resp = requests.post(url, json=payload, timeout=5)
		if resp.status_code >= 400:
			frappe.log_error(
				title=f"saas_register: renewal webhook non-2xx ({resp.status_code})",
				message=f"URL: {url}\nPayload: {json.dumps(payload)}\nResponse: {resp.text[:500]}",
			)
	except Exception:
		frappe.log_error(
			title="saas_register: renewal webhook POST failed",
			message=frappe.get_traceback(),
		)
