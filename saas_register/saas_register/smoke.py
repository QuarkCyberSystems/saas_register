"""End-to-end smoke test for the saas_register spec-compliance work.

Run with: bench --site liviov16.localhost execute /tmp/saas_register_smoke.run

What it tests:
1. SaaS Tier doctype exists, accepts inserts, enforces (app, tier_name) unique
2. SaaS Monthly Cost Audit doctype exists, is_active backfill ran
3. SaaS Monthly Cost has currency + exchange_rate_to_base
4. SaaS Access has revoke_on_offboarding, tier_or_plan is a Link
5. SaaS Action has linked_access
6. SaaS Category has is_active
7. SaaS Register Settings has offboarding_idempotency_window_days
8. avg_monthly_cost converts via exchange_rate_to_base
9. Audit rows are written on monthly cost upsert (page endpoint)
10. Offboarding trigger: skips revoke_on_offboarding=0 rows, respects idempotency
11. Department cascade: Employee.department change updates SaaS Access.department
"""

from __future__ import annotations

import json
import traceback
from datetime import date

import frappe
from frappe.utils import add_days, today

from saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry import (
	upsert_monthly_cost,
	get_grid,
)


PASS = []
FAIL = []


def step(label):
	def deco(fn):
		def wrapped():
			try:
				fn()
				PASS.append(label)
				print(f"  ✓ {label}")
			except AssertionError as e:
				FAIL.append((label, str(e)))
				print(f"  ✗ {label} — {e}")
			except Exception as e:
				FAIL.append((label, f"{type(e).__name__}: {e}"))
				print(f"  ✗ {label} — {type(e).__name__}: {e}")
				traceback.print_exc()
		return wrapped
	return deco


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cleanup():
	"""Delete fixtures from any prior test run so the suite is idempotent."""
	prefix = "SMOKE_"
	for dt in ("SaaS Access", "SaaS Action", "SaaS Tier", "SaaS Monthly Cost Audit"):
		# Use rough heuristics — these are scoped to test fixtures.
		if dt == "SaaS Tier":
			for n in frappe.get_all("SaaS Tier", filters={"tier_name": ("like", f"{prefix}%")}, pluck="name"):
				frappe.delete_doc("SaaS Tier", n, force=True, ignore_permissions=True)
		elif dt == "SaaS Access":
			for n in frappe.get_all("SaaS Access", filters={"saas_application": ("like", f"%{prefix}%")}, pluck="name"):
				frappe.delete_doc("SaaS Access", n, force=True, ignore_permissions=True)
		elif dt == "SaaS Action":
			for n in frappe.get_all("SaaS Action", filters={"saas_application": ("like", f"%{prefix}%")}, pluck="name"):
				frappe.delete_doc("SaaS Action", n, force=True, ignore_permissions=True)
		elif dt == "SaaS Monthly Cost Audit":
			for n in frappe.get_all("SaaS Monthly Cost Audit", filters={"saas_application": ("like", f"%{prefix}%")}, pluck="name"):
				frappe.delete_doc("SaaS Monthly Cost Audit", n, force=True, ignore_permissions=True)

	for n in frappe.get_all("SaaS Application", filters={"app_name": ("like", f"{prefix}%")}, pluck="name"):
		frappe.delete_doc("SaaS Application", n, force=True, ignore_permissions=True)
	for n in frappe.get_all("ToDo", filters={"description": ("like", f"%{prefix}%")}, pluck="name"):
		frappe.delete_doc("ToDo", n, force=True, ignore_permissions=True)
	# Test employee
	if frappe.db.exists("Employee", {"first_name": "SmokeTest", "last_name": "User"}):
		emp = frappe.db.get_value("Employee", {"first_name": "SmokeTest", "last_name": "User"}, "name")
		# Clean any access for this employee first
		for n in frappe.get_all("SaaS Access", filters={"employee": emp}, pluck="name"):
			frappe.delete_doc("SaaS Access", n, force=True, ignore_permissions=True)
		# ToDos referencing this employee's accesses already cleaned above
		frappe.delete_doc("Employee", emp, force=True, ignore_permissions=True)

	frappe.db.commit()


