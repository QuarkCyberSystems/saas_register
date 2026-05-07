# SaaS & Access Register (`saas_register`)

A custom Frappe v15 app for **Livio** that:

1. **Inventories** every paid SaaS application — cost, plan, seats, renewal, owner.
2. **Tracks access** — which Employee has access to which app, with revoke status.
3. **Auto-triggers offboarding** — when HR changes an Employee's status to `Left` (or any value containing `Resigned` / `Terminated`), the app creates a Project with one Task per (app × offboarding step).

Reuses standard ERPNext **Supplier** for vendors, HRMS **Employee** for users/owners, and standard **Cost Center** / **Currency** / **Purchase Invoice** for finance fields.

---

## Architecture

| Layer | What | Where |
| --- | --- | --- |
| Master | `SaaS Application` | `saas_register/saas_register/doctype/saas_application` |
| Master | `SaaS Category` (used by Application.category Link) | `.../doctype/saas_category` |
| Standalone | `SaaS Access` (one row per employee × app, naming `SAC-.YYYY.-.####`) | `.../doctype/saas_access` |
| Child | `SaaS Application Tier` (per-tier seats + cost; rollup on parent) | `.../doctype/saas_application_tier` |
| Child | `SaaS Offboarding Step` (child of SaaS Application) | `.../doctype/saas_offboarding_step` |
| Single | `SaaS Register Settings` (role_key → User mapping, defaults) | `.../doctype/saas_register_settings` |
| Server logic | Employee `on_update` hook → offboarding workflow | `saas_register/saas_register/employee_hooks.py` |
| Server logic | SaaS Access hooks → recompute `seats_active` on parent | `saas_register/saas_register/doctype/saas_access/saas_access.py` |
| Server logic | Permission query / `has_permission` for SaaS Access | `saas_register/saas_register/permissions.py` |
| Client | Form `.js` for "Revoke Now" button | `.../doctype/saas_access/saas_access.js` |
| Client | Form `.js` for Application dashboard utilization indicator + recompute | `.../doctype/saas_application/saas_application.js` |
| Report | `SaaS Spend` (Script Report with `report_summary` KPI tiles + chart) | `.../report/saas_spend` |
| Report | `SaaS Spend Forecast` (12-month projection, renewal-aware, line chart) | `.../report/saas_spend_forecast` |
| Report | `SaaS Access Matrix` (Employee × App pivot with colored cells) | `.../report/saas_access_matrix` |
| Workspace | "SaaS Register" sidebar entry | `.../workspace/saas_register` |
| Roles | `IT Manager` (created via fixture) | `saas_register/fixtures/role.json` |

All server-side wiring uses **standard Frappe `doc_events` hooks** (not runtime Server Script records), so it's version-controlled and ships with the app.

---

## Install

```bash
# from frappe-bench root
bench get-app saas_register <repo-url> --branch version-16   # if cloning fresh
bench --site <site> install-app saas_register
```

Already installed sites just need a migrate to pick up new doctypes:

```bash
bench --site <site> migrate
```

If the app was installed from an earlier (empty-skeleton) revision, the
`after_install` hook won't have run — re-trigger seed data manually:

```bash
bench --site <site> execute saas_register.install.after_install
```

What `after_install` does:
- Creates 5 sample SaaS Applications (Google Workspace, HubSpot Sales Hub, Atlassian Jira, Vercel, 1Password Business) each with offboarding steps. Skipped if records with the same `app_name` already exist.

What gets imported automatically every migrate (via `fixtures/`):
- `IT Manager` Role (idempotent)
- `SaaS Category` master records (12 categories: spec union with mockup)

---

## First-time setup

After install, configure **SaaS Register Settings** (`/app/saas-register-settings`):

| Field | Set to | Why |
| --- | --- | --- |
| Felix (IT) | `felix@livio.com` | resolves `assigned_role_key=felix` on offboarding steps |
| Tech Lead | `david@livio.com` | resolves `assigned_role_key=tech_lead` |
| HR | HR user | resolves `assigned_role_key=hr` |
| Department Head (default) | fallback user | resolves `assigned_role_key=dept_head` when employee's department has no head user |
| Default Cost Center | e.g. `Tech / Infrastructure` | applied to created offboarding Projects |
| Notification Email | `felix@livio.com` | gets a summary mail when offboarding workflow is created |
| Default Offboarding SLA (days) | `1` | Task `exp_end_date = today + this` |

