"""Install / setup helpers for saas_register.

`after_install` is wired in hooks.py and runs once per site when the app
is first installed (or via `bench execute saas_register.install.after_install`
to re-run manually).
"""

from __future__ import annotations

import json
import os

import frappe


SAMPLE_APPS_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "saas_application.json")


def after_install():
	_load_sample_applications()
	frappe.db.commit()


def _load_sample_applications():
	if not os.path.exists(SAMPLE_APPS_PATH):
		return

	with open(SAMPLE_APPS_PATH, encoding="utf-8") as f:
		records = json.load(f)

	# Pick any existing Employee to use as a placeholder business_owner for samples.
	# If no Employees exist yet, we skip seeding — sample data doesn't make sense
	# without owners.
	fallback_owner = frappe.db.get_value("Employee", {"status": "Active"}, "name") or frappe.db.get_value(
		"Employee", {}, "name"
	)
	if not fallback_owner:
		frappe.log_error(
			title="saas_register: skipping sample seed",
			message="No Employee exists yet — sample SaaS Applications need a business_owner.",
		)
		return

	for record in records:
		app_name = record.get("app_name")
		if not app_name:
			continue
		if frappe.db.exists("SaaS Application", {"app_name": app_name}):
			continue

		record.setdefault("business_owner", fallback_owner)

		try:
			doc = frappe.get_doc(record)
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title=f"saas_register: failed to seed sample app {app_name}",
				message=frappe.get_traceback(),
			)
