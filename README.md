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
| Child | `SaaS Offboarding Step` (child of SaaS Application) | `.../doctype/saas_offboarding_step` |
| Single | `SaaS Register Settings` (role_key → User mapping, defaults) | `.../doctype/saas_register_settings` |
| Server logic | Employee `on_update` hook → offboarding workflow | `saas_register/saas_register/employee_hooks.py` |
| Server logic | SaaS Access hooks → recompute `seats_active` on parent | `saas_register/saas_register/doctype/saas_access/saas_access.py` |
| Server logic | Permission query / `has_permission` for SaaS Access | `saas_register/saas_register/permissions.py` |
| Client | Form `.js` for "Revoke Now" button | `.../doctype/saas_access/saas_access.js` |
| Client | Form `.js` for Application dashboard utilization indicator + recompute | `.../doctype/saas_application/saas_application.js` |
| Report | `SaaS Spend` (Script Report with `report_summary` KPI tiles + chart) | `.../report/saas_spend` |
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
2. Create a **Project** named `Offboarding — {employee_name} — {today}`. `expected_end_date = today + Default Offboarding SLA`.
3. For each access row → flip status to `Pending Revoke`, then for each `SaaS Offboarding Step` on the linked SaaS Application, create a **Task** under the Project with subject `{app_name} — {step_description}`. The task is assigned (via Frappe ToDo `assign_to`) to the User resolved from the step's `assigned_role_key` against `SaaS Register Settings`. Tasks marked `requires_password_rotation` get tagged `password-rotation`.
4. If no offboarding steps are configured for an app, a fallback "Revoke account in admin panel" Task is still created so nothing slips through.
5. Send a summary email to the Notification Email.

The whole block is wrapped in `try/except` and logs to **Error Log** on failure — Employee save is **never** blocked.

> **Note on Employee status options.** Stock ERPNext only ships `Active / Inactive / Suspended / Left`. To add `Resigned` or `Terminated` as a real selectable value, customize the Employee doctype's `status` field via `Customize Form`. The trigger already accepts those values without code changes.

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

### SaaS Spend Report

Script Report at `/app/query-report/SaaS Spend`. Returns:
- 14 columns: app, vendor, category, plan, cost center, status, seats paid/active/utilization, monthly/annual cost, renewal, days to renewal.
- 4 KPI tiles: total monthly spend (Active apps), active app count, underutilized seats (≥25% unused), renewals in next 60 days.
- Bar chart: monthly spend by cost center.
- Filters: month (default current), cost_center, status, vendor.
- PDF + Excel export via standard report-page buttons.

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
  - A new Project `Offboarding — {employee_name} — {today}` exists in /app/project.
  - Each access row's offboarding steps got a Task on that project.
  - All previously-Active SaaS Access rows for the employee are now `Pending Revoke`.
  - Notification email sent to `notify_email` (visible in Email Queue if SMTP isn't configured).

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
