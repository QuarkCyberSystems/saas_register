import frappe
from frappe import _
from frappe.model.document import Document


class SaaSApplicationTier(Document):
	def validate(self):
		# (saas_application, tier_name) is implicitly unique because autoname is
		# `format:{saas_application}-{tier_name}` — Frappe will fail the insert
		# if a duplicate name is generated. Belt-and-braces: explicit check
		# for clearer error message.
		if self.is_new() and frappe.db.exists("SaaS Application Tier", self.name):
			frappe.throw(
				_("Tier {0} already exists for {1}.").format(
					frappe.bold(self.tier_name),
					frappe.bold(self.saas_application),
				),
				title=_("Duplicate Tier"),
			)

	def after_insert(self):
		recompute_parent(self.saas_application)

	def on_update(self):
		recompute_parent(self.saas_application)
		old = self.get_doc_before_save()
		if old and old.saas_application and old.saas_application != self.saas_application:
			recompute_parent(old.saas_application)

	def after_delete(self):
		# `on_trash` fires *before* the DB row is removed, so recomputing the
		# parent there would still see the about-to-be-deleted tier and produce
		# stale totals. `after_delete` fires after the row is gone — recompute
		# here so the parent rollup is correct.
		recompute_parent(self.saas_application)


def recompute_parent(app_name: str) -> None:
	"""Re-roll totals on the SaaS Application from its tiers.

	Called from this doctype's after_insert / on_update / on_trash. Updates the
	parent's `seats_paid`, `monthly_cost`, `annual_cost`, and `plan_summary`
	fields directly via frappe.db.set_value (no parent save → no recursion).
	"""
	if not app_name or not frappe.db.exists("SaaS Application", app_name):
		return

	tiers = frappe.get_all(
		"SaaS Application Tier",
		filters={"saas_application": app_name},
		fields=["tier_name", "seats_paid", "monthly_cost"],
		order_by="creation asc",
	)

	total_seats = sum(int(t.seats_paid or 0) for t in tiers)
	total_cost = sum(float(t.monthly_cost or 0) for t in tiers)
	annual_cost = total_cost * 12

	labels: list[str] = []
	for t in tiers:
		label = (t.tier_name or "").strip() or _("Tier")
		labels.append(f"{label} {int(t.seats_paid)}" if t.seats_paid else label)
	plan_summary = " / ".join(labels)

	frappe.db.set_value(
		"SaaS Application",
		app_name,
		{
			"seats_paid": total_seats,
			"monthly_cost": total_cost,
			"annual_cost": annual_cost,
			"plan_summary": plan_summary,
		},
		update_modified=False,
	)


@frappe.whitelist()
def get_tiers(saas_application: str) -> list[dict]:
	"""Used by the SaaS Access form's `tier` Link field's get_query — also
	exposed for other client code that needs the raw per-seat cost."""
	if not saas_application:
		return []
	return frappe.get_all(
		"SaaS Application Tier",
		filters={"saas_application": saas_application},
		fields=["name", "tier_name", "seats_paid", "monthly_cost", "currency"],
		order_by="creation asc",
	)
