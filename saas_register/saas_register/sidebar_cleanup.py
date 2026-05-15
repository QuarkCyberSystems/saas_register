"""Self-heal Workspace Sidebar after migrate / install.

Frappe auto-generates a `Workspace Sidebar` record per module the first time
the desk boots — including a list of `Workspace Sidebar Item` rows of
`link_type=Workspace` pointing at each Workspace in the module. Once saved,
that record is treated as the source of truth and auto-regeneration is
skipped (see `auto_generate_sidebar_from_module()` at
apps/frappe/frappe/desk/doctype/workspace_sidebar/workspace_sidebar.py:274).

If a workspace is later renamed or deleted (we did both in v4), the saved
sidebar still references the old name. The frontend's
`sidebar_item.js::get_path()` then crashes hard at:

    let workspaces = frappe.workspaces[frappe.router.slug(this.item.link_to)];
    if (workspaces.public) { ... }   // 💥 undefined

because the lookup misses and there's no null-guard. One stale link kills the
entire sidebar render.

Our fix: drop the saved `Workspace Sidebar` for the Saas Register module if
any of its items point to a workspace that no longer exists. On the next desk
load, `auto_generate_sidebar_from_module()` re-creates it in-memory using
current workspaces — clean and correct, no stale references.

Idempotent — safe to run on every migrate.
"""

from __future__ import annotations

import frappe


MODULE_NAME = "Saas Register"


def cleanup_stale_sidebar() -> dict:
	"""Delete any Workspace Sidebar for our module whose items reference a
	now-missing workspace. Returns a small summary for logging/tests."""

	summary = {"sidebars_dropped": 0, "items_dropped": 0}

	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		# Older Frappe versions don't have this doctype.
		return summary

	# Find sidebars belonging to our module (or named after it for the rare
	# case where the saved record uses the module label as its name).
	sidebar_names = set(
		frappe.get_all(
			"Workspace Sidebar",
			filters={"module": MODULE_NAME},
			pluck="name",
		)
	)
	if frappe.db.exists("Workspace Sidebar", MODULE_NAME):
		sidebar_names.add(MODULE_NAME)

	if not sidebar_names:
		return summary

	for sidebar in sidebar_names:
		dangling = frappe.db.sql(
			"""
			SELECT wsi.name, wsi.link_to
			FROM `tabWorkspace Sidebar Item` wsi
			WHERE wsi.parent = %s
			  AND wsi.link_type = 'Workspace'
			  AND wsi.link_to IS NOT NULL
			  AND wsi.link_to != ''
			  AND wsi.link_to NOT IN (SELECT name FROM tabWorkspace)
			""",
			(sidebar,),
			as_dict=True,
		)
		if not dangling:
			# Sidebar is healthy — leave it alone (preserves any user reordering).
			continue

		try:
			frappe.delete_doc(
				"Workspace Sidebar",
				sidebar,
				force=True,
				ignore_permissions=True,
				delete_permanently=True,
			)
			summary["sidebars_dropped"] += 1
			summary["items_dropped"] += len(dangling)
			frappe.logger().info(
				f"saas_register: dropped stale Workspace Sidebar {sidebar!r} "
				f"({len(dangling)} dangling links: {[d.link_to for d in dangling]})"
			)
		except Exception:
			frappe.log_error(
				title=f"saas_register: failed to drop stale Workspace Sidebar {sidebar}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	return summary