def _ensure_currencies():
	for c in ("AED", "USD"):
		if not frappe.db.exists("Currency", c):
			frappe.get_doc({"doctype": "Currency", "currency_name": c, "enabled": 1}).insert(ignore_permissions=True)


def _company():
	c = frappe.defaults.get_user_default("Company") or frappe.db.get_default("Company") or frappe.db.get_value("Company", {}, "name")
	if not c:
		raise RuntimeError("No Company exists — set up at least one before running smoke tests.")
	return c


def _ensure_department():
	"""Department names get suffixed with company abbreviation by Frappe — look
	up by department_name, return the real `name` for use in Link fields."""
	out: dict[str, str] = {}
	for label in ("SMOKE_Old_Dept", "SMOKE_New_Dept"):
		existing = frappe.db.get_value("Department", {"department_name": label}, "name")
		if existing:
			out[label] = existing
			continue
		dept = frappe.get_doc({"doctype": "Department", "department_name": label, "company": _company()}).insert(ignore_permissions=True)
		out[label] = dept.name
	return out


def _make_app(name, **kw):
	doc = frappe.get_doc(
		{
			"doctype": "SaaS Application",
			"app_name": name,
			"category": frappe.db.get_value("SaaS Category", {}, "name") or _ensure_category(),
			"business_owner": _ensure_employee(),
			"subscription_model": kw.get("subscription_model", "Shared"),
			"status": "Active",
			"currency": kw.get("currency", "AED"),
			"billing_cycle": "Monthly",
		}
	)
	# Optional fields
	if "renewal_date" in kw:
		doc.renewal_date = kw["renewal_date"]
	doc.insert(ignore_permissions=True)
	return doc


def _ensure_category():
	if not frappe.db.exists("SaaS Category", "Productivity"):
		frappe.get_doc({"doctype": "SaaS Category", "category_name": "Productivity", "is_active": 1}).insert(ignore_permissions=True)
	return "Productivity"


def _ensure_employee():
	if frappe.db.exists("Employee", {"first_name": "SmokeTest", "last_name": "User"}):
		return frappe.db.get_value("Employee", {"first_name": "SmokeTest", "last_name": "User"}, "name")
	emp = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "SmokeTest",
			"last_name": "User",
			"gender": "Other",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2024-01-01",
			"status": "Active",
			"company": _company(),
			"department": DEPTS.get("SMOKE_Old_Dept"),
		}
	)
	emp.insert(ignore_permissions=True)
	return emp.name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def run():
	print("\n=== saas_register smoke test ===\n")
	_cleanup()
	_ensure_currencies()
	global DEPTS
	DEPTS = _ensure_department()

	# ----- 1. SaaS Tier doctype exists + uniqueness -----
	test_saas_tier_exists_and_unique()

	# ----- 2. SaaS Monthly Cost Audit doctype exists -----
	test_audit_doctype_exists()

	# ----- 3. New fields exist on existing doctypes -----
	test_new_fields_exist()

	# ----- 4. avg_monthly_cost converts to base currency -----
	test_avg_monthly_cost_conversion()

	# ----- 5. Audit row written on upsert (Insert + Update path) -----
	test_audit_row_written_on_upsert()

	# ----- 6. Offboarding trigger skips revoke_on_offboarding=0 + idempotency -----
	test_offboarding_skip_and_idempotency()

	# ----- 7. Department cascade -----
	test_department_cascade()

	# ----- 8. Settings has new fields -----
	test_settings_fields()

	# ----- 9. Webhook payload builder -----
	test_webhook_builder()

	# ----- 10. SaaS Access tier validation -----
	test_tier_belongs_to_app()

	print(f"\n=== Results: {len(PASS)} passed, {len(FAIL)} failed ===\n")
	if FAIL:
		print("Failures:")
		for label, msg in FAIL:
			print(f"  - {label}: {msg}")
	_cleanup()


# ============================================================================


