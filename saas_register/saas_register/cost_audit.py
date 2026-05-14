"""SaaS Monthly Cost Audit — writer + parent-hook integration.

The audit doctype is append-only via UI permissions. Rows are produced here.

Two write paths:

1. `write_audit(...)` — used directly by the Monthly Cost Entry page upsert
   and the migration script. Caller already knows old vs new.

2. `audit_application_save(doc, method)` — bound to SaaS Application on_update.
   Diffs the new monthly_costs child rows against the snapshot kept on the
   parent before_save, and writes Insert/Update/Delete audit rows accordingly.
   Catches edits made directly on the Application form (not just via the
   custom page), so the audit trail is comprehensive.

Both paths swallow exceptions so audit failure never blocks a cost save.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, get_first_day, getdate, now


# ---------------------------------------------------------------------------
# Direct writer — used by Monthly Cost Entry page + migration
# ---------------------------------------------------------------------------


def write_audit(
	*,
	saas_application: str,
	month,
	action: str,
	new_amount: float | None,
	new_currency: str | None,
	old_amount: float | None = None,
	old_currency: str | None = None,
	source: str = "Manual",
	edited_by: str | None = None,
) -> str | None:
	"""Append one SaaS Monthly Cost Audit row. Returns the audit doc name, or
	None if writing failed (failure is logged but not raised).
	"""
	try:
		audit = frappe.get_doc(
			{
				"doctype": "SaaS Monthly Cost Audit",
				"saas_application": saas_application,
				"month": get_first_day(getdate(month)),
				"action": action,
				"old_amount": old_amount,
				"new_amount": flt(new_amount or 0),
				"old_currency": old_currency,
				"new_currency": new_currency or "AED",
				"source": source or "Manual",
				"edited_by": edited_by or frappe.session.user,
				"edited_at": now(),
			}
		)
		audit.flags.ignore_permissions = True
		audit.insert(ignore_permissions=True)
		return audit.name
	except Exception:
		frappe.log_error(
			title="saas_register: audit write failed",
			message=frappe.get_traceback(),
		)
		return None


# ---------------------------------------------------------------------------
# Parent on_update diff — catches edits from the Application form
# ---------------------------------------------------------------------------


def audit_application_save(doc, method=None):
	"""Diff doc.monthly_costs against the pre-save snapshot and write audit rows.

	Frappe provides `doc.get_doc_before_save()` which returns the document as
	it was before the current save — perfect for diffing.
	"""
	# Webhook upserts via the Monthly Cost Entry page also save the parent;
	# they audit their own change directly in upsert_monthly_cost(). To avoid
	# double-counting, callers can set this flag.
	if getattr(doc.flags, "skip_cost_audit", False):
		return

	try:
		before = doc.get_doc_before_save()
	except Exception:
		before = None

	current_by_month = _index_by_month(doc.get("monthly_costs") or [])
	previous_by_month = _index_by_month((before.get("monthly_costs") if before else []) or [])

	# Inserts + Updates
	for month, row in current_by_month.items():
		prev = previous_by_month.get(month)
		if prev is None:
			write_audit(
				saas_application=doc.name,
				month=month,
				action="Insert",
				new_amount=row.get("amount"),
				new_currency=row.get("currency") or doc.currency,
				source=row.get("source") or "Manual",
			)
		elif _row_changed(prev, row):
			write_audit(
				saas_application=doc.name,
				month=month,
				action="Update",
				old_amount=prev.get("amount"),
				old_currency=prev.get("currency") or doc.currency,
				new_amount=row.get("amount"),
				new_currency=row.get("currency") or doc.currency,
				source=row.get("source") or "Manual",
			)

	# Deletes
	for month, prev in previous_by_month.items():
		if month not in current_by_month:
			write_audit(
				saas_application=doc.name,
				month=month,
				action="Delete",
				old_amount=prev.get("amount"),
				old_currency=prev.get("currency") or doc.currency,
				new_amount=0,
				new_currency=prev.get("currency") or doc.currency,
				source=prev.get("source") or "Manual",
			)


def _index_by_month(rows) -> dict:
	out: dict = {}
	for row in rows:
		month = row.month if hasattr(row, "month") else row.get("month")
		if not month:
			continue
		key = str(get_first_day(getdate(month)))
		out[key] = {
			"amount": flt(row.amount if hasattr(row, "amount") else row.get("amount") or 0),
			"currency": (row.currency if hasattr(row, "currency") else row.get("currency")),
			"source": (row.source if hasattr(row, "source") else row.get("source")),
		}
	return out


def _row_changed(prev: dict, current: dict) -> bool:
	return (
		flt(prev.get("amount") or 0) != flt(current.get("amount") or 0)
		or (prev.get("currency") or "") != (current.get("currency") or "")
	)
