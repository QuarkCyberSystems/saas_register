"""Consolidate the three sub-workspaces (SaaS HR / SaaS Finance / SaaS IT
Operations) into a single `SaaS Register` workspace.

The split-by-department approach created sidebar fragmentation and forced
users to know which workspace owns which doctype. The new model: one
workspace, role-driven visibility via the existing DocType permissions
(Frappe automatically hides sidebar links the user can't read).

This patch:
1. Deletes the three legacy workspace records — `bench migrate` then imports
   the new `SaaS Register` workspace from its JSON.
2. Triggers `cleanup_stale_sidebar` so any `Workspace Sidebar` rows that
   still point at the deleted workspaces are dropped and the desk
   auto-regenerates a clean sidebar on next page load.

Idempotent — safe to re-run.
"""

from __future__ import annotations

import frappe

from saas_register.saas_register.sidebar_cleanup import cleanup_stale_sidebar


OLD_WORKSPACES = ("SaaS HR", "SaaS Finance", "SaaS IT Operations")


def execute():
	for name in OLD_WORKSPACES:
		if frappe.db.exists("Workspace", name):
			try:
				frappe.delete_doc(
					"Workspace",
					name,
					force=True,
					ignore_permissions=True,
					delete_permanently=True,
				)
			except Exception:
				frappe.log_error(
					title=f"saas_register: failed to delete legacy workspace {name}",
					message=frappe.get_traceback(),
				)

	# Knock out any saved Workspace Sidebar still pointing at the deleted
	# workspaces so the desk auto-regenerator picks up the new single one.
	cleanup_stale_sidebar()
	frappe.db.commit()
