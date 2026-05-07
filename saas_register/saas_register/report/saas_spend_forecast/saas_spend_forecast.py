"""SaaS Spend Forecast — month-by-month, renewal-aware.

Forecast horizon: 12 months from `start_month` (defaults to the first day of the
current month). One row per SaaS Application + a totals row at the bottom.

Cost model:
  - Monthly billing apps: contribute `monthly_cost` every month, until the app
    is dropped (see Kill-Replace logic below).
  - Annual / Multi-year billing apps: amortized as `monthly_cost` every month
    (i.e. annual_cost / 12). This gives a smooth budgeting view rather than a
    one-time spike on the renewal month.
  - Kill-Replace apps: contribute monthly_cost up to and including their next
    `renewal_date` month, then drop to zero (we assume the team kills it before
    renewal — this matches "Kill before renew" tags in the mockup).
  - Apps without renewal_date: assumed continuous if Active, dropped if status
    is Kill-Replace.

Filters: start_month (default today's month start), cost_center, status.

Dashboard chart: line of total monthly forecast across the horizon.
KPI tiles: 12-month total, peak month, average month, drop-off at month 12.
"""

from __future__ import annotations

from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, today


HORIZON_MONTHS = 12


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	start = _resolve_start_month(filters.get("start_month"))
	months = [add_months(start, i) for i in range(HORIZON_MONTHS)]

	apps = _fetch_apps(filters)
	rows, totals = _build_rows(apps, months)

	columns = _columns(months)
	rows_with_totals = rows + [_totals_row(totals, months)]
	summary = _summary(totals)
	chart = _chart(totals, months)

	return columns, rows_with_totals, None, chart, summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_start_month(value) -> date:
	if not value:
		return getdate(get_first_day(today()))
	d = getdate(value)
	return getdate(get_first_day(d))


def _fetch_apps(filters: dict) -> list[dict]:
	q_filters: dict = {}
	if filters.get("cost_center"):
		q_filters["cost_center"] = filters["cost_center"]
	if filters.get("status"):
		q_filters["status"] = filters["status"]
	# We never bother forecasting fully-dead apps unless explicitly asked
	if "status" not in q_filters:
		q_filters["status"] = ("in", ["Active", "Review", "Kill-Replace"])

	return frappe.get_all(
		"SaaS Application",
		filters=q_filters,
		fields=[
			"name",
			"app_name",
			"vendor",
			"category",
			"cost_center",
			"status",
			"monthly_cost",
			"billing_cycle",
			"renewal_date",
			"currency",
		],
		order_by="monthly_cost desc",
	)


def _build_rows(apps: list[dict], months: list[date]):
	rows: list[dict] = []
	totals: dict[date, float] = {m: 0.0 for m in months}

	for app in apps:
		row: dict = {
			"app": app.name,
			"app_name": app.app_name,
			"vendor": app.vendor,
			"cost_center": app.cost_center,
			"status": app.status,
			"currency": app.currency,
			"_total": 0.0,
		}
		for m in months:
			cost = _forecast_one_month(app, m)
			row[_col(m)] = cost
			row["_total"] += cost
			totals[m] += cost

		rows.append(row)

	return rows, totals


def _forecast_one_month(app: dict, month: date) -> float:
	monthly = flt(app.get("monthly_cost"))
	if not monthly:
		return 0.0

	# Kill-Replace handling: cost continues up to and including the renewal month,
	# then drops to zero.
	if app.get("status") == "Kill-Replace" and app.get("renewal_date"):
		renew = getdate(app["renewal_date"])
		if month > getdate(get_first_day(renew)):
			return 0.0

	return monthly


def _col(m: date) -> str:
	return m.strftime("m_%Y_%m")


def _label(m: date) -> str:
	return m.strftime("%b %Y")


def _columns(months: list[date]) -> list[dict]:
	cols: list[dict] = [
		{"label": _("App"), "fieldname": "app", "fieldtype": "Link", "options": "SaaS Application", "width": 130},
		{"label": _("Application"), "fieldname": "app_name", "fieldtype": "Data", "width": 200},
		{"label": _("Vendor"), "fieldname": "vendor", "fieldtype": "Link", "options": "Supplier", "width": 130},
		{"label": _("Cost Center"), "fieldname": "cost_center", "fieldtype": "Link", "options": "Cost Center", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]
	for m in months:
		cols.append(
			{
				"label": _label(m),
				"fieldname": _col(m),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 100,
			}
		)
	cols.append(
		{"label": _("12-mo Total"), "fieldname": "_total", "fieldtype": "Currency", "options": "currency", "width": 130}
	)
	return cols


def _totals_row(totals: dict[date, float], months: list[date]) -> dict:
	row: dict = {
		"app": None,
		"app_name": "<b>" + _("Total") + "</b>",
		"vendor": None,
		"cost_center": None,
		"status": None,
		"_total": sum(totals.values()),
	}
	for m in months:
		row[_col(m)] = totals[m]
	return row


def _summary(totals: dict[date, float]) -> list[dict]:
	values = list(totals.values())
	if not values:
		return []
	total = sum(values)
	avg = total / len(values)
	peak = max(values)
	last = values[-1]
	first = values[0]
	delta = last - first

	default_currency = frappe.db.get_default("currency") or "AED"
	return [
		{"value": total, "label": _("12-month Total"), "datatype": "Currency", "currency": default_currency, "indicator": "Blue"},
		{"value": avg, "label": _("Avg Monthly"), "datatype": "Currency", "currency": default_currency, "indicator": "Blue"},
		{"value": peak, "label": _("Peak Month"), "datatype": "Currency", "currency": default_currency, "indicator": "Orange"},
		{"value": delta, "label": _("Δ Month 12 vs Month 1"), "datatype": "Currency", "currency": default_currency, "indicator": "Green" if delta <= 0 else "Red"},
	]


def _chart(totals: dict[date, float], months: list[date]) -> dict:
	return {
		"data": {
			"labels": [_label(m) for m in months],
			"datasets": [{"name": _("Monthly Forecast"), "values": [round(totals[m], 2) for m in months]}],
		},
		"type": "line",
		"colors": ["#2490EF"],
		"lineOptions": {"regionFill": 1},
	}
