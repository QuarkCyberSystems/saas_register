"""Adds a 'SaaS Access' connection card to the standard Employee dashboard."""

from __future__ import annotations


def extend_employee_dashboard(data):
	transactions = data.setdefault("transactions", [])
	transactions.append(
		{
			"label": "SaaS Access",
			"items": ["SaaS Access"],
		}
	)

	non_standard_fieldnames = data.setdefault("non_standard_fieldnames", {})
	non_standard_fieldnames["SaaS Access"] = "employee"

	return data
