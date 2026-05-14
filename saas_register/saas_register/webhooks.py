"""Webhook emission helper.

A single `build_payload(event_type, **kwargs)` builds every outbound webhook
payload, always injecting `triggered_by_user` and `event_timestamp`. Adding a
new event = adding a key to `_BUILDERS`; the audit-context fields are baked in
for every event, removing the risk of forgetting them on a new endpoint.

Outbound HTTP is performed via `post(payload, path)`. If
`SaaS Register Settings.n8n_webhook_base_url` is blank, all posts are no-ops —
the rest of the app keeps working unaffected.

Events emitted (Phase 1, per spec §3.5):
- `task_created`       — when an offboarding ToDo is created
- `action_opened`      — when a SaaS Action is created in `Open` status
- `renewal_upcoming`   — daily scheduler (already posted via application_hooks)
- `monthly_cost_updated` — when a SaaS Monthly Cost row is inserted/updated

The renewal_upcoming event currently lives in `application_hooks._post_renewal_webhook`
for legacy reasons; new events should use this helper.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import now


def build_payload(event_type: str, **kwargs: Any) -> dict:
	"""Compose an outbound webhook payload.

	Every payload carries `triggered_by_user` (the User who caused the event)
	and `event_timestamp` (ISO 8601, server clock). Both are non-negotiable —
	downstream n8n consumers rely on them for audit context.
	"""
	base = {
		"event_type": event_type,
		"triggered_by_user": frappe.session.user,
		"event_timestamp": str(now()),
	}
	builder = _BUILDERS.get(event_type)
	if builder:
		base.update(builder(**kwargs))
	else:
		base.update(kwargs)
	return base


def post(payload: dict, path: str = "/saas/event") -> None:
	"""POST the payload to n8n. Best-effort, never raises.

	No-op if `n8n_webhook_base_url` is blank — used to gate the integration
	without touching code.
	"""
	import requests

	base_url = (
		frappe.db.get_single_value("SaaS Register Settings", "n8n_webhook_base_url") or ""
	).rstrip("/")
	if not base_url:
		return

	url = base_url + path
	try:
		resp = requests.post(url, json=payload, timeout=5)
		if resp.status_code >= 400:
			frappe.log_error(
				title=f"saas_register: webhook non-2xx ({resp.status_code})",
				message=f"URL: {url}\nPayload: {json.dumps(payload)[:1000]}\nResponse: {resp.text[:500]}",
			)
	except Exception:
		frappe.log_error(
			title="saas_register: webhook POST failed",
			message=frappe.get_traceback(),
		)


# ---------------------------------------------------------------------------
# Builders — one per event type
# ---------------------------------------------------------------------------


def _build_task_created(*, todo_name: str, subject: str, assignee: str, linked_app: str | None,
						linked_employee: str | None, requires_password_rotation: bool) -> dict:
	return {
		"task_name": todo_name,
		"subject": subject,
		"assignee": assignee,
		"linked_app": linked_app,
		"linked_employee": linked_employee,
		"requires_password_rotation": bool(requires_password_rotation),
	}


def _build_action_opened(*, action_id: str, app: str, linked_access: str | None,
						 action_type: str, assignee: str, projected_monthly_saving: float | None,
						 due_date: str | None) -> dict:
	return {
		"action_id": action_id,
		"app": app,
		"linked_access": linked_access,
		"action_type": action_type,
		"assignee": assignee,
		"projected_monthly_saving": float(projected_monthly_saving or 0),
		"due_date": due_date,
	}


def _build_renewal_upcoming(*, app: str, renewal_date: str, auto_renew: bool,
							business_owner_email: str | None, per_user_renewal_date: str | None = None,
							access: str | None = None) -> dict:
	return {
		"app": app,
		"renewal_date": renewal_date,
		"per_user_renewal_date": per_user_renewal_date,
		"access": access,
		"auto_renew": bool(auto_renew),
		"business_owner_email": business_owner_email,
	}


def _build_monthly_cost_updated(*, app: str, month: str, old_amount: float | None,
								new_amount: float, currency: str) -> dict:
	return {
		"app": app,
		"month": month,
		"old_amount": float(old_amount) if old_amount is not None else None,
		"new_amount": float(new_amount),
		"currency": currency,
	}


_BUILDERS = {
	"task_created": _build_task_created,
	"action_opened": _build_action_opened,
	"renewal_upcoming": _build_renewal_upcoming,
	"monthly_cost_updated": _build_monthly_cost_updated,
}
