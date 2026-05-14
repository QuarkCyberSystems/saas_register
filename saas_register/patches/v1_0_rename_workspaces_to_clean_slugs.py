"""Clean up the legacy em-dash workspace records.

The previous workspaces were named "SaaS — HR", "SaaS — Finance", and
"SaaS — IT Operations" — that em-dash (U+2014) URL-encodes to %E2%80%94 in
the route slug, producing the ugly `/app/saas-%E2%80%94-hr`.

The workspace JSONs have been updated to use clean ASCII names ("SaaS HR",
"SaaS Finance", "SaaS IT Operations"). `bench migrate` syncs the new records
from the JSONs but leaves the old em-dash records behind. This patch removes
them so the sidebar doesn't show duplicates and the URLs stay clean.

Idempotent — safe to re-run.
"""

from __future__ import annotations

import frappe


OLD_NAMES = ("SaaS — HR", "SaaS — Finance", "SaaS — IT Operations")


def execute():
	for name in OLD_NAMES:
		if frappe.db.exists("Workspace", name):
			try:
				frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title=f"saas_register: failed to delete legacy workspace {name}",
					message=frappe.get_traceback(),
				)
	frappe.db.commit()
