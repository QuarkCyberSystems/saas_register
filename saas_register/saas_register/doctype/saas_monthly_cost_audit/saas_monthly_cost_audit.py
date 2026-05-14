"""Controller for SaaS Monthly Cost Audit.

Append-only by design. The doctype has no edit/delete permissions in the UI;
rows are written exclusively by `saas_register.saas_register.cost_audit.write_audit`.

This controller is intentionally bare — validation lives in the writer helper.
"""

from __future__ import annotations

from frappe.model.document import Document


class SaaSMonthlyCostAudit(Document):
	pass