Then assign the `IT Manager` role to Felix.

---

## How it works

### `seats_active` — auto-computed

The `seats_active` Int on each `SaaS Application` is **read-only on the form**. It's recomputed inside `SaaSAccess.after_insert` / `on_update` / `on_trash` by:

```python
frappe.db.count("SaaS Access", {"saas_application": app, "revoke_status": "Active"})
```

The hook calls `frappe.db.set_value(..., update_modified=False)` — synchronous, no scheduler delay, so the value is consistent within a single request.

### Offboarding trigger

`saas_register.saas_register.employee_hooks.on_employee_update` is bound to Employee's `on_update` and `after_insert`.

Activation condition:
- `doc.status` ∈ `{"Left", "Resigned", "Terminated"}` (or contains those tokens — for custom statuses)
- AND `status` actually changed in this save

What it does:
1. Lookup all `SaaS Access` rows where `employee = doc.name` AND `revoke_status = "Active"`.
2. For each access row:
   - Flip `revoke_status` to `Pending Revoke`.
   - For each `SaaS Offboarding Step` on the linked SaaS Application, create a **ToDo** (via `frappe.desk.form.assign_to.add`) for the User resolved from the step's `assigned_role_key` (felix / tech_lead / dept_head / hr) against **SaaS Register Settings**. Falls back to `Settings.hr_user` when the role_key doesn't resolve.
   - The ToDo's `reference_type` / `reference_name` point back to the `SaaS Access` row so clicking it opens the access record.
   - `priority = High` for steps that require password rotation, `Medium` otherwise.
   - `date = today + Default Offboarding SLA` (default 1 day).
3. If no offboarding steps are configured for an app, a fallback "Revoke account in admin panel" ToDo is still created so nothing slips through.
4. Send a summary email to the Notification Email.

The whole block is wrapped in `try/except` and logs to **Error Log** on failure — Employee save is **never** blocked.

> **Note on idempotency.** Offboarding ToDos are created directly (not via `assign_to.add`) so each step gets its own ToDo even when the same user is the assignee for multiple steps. This is deliberate — each step should be independently checkable. If you re-trigger an offboarding (e.g. by toggling status off and back to Left), the trigger only fires when status actually changes, so accidental re-runs are rare; if they happen, you may need to manually delete duplicate ToDos.

> **Why ToDos and not a Project?** SaaS offboarding is a stream of small single-owner actions, not a project with phases. ToDos land in each owner's inbox and bell notification with no project-management overhead — and HR can sweep them with a single filter on `/app/todo`.

> **Note on Employee status options.** Stock ERPNext only ships `Active / Inactive / Suspended / Left`. To add `Resigned` or `Terminated` as a real selectable value, customize the Employee doctype's `status` field via `Customize Form`. The trigger already accepts those values without code changes.

### Renewal expiry trigger

