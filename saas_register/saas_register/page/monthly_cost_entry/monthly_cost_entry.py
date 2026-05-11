"""Whitelisted endpoints for the Monthly Cost Entry page.

The page is a Frappe Page (not a doctype) — see monthly_cost_entry.json + .js.
Calls these methods to load/save SaaS Monthly Cost rows by (application, month).

Audit trail (Phase 1):
  - Each edit logs the old → new amount to Error Log titled "SaaS Monthly Cost
    Audit" with a structured message. Sufficient for v1; promotes to a
    dedicated SaaS Monthly Cost Audit doctype in Phase 1.5 (per v3 §3.2).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, now


AUDIT_TITLE = "SaaS Monthly Cost Audit"


# ---------------------------------------------------------------------------
# GET: grid
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_grid(month: str, status: str = "Active", category: str | None = None) -> list[dict]:
	"""Return one row per matching SaaS Application with:
	- app, app_name, vendor, subscription_model, cost_center, currency
	- expected_amount (avg of previous 3 months from monthly_costs)
	- actual_amount (this month's row if it exists)
	- notes (this month's row notes)
	"""
	target_month = get_first_day(getdate(month))

	app_filters: dict = {}
	if status and status != "All":
		app_filters["status"] = status
	if category:
		app_filters["category"] = category

	apps = frappe.get_all(
		"SaaS Application",
		filters=app_filters,
		fields=["name", "app_name", "vendor", "subscription_model", "cost_center", "currency", "monthly_cost"],
		order_by="app_name asc",
	)

	rows: list[dict] = []
	for app in apps:
		previous_months = _months_before(target_month, 3)
		hist = frappe.get_all(
			"SaaS Monthly Cost",
			filters={
				"parent": app["name"],
				"parenttype": "SaaS Application",
				"month": ("in", previous_months),
			},
			fields=["month", "amount"],
		)
		expected = (sum(flt(h.amount) for h in hist) / len(hist)) if hist else flt(app.get("monthly_cost"))

		this_month = frappe.db.get_value(
			"SaaS Monthly Cost",
			{
				"parent": app["name"],
				"parenttype": "SaaS Application",
				"month": target_month,
			},
			["amount", "notes"],
			as_dict=True,
		)

		rows.append(
			{
				"app": app["name"],
				"app_name": app["app_name"],
				"vendor": app["vendor"],
				"subscription_model": app["subscription_model"],
				"cost_center": app["cost_center"],
				"currency": app.get("currency") or "AED",
				"expected_amount": flt(expected),
				"actual_amount": flt(this_month.amount) if this_month else None,
				"notes": (this_month.notes if this_month else None),
			}
		)

	return rows


def _months_before(month: date, n: int) -> list[date]:
	out: list[date] = []
	for i in range(1, n + 1):
		out.append(add_months(month, -i))
	return out


# ---------------------------------------------------------------------------
# UPSERT: one cell
# ---------------------------------------------------------------------------


@frappe.whitelist()
def upsert_monthly_cost(
	application: str,
	month: str,
	amount: float | str,
	notes: str | None = None,
) -> dict:
	"""Upsert a SaaS Monthly Cost row identified by (parent=application, month)."""
	target_month = get_first_day(getdate(month))
	new_amount = flt(amount)

	app = frappe.get_doc("SaaS Application", application)
	frappe.has_permission("SaaS Application", "write", app, throw=True)

	existing_row = None
	for row in (app.monthly_costs or []):
		if getdate(row.month) == target_month:
			existing_row = row
			break

	old_amount = flt(existing_row.amount) if existing_row else None

	if existing_row:
		existing_row.amount = new_amount
		if notes is not None:
			existing_row.notes = notes
		existing_row.source = "Manual"
	else:
		app.append(
			"monthly_costs",
			{
				"month": target_month,
				"amount": new_amount,
				"source": "Manual",
				"notes": notes or "",
			},
		)

	app.save(ignore_permissions=False)

	_audit(application=application, month=str(target_month), old_amount=old_amount, new_amount=new_amount)
	return {"application": application, "month": str(target_month), "amount": new_amount}


def _audit(*, application: str, month: str, old_amount: float | None, new_amount: float) -> None:
	"""Phase-1 audit: log to Error Log so changes are queryable. Phase 1.5
	promotes to a SaaS Monthly Cost Audit doctype."""
	message = json.dumps(
		{
			"application": application,
			"month": month,
			"old_amount": old_amount,
			"new_amount": new_amount,
			"user": frappe.session.user,
			"timestamp": str(now()),
		}
	)
	try:
		frappe.log_error(title=AUDIT_TITLE, message=message)
	except Exception:
		# Never fail an upsert because audit failed.
		pass


# ---------------------------------------------------------------------------
# Paste from spreadsheet
# ---------------------------------------------------------------------------


@frappe.whitelist()
def paste_monthly_costs(month: str, rows: str | list, commit: int = 0) -> dict:
	"""Fuzzy-match each row against SaaS Application.app_name. Returns
	{matched, unmatched}. When commit=1, also upserts the matched rows.
	"""
	target_month = get_first_day(getdate(month))
	parsed = _ensure_rows(rows)
	apps = frappe.get_all("SaaS Application", fields=["name", "app_name"])

	matched: list[dict] = []
	unmatched: list[dict] = []

	for r in parsed:
		input_name = (r.get("app_name") or "").strip()
		amount = flt(r.get("amount"))
		if not input_name:
			continue

		app = _fuzzy_match(input_name, apps)
		if app:
			matched.append(
				{
					"input": input_name,
					"app": app["name"],
					"app_name": app["app_name"],
					"amount": amount,
				}
			)
			if int(commit):
				upsert_monthly_cost(application=app["name"], month=str(target_month), amount=amount)
		else:
			unmatched.append({"app_name": input_name, "amount": amount})

	return {"matched": matched, "unmatched": unmatched}


def _ensure_rows(rows):
	if isinstance(rows, str):
		return json.loads(rows)
	return rows or []


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(s: str) -> str:
	return _NORMALIZE_RE.sub("", (s or "").lower())


def _fuzzy_match(input_name: str, apps: list[dict]) -> dict | None:
	"""Return the SaaS Application dict that best matches input_name. None if
	no app crosses the similarity threshold."""
	if not input_name:
		return None
	target = _normalize(input_name)

	best: tuple[float, dict | None] = (0.0, None)
	for app in apps:
		candidate = _normalize(app["app_name"])
		# Substring match → high confidence
		if candidate and candidate in target:
			score = 0.95
		elif target and target in candidate:
			score = 0.95
		else:
			score = SequenceMatcher(None, target, candidate).ratio()
		if score > best[0]:
			best = (score, app)

	if best[0] >= 0.8:
		return best[1]
	return None
