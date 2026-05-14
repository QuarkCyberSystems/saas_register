"""Whitelisted endpoints for the Monthly Cost Entry page.

The page is a Frappe Page (not a doctype) — see monthly_cost_entry.json + .js.
Calls these methods to load/save SaaS Monthly Cost rows by (application, month).

Per-row currency: each SaaS Monthly Cost stores its own `currency` and
`exchange_rate_to_base`, so AWS can bill in USD while Spend Dashboard reports
in AED. The page picker auto-fills exchange_rate from ERPNext's Currency
Exchange table (callers can override).

Audit trail: every upsert writes a row to SaaS Monthly Cost Audit. Both insert
(no old_amount) and update (old → new) paths are recorded with action,
edited_by, edited_at, and source.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, today

from saas_register.saas_register.cost_audit import write_audit


# ---------------------------------------------------------------------------
# GET: grid
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_grid(month: str, status: str = "Active", category: str | None = None) -> list[dict]:
	"""Return one row per matching SaaS Application with:
	- app, app_name, vendor, subscription_model, cost_center, currency
	- expected_amount (avg of previous 3 months, converted to base currency)
	- actual_amount (this month's row if it exists)
	- actual_currency + exchange_rate_to_base (per-row, defaults from app)
	- notes (this month's row notes)
	"""
	target_month = get_first_day(getdate(month))
	base_currency = _base_currency()

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
			fields=["month", "amount", "exchange_rate_to_base"],
		)
		# Expected (avg of last 3) is reported in base currency so the Δ column
		# is meaningful across multi-currency apps.
		if hist:
			converted = [flt(h.amount) * flt(h.exchange_rate_to_base or 1.0) for h in hist]
			expected = sum(converted) / len(converted)
		else:
			expected = flt(app.get("monthly_cost"))

		this_month = frappe.db.get_value(
			"SaaS Monthly Cost",
			{
				"parent": app["name"],
				"parenttype": "SaaS Application",
				"month": target_month,
			},
			["amount", "notes", "currency", "exchange_rate_to_base"],
			as_dict=True,
		)

		row_currency = (this_month and this_month.currency) or app.get("currency") or base_currency
		row_rate = (this_month and flt(this_month.exchange_rate_to_base)) or _suggested_rate(row_currency, base_currency, target_month)

		rows.append(
			{
				"app": app["name"],
				"app_name": app["app_name"],
				"vendor": app["vendor"],
				"subscription_model": app["subscription_model"],
				"cost_center": app["cost_center"],
				"currency": row_currency,
				"exchange_rate_to_base": row_rate,
				"base_currency": base_currency,
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


def _base_currency() -> str:
	# Settings field is still named `default_currency` for back-compat. Spec calls
	# it base_currency; the relabel makes the role clear in the form.
	return frappe.db.get_single_value("SaaS Register Settings", "default_currency") or "AED"


@frappe.whitelist()
def get_exchange_rate(from_currency: str, to_currency: str, on_date: str | None = None) -> float:
	"""Look up the ERPNext Currency Exchange rate, falling back to 1.0 when
	currencies match or no rate is configured."""
	if not from_currency or not to_currency or from_currency == to_currency:
		return 1.0
	return _suggested_rate(from_currency, to_currency, getdate(on_date) if on_date else getdate(today()))


def _suggested_rate(from_currency: str, to_currency: str, on_date) -> float:
	if not from_currency or not to_currency or from_currency == to_currency:
		return 1.0
	# Most-recent Currency Exchange row at or before the target month.
	rate = frappe.db.sql(
		"""
		SELECT exchange_rate
		FROM `tabCurrency Exchange`
		WHERE from_currency = %s AND to_currency = %s AND date <= %s
		ORDER BY date DESC
		LIMIT 1
		""",
		(from_currency, to_currency, on_date),
	)
	if rate and rate[0][0]:
		return flt(rate[0][0])
	return 1.0


# ---------------------------------------------------------------------------
# UPSERT: one cell
# ---------------------------------------------------------------------------


@frappe.whitelist()
def upsert_monthly_cost(
	application: str,
	month: str,
	amount: float | str,
	currency: str | None = None,
	exchange_rate_to_base: float | str | None = None,
	notes: str | None = None,
) -> dict:
	"""Upsert a SaaS Monthly Cost row identified by (parent=application, month).

	Writes a SaaS Monthly Cost Audit row in the same transaction.
	"""
	target_month = get_first_day(getdate(month))
	new_amount = flt(amount)

	app = frappe.get_doc("SaaS Application", application)
	frappe.has_permission("SaaS Application", "write", app, throw=True)

	# Default currency from the app; exchange rate from Currency Exchange.
	new_currency = currency or app.currency or _base_currency()
	if exchange_rate_to_base in (None, "", 0):
		new_rate = _suggested_rate(new_currency, _base_currency(), target_month)
	else:
		new_rate = flt(exchange_rate_to_base) or 1.0

	existing_row = None
	for row in (app.monthly_costs or []):
		if getdate(row.month) == target_month:
			existing_row = row
			break

	old_amount = flt(existing_row.amount) if existing_row else None
	old_currency = existing_row.currency if existing_row else None
	action = "Update" if existing_row else "Insert"

	if existing_row:
		existing_row.amount = new_amount
		existing_row.currency = new_currency
		existing_row.exchange_rate_to_base = new_rate
		if notes is not None:
			existing_row.notes = notes
		existing_row.source = "Manual"
		existing_row.last_edited_by = frappe.session.user
		existing_row.last_edited_at = frappe.utils.now()
	else:
		app.append(
			"monthly_costs",
			{
				"month": target_month,
				"amount": new_amount,
				"currency": new_currency,
				"exchange_rate_to_base": new_rate,
				"source": "Manual",
				"notes": notes or "",
				"last_edited_by": frappe.session.user,
				"last_edited_at": frappe.utils.now(),
			},
		)

	# Skip the parent-diff auto-audit — we'll write the audit ourselves below
	# with the right action label and full context.
	app.flags.skip_cost_audit = True
	app.save(ignore_permissions=False)

	write_audit(
		saas_application=application,
		month=target_month,
		action=action,
		old_amount=old_amount,
		old_currency=old_currency,
		new_amount=new_amount,
		new_currency=new_currency,
		source="Manual",
	)

	return {
		"application": application,
		"month": str(target_month),
		"amount": new_amount,
		"currency": new_currency,
		"exchange_rate_to_base": new_rate,
	}


# ---------------------------------------------------------------------------
# Paste from spreadsheet
# ---------------------------------------------------------------------------


@frappe.whitelist()
def paste_monthly_costs(month: str, rows: str | list, commit: int = 0) -> dict:
	"""Fuzzy-match each row against SaaS Application.app_name. Returns
	{matched, unmatched}. When commit=1, also upserts the matched rows.

	Optional `currency` per row honours per-row currency; otherwise the app's
	currency is used and the exchange rate is fetched from Currency Exchange.
	"""
	target_month = get_first_day(getdate(month))
	parsed = _ensure_rows(rows)
	apps = frappe.get_all("SaaS Application", fields=["name", "app_name"])

	matched: list[dict] = []
	unmatched: list[dict] = []

	for r in parsed:
		input_name = (r.get("app_name") or "").strip()
		amount = flt(r.get("amount"))
		currency = (r.get("currency") or "").strip() or None
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
					"currency": currency,
				}
			)
			if int(commit):
				upsert_monthly_cost(
					application=app["name"],
					month=str(target_month),
					amount=amount,
					currency=currency,
				)
		else:
			unmatched.append({"app_name": input_name, "amount": amount, "currency": currency})

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