A daily scheduler job `saas_register.saas_register.application_hooks.check_expiring_apps` runs once per day (Frappe's `scheduler_events.daily`).

For every Active SaaS Application whose `renewal_date` is **today**, it creates a ToDo on:
- the application's `business_owner` (resolved to their `user_id`), if set
- `Settings.felix_user`
- fallback to `Settings.hr_user` if neither of the above resolves

The ToDo's `reference_type` is `SaaS Application` and clicking it opens the app. Job is idempotent — it skips creating a ToDo if one already exists today for the same (app, user). Apps marked `Kill-Replace` are excluded since you've decided to drop them.

Manual invocation for testing:

```bash
bench --site <site> execute saas_register.saas_register.application_hooks.check_expiring_apps
```

### Revoke Now button

Form `.js` on `SaaS Access` adds a red **Revoke Now** button (hidden when already Revoked). It prompts for an optional reason, asks for confirmation, then calls the whitelisted server method `saas_register.saas_register.doctype.saas_access.saas_access.revoke_now`, which sets `revoke_status="Revoked"`, fills `revoked_date=today` and `revoked_by=frappe.session.user`, and saves. The save triggers `on_update`, which decrements `seats_active` on the parent SaaS Application.

### Permissions

Per the spec matrix (in [reference/saas_register_build_spec.md](../../reference/saas_register_build_spec.md)):

| Role | SaaS Application | SaaS Access | Settings | SaaS Spend Report |
| --- | --- | --- | --- | --- |
| System Manager | full | full | full | view |
| **IT Manager** (custom role created by this app) | full | full | full | view |
| HR Manager | read | read | – | view |
| Department Head | read (own dept via permission_query) | read (own dept) | – | view |
| Employee Self Service | – | read (own only via permission_query) | – | – |

The "own department" / "own employee" filtering for `SaaS Access` is implemented in [saas_register/saas_register/permissions.py](saas_register/saas_register/permissions.py), wired via `permission_query_conditions` and `has_permission` hooks in `hooks.py`.

### Linking Purchase Invoices

A SaaS app accumulates many invoices over its life (monthly bills, annual renewals, mid-cycle adjustments). Rather than a single `linked_invoice` field on the application, the app installs a **Custom Field** `saas_application` on **Purchase Invoice** (Link → SaaS Application) — shipped via fixtures so it auto-syncs on install/migrate.

How to use it:

1. Create or open a Purchase Invoice in ERPNext.
2. In the supplier section there's now a **SaaS Application** field — set it to the app this invoice pays for.
3. On the SaaS Application form, the **Connections** card "Purchase Invoice" automatically lists every invoice tagged to that app. The total dollar amount per app over a period is also queryable from the same field.

Standard filter on Purchase Invoice list lets you slice all SaaS spend by app.

### Multi-tier pricing

Many SaaS products have multiple paid tiers running in parallel (e.g. Anthropic Claude with **Pro / Team / Enterprise**). The `SaaS Application` form has a **Tiers** child table where each row captures `tier_name`, `seats_paid`, and `monthly_cost`. The parent's `seats_paid` and `monthly_cost` are **read-only rollups** auto-computed in `validate()`. A derived `plan_summary` (e.g. `"Pro 18 / Team 8 / Enterprise 4"`) feeds the list view's Plan column.

On `SaaS Access`, the **Tier** field is an Autocomplete populated by the form `.js` calling `get_tiers(saas_application)`. When you pick a tier, `monthly_cost_share` auto-fills with that tier's per-seat cost (`tier.monthly_cost / tier.seats_paid`). You can still override the share manually for special-case pricing.

### SaaS Spend Report

Script Report at `/app/query-report/SaaS Spend`. Returns:
- 14 columns: app, vendor, category, plan, cost center, status, seats paid/active/utilization, monthly/annual cost, renewal, days to renewal.
- 4 KPI tiles: total monthly spend (Active apps), active app count, underutilized seats (≥25% unused), renewals in next 60 days.
- Bar chart: monthly spend by cost center.
- Filters: month (default current), cost_center, status, vendor.
- PDF + Excel export via standard report-page buttons.

### SaaS Spend Forecast

Script Report at `/app/query-report/SaaS Spend Forecast`. 12-month rolling projection.

- One row per SaaS Application + a Total row at the bottom.
- One column per month (Jan / Feb / ...) plus a 12-month total column.
- Annual / Multi-year billing → amortized as `monthly_cost` every month (smooth budget view).
- Apps marked **Kill-Replace** drop to zero the month after their next `renewal_date` (highlighted red).
- KPI tiles: 12-month total, average monthly, peak month, Δ month 12 vs month 1.
- Line chart: total monthly forecast across the horizon.
- Filters: start_month (default current month-start), cost_center, status.

### SaaS Access Matrix

Script Report at `/app/query-report/SaaS Access Matrix`. Pivot of **Employee × SaaS Application**.

- Rows: Employees (filtered by department, status). Default shows Active + recently Left (so offboarding gaps are visible).
- Columns: each SaaS Application gets its own column.
- Cell encoding: ✓ green = Active access, ⏳ orange = Pending Revoke / In Progress, ✗ red = Revoked, blank = no access. Hovering shows the tier name.
- Last column: count of Active apps per employee.
- KPI tiles: Employees, Applications, Active Access Rows, Left w/ Open Revoke.
- Bar chart: active users per app.
- Filters: department, employee_status, include_revoked, include_no_access.

---

## Test plan (manual)

Run from any browser logged in as Administrator on the site you installed to.

### 1. CSV bulk import

- Go to **SaaS Application list → Menu → Import**.
- Upload a CSV with 20 apps. Expected: import succeeds, no errors.
- Then **SaaS Access list → Menu → Import** with 100 rows. Expected: `seats_active` ticks up live on each parent (refresh the SaaS Application list to confirm column).

### 2. Offboarding trigger

- Open any Employee with at least one Active `SaaS Access` row.
- Set **Status = Left**, save.
- Within ~5 seconds:
  - One ToDo per (app × offboarding step) shows up at `/app/todo` for the resolved owners (Felix, Tech Lead, HR per `assigned_role_key`; fallback `hr_user`).
  - All previously-Active SaaS Access rows for the employee are now `Pending Revoke`.
  - Notification email sent to `notify_email` (visible in Email Queue if SMTP isn't configured).
  - Each ToDo's reference is the SaaS Access row — clicking the ToDo opens the access record.

### 2b. Renewal expiry trigger

- Set a SaaS Application's `renewal_date` to today.
- Run `bench --site <site> execute saas_register.saas_register.application_hooks.check_expiring_apps`.
- Expected: ToDos created on `business_owner`'s user + `Settings.felix_user`; visible at `/app/todo`. Re-running the job is idempotent and won't duplicate.

### 3. Seats refresh latency

- Add a SaaS Access row → reload the parent SaaS Application form. `Seats Active` is +1.
- Mark the access row as Revoked → reload. `Seats Active` is -1. Should happen well within 2 seconds.

### 4. Spend report month total

- Run the report with no filters.
- Confirm "Total Monthly Spend" tile equals the sum of `monthly_cost` over Active apps in the table (±1 AED).

### 5. List view colors

- SaaS Application list → status indicator: green for Active, yellow for Review, red for Kill-Replace.
- SaaS Access list → indicator follows the same color rules per `revoke_status`.

### 6. Department-restricted access

- Log in as a User with only the `Department Head` role + their User linked to an Employee in Department X.
- Open SaaS Access list. Should see only rows where `department = X`. Other departments' access rows are filtered out at the SQL level (`permission_query_conditions`).
- Same for `Employee Self Service` — should see only own employee's rows.

### 7. Automated smoke

A quick scripted smoke run (to be executed via `bench --site <site> console`):

```python
import frappe
from frappe.utils import today
from saas_register.saas_register.doctype.saas_access.saas_access import revoke_now

emp = frappe.db.get_value("Employee", {}, "name")
app = "SAAS-0008"  # or any seeded app

before = frappe.db.get_value("SaaS Application", app, "seats_active") or 0
acc = frappe.get_doc({
    "doctype": "SaaS Access",
    "employee": emp,
    "saas_application": app,
    "revoke_status": "Active",
    "granted_date": today(),
}).insert(ignore_permissions=True)
assert frappe.db.get_value("SaaS Application", app, "seats_active") == before + 1

revoke_now(acc.name, "test")
assert frappe.db.get_value("SaaS Application", app, "seats_active") == before
print("OK")
```

---

## Out of scope (Phase 2)

Per spec section 8 — not built:

- Google Workspace API (`last_login`, active users)
- 1Password SCIM (vault membership / rotation status)
- Webhook from Purchase Invoice → auto-update `monthly_cost`
- Slack notification on offboarding task creation
- AI-driven cost anomaly alerts

---

## Contributing

Pre-commit configured with `ruff`, `eslint`, `prettier`, `pyupgrade`:

```bash
cd apps/saas_register
pre-commit install
```

## License

MIT