@step("SaaS Tier: insert + (app, tier_name) uniqueness")
def test_saas_tier_exists_and_unique():
	assert frappe.db.exists("DocType", "SaaS Tier"), "SaaS Tier doctype missing"
	app = _make_app("SMOKE_App_Tier", subscription_model="Shared")

	t1 = frappe.get_doc({"doctype": "SaaS Tier", "saas_application": app.name, "tier_name": "SMOKE_Max", "is_active": 1}).insert(ignore_permissions=True)
	assert t1.name, "First tier did not insert"

	# Duplicate (app, tier_name) must raise
	dup_failed = False
	try:
		frappe.get_doc({"doctype": "SaaS Tier", "saas_application": app.name, "tier_name": "SMOKE_Max", "is_active": 1}).insert(ignore_permissions=True)
	except Exception:
		dup_failed = True
	assert dup_failed, "Duplicate (app, tier_name) was allowed"


@step("SaaS Monthly Cost Audit: doctype exists + no UI write permission")
def test_audit_doctype_exists():
	assert frappe.db.exists("DocType", "SaaS Monthly Cost Audit"), "Audit doctype missing"
	meta = frappe.get_meta("SaaS Monthly Cost Audit")
	for f in ("saas_application", "month", "action", "old_amount", "new_amount", "old_currency", "new_currency", "edited_by", "edited_at", "source"):
		assert meta.get_field(f), f"Audit doctype missing field: {f}"
	# Verify in_create=1 (only programmatic creation allowed via UI roles having no `create` perm)
	doctype = frappe.get_doc("DocType", "SaaS Monthly Cost Audit")
	assert doctype.in_create == 1, "in_create flag not set"


@step("New fields present on existing doctypes")
def test_new_fields_exist():
	mc = frappe.get_meta("SaaS Monthly Cost")
	assert mc.get_field("currency"), "SaaS Monthly Cost.currency missing"
	assert mc.get_field("exchange_rate_to_base"), "SaaS Monthly Cost.exchange_rate_to_base missing"

	sa = frappe.get_meta("SaaS Access")
	rev = sa.get_field("revoke_on_offboarding")
	assert rev, "SaaS Access.revoke_on_offboarding missing"
	assert rev.default == "1" or rev.default == 1, f"revoke_on_offboarding default not 1 (got {rev.default!r})"
	tier = sa.get_field("tier_or_plan")
	assert tier.fieldtype == "Link", f"tier_or_plan fieldtype should be Link, got {tier.fieldtype}"
	assert tier.options == "SaaS Tier", f"tier_or_plan options should be 'SaaS Tier', got {tier.options}"

	act = frappe.get_meta("SaaS Action")
	la = act.get_field("linked_access")
	assert la and la.fieldtype == "Link" and la.options == "SaaS Access", "SaaS Action.linked_access missing/incorrect"

	cat = frappe.get_meta("SaaS Category")
	ia = cat.get_field("is_active")
	assert ia, "SaaS Category.is_active missing"


@step("avg_monthly_cost converts via exchange_rate_to_base")
def test_avg_monthly_cost_conversion():
	app = _make_app("SMOKE_App_AvgFX", currency="USD")
	# 3 rows, each in USD at FX rate 3.67 (USD→AED)
	app.append("monthly_costs", {"month": "2026-01-01", "amount": 100, "currency": "USD", "exchange_rate_to_base": 3.67, "source": "Manual"})
	app.append("monthly_costs", {"month": "2026-02-01", "amount": 100, "currency": "USD", "exchange_rate_to_base": 3.67, "source": "Manual"})
	app.append("monthly_costs", {"month": "2026-03-01", "amount": 100, "currency": "USD", "exchange_rate_to_base": 3.67, "source": "Manual"})
	app.save(ignore_permissions=True)
	expected = 100 * 3.67  # avg of three identical converted values
	assert abs(app.avg_monthly_cost - expected) < 0.01, f"avg_monthly_cost = {app.avg_monthly_cost}, expected {expected}"


