"""SaaS Spend — Script Report.

Top of the report shows KPI tiles (`report_summary`) and a chart
(`chart`). The body table lists active applications with their spend.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})

	columns = _columns()
	rows = _rows(filters)
	summary = _summary(filters, rows)
	chart = _chart(rows)

	return columns, rows, None, chart, summary


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


def _columns() -> list[dict]:
	return [
		{"label": _("App"), "fieldname": "app_name", "fieldtype": "Link", "options": "SaaS Application", "width": 220},
		{"label": _("Vendor"), "fieldname": "vendor", "fieldtype": "Link", "options": "Supplier", "width": 140},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Link", "options": "SaaS Category", "width": 130},
		{"label": _("Plan"), "fieldname": "plan", "fieldtype": "Data", "width": 130},
		{"label": _("Cost Center"), "fieldname": "cost_center", "fieldtype": "Link", "options": "Cost Center", "width": 150},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Seats Paid"), "fieldname": "seats_paid", "fieldtype": "Int", "width": 90},
		{"label": _("Seats Active"), "fieldname": "seats_active", "fieldtype": "Int", "width": 100},
		{"label": _("Utilization %"), "fieldname": "utilization", "fieldtype": "Percent", "width": 110},
		{"label": _("Monthly Cost"), "fieldname": "monthly_cost", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Annual Cost"), "fieldname": "annual_cost", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Renewal"), "fieldname": "renewal_date", "fieldtype": "Date", "width": 110},
		{"label": _("Days to Renewal"), "fieldname": "days_to_renewal", "fieldtype": "Int", "width": 130},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
	]


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _rows(filters: dict) -> list[dict]:
	conditions: list[str] = []
	values: dict = {}

	if filters.get("status"):
		conditions.append("status = %(status)s")
		values["status"] = filters["status"]

	if filters.get("vendor"):
		conditions.append("vendor = %(vendor)s")
		values["vendor"] = filters["vendor"]

	if filters.get("cost_center"):
		conditions.append("cost_center = %(cost_center)s")
		values["cost_center"] = filters["cost_center"]

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	apps = frappe.db.sql(
		f"""
		SELECT
			name AS app_name,
			vendor,
			category,
			plan,
			cost_center,
			status,
			seats_paid,
			seats_active,
			monthly_cost,
			annual_cost,
			renewal_date,
			currency
		FROM `tabSaaS Application`
		{where}
		ORDER BY monthly_cost DESC
		""",
		values=values,
		as_dict=True,
	)

	today_d = getdate(today())
	for row in apps:
		row.utilization = (
			(flt(row.seats_active) / flt(row.seats_paid) * 100.0) if row.seats_paid else 0.0
		)
		row.days_to_renewal = (getdate(row.renewal_date) - today_d).days if row.renewal_date else None

	return apps


# ---------------------------------------------------------------------------
# KPI tiles
# ---------------------------------------------------------------------------


def _summary(filters: dict, rows: list[dict]) -> list[dict]:
	active_rows = [r for r in rows if (r.get("status") or "") == "Active"]

	total_spend = sum(flt(r.get("monthly_cost")) for r in active_rows)
	active_apps = len(active_rows)

	underutilized_seats = 0
	for r in active_rows:
		paid = flt(r.get("seats_paid"))
		used = flt(r.get("seats_active"))
		if paid and ((paid - used) / paid) >= 0.25:
			underutilized_seats += int(paid - used)

	horizon = add_days(today(), 60)
	renewals_60 = [
		r
		for r in rows
		if r.get("renewal_date")
		and getdate(r["renewal_date"]) <= getdate(horizon)
		and getdate(r["renewal_date"]) >= getdate(today())
	]

	default_currency = (rows[0].get("currency") if rows else None) or frappe.db.get_default("currency") or "AED"

	return [
		{"value": total_spend, "label": _("Total Monthly Spend"), "datatype": "Currency", "currency": default_currency, "indicator": "Blue"},
		{"value": active_apps, "label": _("Active Apps"), "datatype": "Int", "indicator": "Green"},
		{"value": underutilized_seats, "label": _("Underutilized Seats"), "datatype": "Int", "indicator": "Orange"},
		{"value": len(renewals_60), "label": _("Renewals < 60 days"), "datatype": "Int", "indicator": "Red"},
	]


# ---------------------------------------------------------------------------
# Dashboard chart
# ---------------------------------------------------------------------------


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	by_cc: dict[str, float] = {}
	for r in rows:
		if (r.get("status") or "") != "Active":
			continue
		key = r.get("cost_center") or _("Unassigned")
		by_cc[key] = by_cc.get(key, 0.0) + flt(r.get("monthly_cost"))

	if not by_cc:
		return None

	labels = list(by_cc.keys())
	values = [round(by_cc[k], 2) for k in labels]

	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Monthly Spend"), "values": values}],
		},
		"type": "bar",
		"colors": ["#2490EF"],
		"barOptions": {"stacked": False},
	}
