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

	for record in records:
		app_name = record.get("app_name")
		if not app_name:
			continue
		if frappe.db.exists("SaaS Application", {"app_name": app_name}):
			continue

		# Tiers are linked docs now (not a child table on the parent), so we
		# pop them out of the parent record and create them separately after
		# the parent is saved.
		tiers = record.pop("tiers", []) or []

		try:
			doc = frappe.get_doc(record)
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title=f"saas_register: failed to seed sample app {app_name}",
				message=frappe.get_traceback(),
			)
			continue

		for tier in tiers:
			try:
				tier_doc = frappe.get_doc(
					{
						"doctype": "SaaS Application Tier",
						"saas_application": doc.name,
						**tier,
					}
				)
				tier_doc.insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title=f"saas_register: failed to seed tier on {app_name}",
					message=frappe.get_traceback(),
				)