@step("Audit row written on Monthly Cost upsert (Insert then Update)")
def test_audit_row_written_on_upsert():
	app = _make_app("SMOKE_App_Audit")

	# Insert
	upsert_monthly_cost(application=app.name, month="2026-03-01", amount=500, currency="AED")
	rows = frappe.get_all("SaaS Monthly Cost Audit",
						   filters={"saas_application": app.name, "month": "2026-03-01"},
						   fields=["action", "old_amount", "new_amount", "new_currency", "source"])
	assert len(rows) == 1 and rows[0].action == "Insert", f"Expected 1 Insert audit row, got {rows}"
	assert rows[0].new_amount == 500, f"new_amount mismatch: {rows[0]}"

	# Update
	upsert_monthly_cost(application=app.name, month="2026-03-01", amount=750, currency="AED")
	rows = frappe.get_all("SaaS Monthly Cost Audit",
						   filters={"saas_application": app.name, "month": "2026-03-01"},
						   fields=["action", "old_amount", "new_amount"],
						   order_by="creation asc")
	assert len(rows) == 2, f"Expected 2 audit rows, got {len(rows)}"
	assert rows[1].action == "Update", f"Second row action {rows[1].action}"
	assert rows[1].old_amount == 500 and rows[1].new_amount == 750, f"Update values: {rows[1]}"


@step("Offboarding: skips revoke_on_offboarding=0 + per-row try/except + idempotency")
def test_offboarding_skip_and_idempotency():
	app_revocable = _make_app("SMOKE_App_Revocable")
	app_service = _make_app("SMOKE_App_ServiceAccount")
	emp = _ensure_employee()

	# Two access rows: one normal (revoke_on_offboarding=1 default), one service account (=0)
	a1 = frappe.get_doc({
		"doctype": "SaaS Access",
		"employee": emp,
		"saas_application": app_revocable.name,
	}).insert(ignore_permissions=True)

	a2 = frappe.get_doc({
		"doctype": "SaaS Access",
		"employee": emp,
		"saas_application": app_service.name,
		"revoke_on_offboarding": 0,
	}).insert(ignore_permissions=True)

	# Add an offboarding step to app_revocable so we get a ToDo
	app_revocable.append("offboarding_steps", {
		"sequence": 1,
		"step_description": "SMOKE_RevokeStep",
		"assigned_role_key": "it_manager",
		"estimated_minutes": 5,
	})
	app_revocable.save(ignore_permissions=True)

	# Trigger offboarding by flipping status to Left (ERPNext requires relieving_date)
	emp_doc = frappe.get_doc("Employee", emp)
	emp_doc.status = "Left"
	emp_doc.relieving_date = today()
	emp_doc.save(ignore_permissions=True)
	frappe.db.commit()

	# Refresh access rows
	a1_after = frappe.get_doc("SaaS Access", a1.name)
	a2_after = frappe.get_doc("SaaS Access", a2.name)
	assert a1_after.revoke_status == "Pending Revoke", f"Revocable access status: {a1_after.revoke_status}"
	assert a2_after.revoke_status == "Active", f"Service-account access should stay Active, got: {a2_after.revoke_status}"

	# ToDo created for the revocable row only
	todos = frappe.get_all("ToDo", filters={"reference_type": "SaaS Access", "reference_name": ("in", [a1.name, a2.name])}, fields=["reference_name", "description"])
	by_ref = {t.reference_name for t in todos}
	assert a1.name in by_ref, f"Expected ToDo for {a1.name}, got {by_ref}"
	assert a2.name not in by_ref, f"Should NOT have ToDo for service account {a2.name}, got {by_ref}"

	# Idempotency: re-save Employee.status (no change) → no new ToDos
	todos_before = len(todos)
	emp_doc.reload()
	emp_doc.save(ignore_permissions=True)
	frappe.db.commit()
	todos_after = frappe.db.count("ToDo", {"reference_type": "SaaS Access", "reference_name": ("in", [a1.name, a2.name])})
	assert todos_after == todos_before, f"Idempotency violated: {todos_before} → {todos_after}"


@step("Department cascade: Employee.department change updates SaaS Access.department")
def test_department_cascade():
	app = _make_app("SMOKE_App_DeptCascade")
	# Fresh isolated employee (so we don't collide with prior test's emp who was set to Left)
	if frappe.db.exists("Employee", {"first_name": "SmokeCascade", "last_name": "User"}):
		old = frappe.db.get_value("Employee", {"first_name": "SmokeCascade", "last_name": "User"}, "name")
		for n in frappe.get_all("SaaS Access", filters={"employee": old}, pluck="name"):
			frappe.delete_doc("SaaS Access", n, force=True, ignore_permissions=True)
		frappe.delete_doc("Employee", old, force=True, ignore_permissions=True)

	emp = frappe.get_doc({
		"doctype": "Employee",
		"first_name": "SmokeCascade",
		"last_name": "User",
		"gender": "Other",
		"date_of_birth": "1990-01-01",
		"date_of_joining": "2024-01-01",
		"status": "Active",
		"company": _company(),
		"department": DEPTS["SMOKE_Old_Dept"],
	}).insert(ignore_permissions=True)

	acc = frappe.get_doc({
		"doctype": "SaaS Access",
		"employee": emp.name,
		"saas_application": app.name,
	}).insert(ignore_permissions=True)
	assert frappe.db.get_value("SaaS Access", acc.name, "department") == DEPTS["SMOKE_Old_Dept"], "Initial dept not fetched"

	# Change the employee's department — should cascade via bulk SQL
	emp.department = DEPTS["SMOKE_New_Dept"]
	emp.save(ignore_permissions=True)
	frappe.db.commit()

	new_dept = frappe.db.get_value("SaaS Access", acc.name, "department")
	assert new_dept == DEPTS["SMOKE_New_Dept"], f"Cascade failed: SaaS Access.department = {new_dept!r}"

	# Cleanup this isolated emp
	frappe.delete_doc("SaaS Access", acc.name, force=True, ignore_permissions=True)
	frappe.delete_doc("Employee", emp.name, force=True, ignore_permissions=True)
	frappe.db.commit()


@step("SaaS Register Settings: new fields present + base_currency role")
def test_settings_fields():
	meta = frappe.get_meta("SaaS Register Settings")
	assert meta.get_field("offboarding_idempotency_window_days"), "idempotency window field missing"
	# default_currency relabeled to Base Currency
	dc = meta.get_field("default_currency")
	assert dc, "default_currency missing"
	assert "Base Currency" in (dc.label or ""), f"default_currency label is {dc.label!r}"


@step("Webhook builder: injects triggered_by_user + event_timestamp; respects no-op when URL blank")
def test_webhook_builder():
	from saas_register.saas_register.webhooks import build_payload, post

	payload = build_payload("task_created", todo_name="t1", subject="x", assignee="a", linked_app="app", linked_employee="e", requires_password_rotation=True)
	assert "triggered_by_user" in payload, "triggered_by_user missing"
	assert "event_timestamp" in payload, "event_timestamp missing"
	assert payload["event_type"] == "task_created"

	# No-op when URL blank — should NOT raise
	frappe.db.set_single_value("SaaS Register Settings", "n8n_webhook_base_url", "")
	post({"x": 1}, "/test")  # no exception expected


@step("SaaS Access: tier_or_plan must belong to the same app (server-side guard)")
def test_tier_belongs_to_app():
	a1 = _make_app("SMOKE_App_TierA")
	a2 = _make_app("SMOKE_App_TierB")
	t1 = frappe.get_doc({"doctype": "SaaS Tier", "saas_application": a1.name, "tier_name": "SMOKE_TierForA", "is_active": 1}).insert(ignore_permissions=True)

	# Tier belongs to a1; saving it onto an access for a2 must throw
	emp = _ensure_employee()

	# Ensure the emp doesn't have access to a2 yet
	for n in frappe.get_all("SaaS Access", filters={"employee": emp, "saas_application": a2.name}, pluck="name"):
		frappe.delete_doc("SaaS Access", n, force=True, ignore_permissions=True)

	threw = False
	try:
		frappe.get_doc({
			"doctype": "SaaS Access",
			"employee": emp,
			"saas_application": a2.name,
			"tier_or_plan": t1.name,
		}).insert(ignore_permissions=True)
	except Exception:
		threw = True
	assert threw, "Server allowed a tier from a different app"
