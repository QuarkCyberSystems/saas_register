# SaaS & Access Register (`saas_register`)

A Frappe v15/v16 app for **Livio** that:

1. **Catalogues** every paid SaaS app across three subscription patterns (Shared / Per-User / Usage-Based).
2. **Tracks access** — which Employee has access to which app, at which tier.
3. **Gives Finance a spreadsheet-style monthly cost workflow** with audit trail.
4. **Auto-creates offboarding ToDos** when HR marks an Employee as Resigned.
5. **Powers cross-departmental actions** (IT raises a "Reduce Seats" action, Finance reviews, IT executes) via the **SaaS Action** doctype.
6. **Three role-filtered Workspaces** (IT / Finance / HR) over a single shared data model.

Reuses standard ERPNext **Supplier**, **Employee** (HRMS), **Cost Center**, **Currency**, **Department**, and **Purchase Invoice**.

This is **Phase 1**. Phase 2 (separate effort) builds the n8n workflows that consume the webhook contracts defined here.

---

## Architecture

```
                              ┌──────────────────────────┐
                              │   SaaS Application       │
                              │   subscription_model:    │
                              │     Shared / Per-User /  │
                              │     Usage-Based          │
                              │   naming: APP-YYYY-####  │
                              └──────────────────────────┘
                                   │       │       │
              ┌────────────────────┘       │       └────────────────┐
              ▼                            ▼                        ▼
   ┌────────────────────┐      ┌──────────────────────┐  ┌──────────────────────┐
   │ SaaS Monthly Cost  │      │ SaaS Cost Allocation │  │ SaaS Offboarding     │
   │ (child) — actual   │      │ (child) — who pays   │  │ Step (child) —       │
   │ monthly spend      │      │ what % (sum = 100)   │  │ revoke playbook      │
   └────────────────────┘      └──────────────────────┘  └──────────────────────┘

   ┌────────────────────────────┐      ┌────────────────────────────┐
   │   SaaS Access              │      │   SaaS Action              │
   │   employee × app           │      │   ACT-YYYY-####             │
   │   tier_or_plan, per-user   │      │   Keep / Audit / Reduce /  │
   │   renewal & billing, role  │      │   Cancel etc.              │
   │   on_app, revoke_status    │      │   savings, lifecycle       │
   └────────────────────────────┘      └────────────────────────────┘
              ▲                                  ▲
              │ Employee.status =                │ Cross-dept handoff:
              │ Resigned/Terminated              │ Finance raises, IT
              │ → ToDo per (access × step)       │ executes, Finance
              │                                  │ confirms savings
        ┌─────┴───┐         ┌──────────┐    ┌────┴──────┐
        │   HR    │ ───────→│    IT    │ ───→│  Finance  │
        └─────────┘         └──────────┘    └───────────┘
```

Three Frappe **Workspaces** project the same shared model:

- **SaaS — IT Operations** (System Manager + IT Manager) — inventory, access, actions, offboarding queue
- **SaaS — Finance** (System Manager + Finance Manager) — Monthly Cost Entry, spend reports, actions by savings
- **SaaS — HR** (System Manager + HR Manager) — HR-category apps, recent resignations, pending revokes, access matrix

---

## Doctype map

| Doctype | Kind | Location |
| --- | --- | --- |
| `SaaS Application` | Master, autoname `APP-.YYYY.-.####` | `saas_register/saas_register/doctype/saas_application` |
| `SaaS Access` | Standalone, autoname `SAC-.YYYY.-.####` | `.../doctype/saas_access` |
| `SaaS Action` | Standalone, autoname `ACT-.YYYY.-.####` | `.../doctype/saas_action` |
| `SaaS Monthly Cost` | Child of SaaS Application | `.../doctype/saas_monthly_cost` |
| `SaaS Cost Allocation` | Child of SaaS Application | `.../doctype/saas_cost_allocation` |
| `SaaS Offboarding Step` | Child of SaaS Application | `.../doctype/saas_offboarding_step` |
| `SaaS Category` | Master (used by SaaS Application.category Link) | `.../doctype/saas_category` |
| `SaaS Register Settings` | Single | `.../doctype/saas_register_settings` |

Server-side wiring uses standard Frappe `doc_events` hooks (not runtime Server Script records), so it's version-controlled and ships with the app.

---

## Install

```bash
# from frappe-bench root
bench get-app saas_register <repo-url> --branch main
bench --site <site> install-app saas_register
```

Already installed sites need a migrate to pick up new doctypes and fixtures:

```bash
bench --site <site> migrate
```

If the app was installed from an earlier (empty-skeleton) revision, the `after_install` hook won't have run — re-trigger seed data manually:

```bash
bench --site <site> execute saas_register.install.after_install
```

What `after_install` does:
- Creates 6 sample SaaS Applications demonstrating all three subscription models (Google Workspace / HubSpot / Atlassian Jira / Anthropic Claude → Shared; AWS → Usage-Based; ChatGPT Plus → Per-User). Each app ships 3 monthly cost rows so `avg_monthly_cost` is populated. Skipped if records with the same `app_name` already exist.

What gets imported automatically every migrate (via `fixtures/`):
- `IT Manager` and `Finance Manager` Roles (idempotent)
- 14 `SaaS Category` master records (full v3 enum)
- `Purchase Invoice-saas_application` Custom Field (so Purchase Invoices can tag the SaaS app they pay for)

---

## First-time setup

After install, configure **SaaS Register Settings** (`/app/saas-register-settings`):

| Field | Set to | Why |
| --- | --- | --- |
| **IT Manager** | `it@livio.com` (e.g. Alex Carter) | resolves `assigned_role_key=it_manager` on offboarding steps; owns offboarding |
| **Tech Lead** | tech-lead user | resolves `tech_lead` role_key |
| **Finance Manager** | `finance@livio.com` (e.g. Sam Patel) | resolves `finance_manager` role_key; default raiser for cost-driven actions |
| **HR Manager** | `hr@livio.com` (e.g. Robin Walsh) | resolves `hr_manager` role_key |
| **Department Head (default)** | fallback user | resolves `dept_head` role_key when employee's department has no head |
| **Default Cost Center** | e.g. "Tech / Infrastructure" | applied to created offboarding artifacts |
| **Default Offboarding SLA (days)** | `1` | ToDo `date = today + this` |
| **Offboarding Alert Recipients** | comma-separated emails | summary mail when offboarding workflow is created |
| **n8n Webhook Base URL** | `https://n8n.livio.com` (when Phase 2 ready) | Phase-2 prep — see [Webhook contracts](#webhook-contracts-phase-2-prep) below |

Then assign the `IT Manager` and `Finance Manager` roles to the relevant users.

---

## Subscription models

The most consequential design decision in v3:

| Aspect | `Shared` | `Per-User` | `Usage-Based` |
| --- | --- | --- | --- |
| Contract structure | One company contract | One contract per access record | One contract, variable usage |
| Renewal date | On Application (`renewal_date`) | On SaaS Access (`per_user_renewal_date`) | N/A |
| Seats counted | Yes (`seats_paid` set, `seats_active` auto) | No (`seats_active` = count of active access) | No |
| Per-access cost | Optional (`monthly_cost_share`) | **Required** (`monthly_cost_share`) | N/A |
| Mixed tiers in one app | **Yes** — `tier_or_plan` on access | Yes (each is its own contract anyway) | N/A |
| Monthly cost entry | Finance enters one total per month | Finance enters one consolidated total per month | Finance enters actual usage cost per month |
| Examples | Google Workspace, HubSpot, Anthropic Claude (mixed tiers), Atlassian Jira | ChatGPT Plus, individual Adobe, Calendly individual | AWS, Twilio, OpenAI API, Cloudflare |

**Mixed-tier handling for Shared apps:** Anthropic Claude with some users on Pro, some on Team, some on Enterprise is *one* Shared subscription. The `tier_or_plan` Data field on each SaaS Access captures the individual entitlement; `monthly_cost_share` captures the per-seat cost. The contract renews on one date. Tier autosuggest on the SaaS Access form pulls distinct existing values for the chosen app.

---

## How it works

### `seats_active` — auto-computed

Read-only on the form. Recomputed inside `SaaSAccess.after_insert / on_update / on_trash` by counting Active SaaS Access rows. Synchronous, no scheduler delay; the value is consistent within a single request.

### `avg_monthly_cost` — read-only rolling average

Computed in `SaaSApplication.validate()` as the mean of the latest 3 `monthly_costs` rows (sorted by month desc). Visible at the top of the Pricing & Seats tab so Finance and IT see "what we've been paying" at a glance.

### `cost_allocations` — sum to 100%

Validated in `SaaSApplication.validate()`. If any rows exist, their `allocation_percent` must sum to 100 (±0.01). Zero rows = uncategorised/company-wide spend (allowed).

### Offboarding trigger

`saas_register.saas_register.employee_hooks.on_employee_update` is bound to Employee's `on_update` and `after_insert`.

Activation condition:
- `doc.status` ∈ `{"Left", "Resigned", "Terminated"}` (or contains those tokens)
- AND `status` actually changed in this save

What it does:
1. Lookup all `SaaS Access` rows where `employee = doc.name` AND `revoke_status = "Active"`.
2. For each access row:
   - Flip `revoke_status` to `Pending Revoke`.
   - For each `SaaS Offboarding Step` on the linked SaaS Application, create a **ToDo** directly (not via `assign_to.add` — we want one ToDo per step, not deduped per assignee). Reference = the SaaS Access row.
   - Assignee resolved from `assigned_role_key` (`it_manager / tech_lead / finance_manager / hr_manager / dept_head`) against **SaaS Register Settings**, with `hr_manager` as fallback.
   - `priority = High` for password-rotation steps, `Medium` otherwise.
   - `date = today + Default Offboarding SLA` (default 1 day).
3. If no offboarding steps configured for an app, a fallback "Revoke account in admin panel" ToDo is created so nothing slips through.
4. Send summary email to `offboarding_alert_recipients`.

The whole block is wrapped in `try/except` and logs to **Error Log** on failure — Employee save is **never** blocked.

> **Why ToDos and not Project + Tasks?** SaaS offboarding is a stream of small single-owner actions, not a project with phases. ToDos land in each owner's inbox + bell notification with no project-management overhead. HR explicitly asked for this; v3 spec's Project+Task code can be re-mapped to ToDos for n8n callbacks (n8n marks a ToDo as Closed instead of a Task as Done).

> **Employee status options.** Stock ERPNext only ships `Active / Inactive / Suspended / Left`. To add `Resigned` or `Terminated` as a real selectable value, customize the Employee doctype's `status` field via `Customize Form`. The trigger already accepts those values.

### Renewal expiry — daily ToDo + 30/14/7-day webhook

Two daily scheduler jobs (wired in `hooks.scheduler_events.daily`):

1. **`check_expiring_apps`** — for every Active app with `renewal_date == today`, create a ToDo on `business_owner.user_id` + `Settings.it_manager` (fallback `hr_manager`). Idempotent on re-run.
2. **`emit_renewal_webhooks`** — for every Active app with `renewal_date` exactly 30 / 14 / 7 days out, POST `{app, app_name, renewal_date, days_out, auto_renew, business_owner, business_owner_email, monthly_cost, currency}` to `{n8n_webhook_base_url}/saas/renewal-upcoming`. No-op when `n8n_webhook_base_url` is blank.

Manual invocation for testing:

```bash
bench --site <site> execute saas_register.saas_register.application_hooks.check_expiring_apps
bench --site <site> execute saas_register.saas_register.application_hooks.emit_renewal_webhooks
```

### Revoke Now button

Form `.js` on SaaS Access adds a red **Revoke Now** button (hidden when already Revoked). Prompts for an optional reason, asks for confirmation, calls the whitelisted `revoke_now` server method which sets `revoke_status=Revoked`, fills `revoked_date=today` and `revoked_by=frappe.session.user`. The save triggers `on_update`, which decrements `seats_active` on the parent.

### Monthly Cost Entry page

Custom Frappe Page at **`/app/monthly-cost-entry`** (Workspace: SaaS — Finance). Spreadsheet-style grid keyed by `(application, month)`.

- Loads all matching apps for the selected month. Shows `expected` (avg of previous 3 months) vs `actual` cell. Δ% highlighted amber if `|Δ| > 25%`.
- Inline-edit the **Actual** cell → blur autosaves via `upsert_monthly_cost(application, month, amount, notes)`.
- Old value preserved as **Error Log** entry titled `"SaaS Monthly Cost Audit"` with structured JSON (`application, month, old_amount, new_amount, user, timestamp`). Phase 1.5 promotes to a dedicated `SaaS Monthly Cost Audit` doctype.
- **Paste from spreadsheet** — paste 2 columns (app name, amount). Fuzzy-matches with substring + sequence-matcher ≥ 0.8 threshold. Preview shows matched/unmatched, then confirm to commit.

Server endpoints (all whitelisted, role-protected by the page):

| Method | What |
| --- | --- |
| `get_grid(month, status, category)` | Loads the grid |
| `upsert_monthly_cost(application, month, amount, notes)` | Inline save; audits to Error Log |
| `paste_monthly_costs(month, rows, commit)` | Fuzzy-match + bulk save |

### Permissions

Per v3 §5:

| Role | SaaS App | SaaS Access | SaaS Action | Monthly Cost Entry | Settings | Reports |
| --- | --- | --- | --- | --- | --- | --- |
| System Manager | Full | Full | Full | Use | Full | View |
| **IT Manager** (custom, shipped via fixture) | Full | Full | Full | Use | Full | View |
| **Finance Manager** (custom, shipped via fixture) | Read | Read | Full | **Use** | — | Full |
| HR Manager | Read | Read (own dept filter) | Read + Create | View | — | View |
| Department Head | Read (own dept) | Read (own dept) | Read (own dept) | — | — | View (own dept) |

The "own department" / "own employee" filtering for SaaS Access uses `permission_query_conditions` + `has_permission` hooks (see [permissions.py](saas_register/saas_register/permissions.py)).

---

## Reports

### SaaS Spend — Script Report

`/app/query-report/SaaS Spend`. KPI tiles (total monthly spend, active apps, underutilized seats, renewals ≤60 days), bar chart of spend by cost center, table of all Active apps. Filters: month, cost_center, status, vendor.

### SaaS Spend Forecast — Script Report

`/app/query-report/SaaS Spend Forecast`. 12-month projection. Annuals amortized 1/12 per month; Kill-Replace apps drop to zero after their next renewal. Per-app rows + totals row + line chart.

### SaaS Access Matrix — Script Report

`/app/query-report/SaaS Access Matrix`. Pivot of Employees × SaaS Applications. Cells colored by `revoke_status` (✓ green = Active, ⏳ orange = Pending Revoke / In Progress, ✗ red = Revoked). Filter by department / employee_status.

---

## Webhook contracts (Phase-2 prep)

Per v3 §3.5: define the integration contract in Phase 1 even though Phase 2 builds the consumers. Once `n8n_webhook_base_url` is set in Settings, admins create Frappe **Webhook** records by hand (UI: `/app/webhook`) — we don't ship them as fixtures because Frappe validates `request_url` at save time and trips on Jinja templates.

Four events, with the payload shapes n8n should expect:

### 1. Offboarding ToDo created

| Field | Source |
| --- | --- |
| Doctype | `ToDo` |
| Event | `after_insert` |
| Condition | `doc.reference_type == 'SaaS Access'` |
| Method | `POST` |
| URL | `{{ frappe.db.get_single_value('SaaS Register Settings', 'n8n_webhook_base_url') }}/saas/offboarding-todo-created` |
| Payload | `{ todo_name, allocated_to, description, reference_type, reference_name, priority, date }` |
| Phase 2 use | n8n suspends user via Google / HubSpot / 1Password / GitHub Admin APIs; callbacks to mark ToDo `status=Closed` |

### 2. SaaS Action created

| Field | Source |
| --- | --- |
| Doctype | `SaaS Action` |
| Event | `after_insert` |
| Condition | `doc.status == 'Open'` |
| URL | `{{ ... }}/saas/action-created` |
| Payload | `{ action_id, saas_application, app_name, action_type, status, priority, requested_by, assigned_to, due_date, projected_monthly_saving }` |
| Phase 2 use | Slack post to the right channel; create reminder |

### 3. Renewal upcoming (30 / 14 / 7 days)

Not a Webhook record — `application_hooks.emit_renewal_webhooks` POSTs directly from the daily scheduler.

| Field | Source |
| --- | --- |
| URL | `{n8n_webhook_base_url}/saas/renewal-upcoming` |
| Payload | `{ app, app_name, renewal_date, days_out (30/14/7), auto_renew, business_owner, business_owner_email, monthly_cost, currency }` |
| Phase 2 use | Email + Slack to business owner |

### 4. SaaS Monthly Cost updated (reverse direction)

| Field | Source |
| --- | --- |
| Doctype | `SaaS Monthly Cost` |
| Event | `on_update` |
| URL | `{{ ... }}/saas/monthly-cost-updated` |
| Payload | `{ row_name, parent_app, month, amount, source, last_edited_by }` |
| Phase 2 use | Phase 2 reverse-direction: n8n polls QuickBooks daily and POSTs to the `upsert_monthly_cost` whitelisted method. This webhook fires when a manual edit happens, useful for an "edits feed" in Slack. |

---

## Test plan (manual)

Run from any browser logged in as Administrator on the site you installed to.

### 1. CSV bulk import

- Go to **SaaS Application list → Menu → Import**. Upload a CSV with 20 apps. Expected: zero errors.
- Then **SaaS Access list → Menu → Import** with 100 rows. Expected: `seats_active` ticks up live; for any row whose parent app is `Per-User`, validation rejects rows missing `per_user_renewal_date` + `monthly_cost_share`.

### 2. Offboarding trigger

- Open any Employee with at least one Active `SaaS Access` row.
- Set **Status = Left**, save.
- Within ~5 seconds:
  - One ToDo per (app × offboarding step) shows up at `/app/todo` for the resolved owners.
  - All previously-Active SaaS Access rows for the employee are now `Pending Revoke`.
  - Notification email sent to `offboarding_alert_recipients`.
  - Each ToDo's reference is the SaaS Access row.

### 3. Subscription model field visibility

- Open a Per-User app (e.g. ChatGPT Plus). Expected: `renewal_date` + `auto_renew` + `seats_section` hidden on the form.
- Open a Usage-Based app (e.g. AWS). Expected: `seats_section` + `monthly_cost` hidden; `monthly_costs` table still visible.
- On a SaaS Access form for a Per-User app: `per_user_section` is required-marked and visible.

### 4. Cost Allocation 100%

- Open any SaaS Application, go to Cost Allocations tab. Add one row at 50%. Save → expect error `Cost Allocations must sum to 100%`. Bump to 100% → saves cleanly.

### 5. Monthly Cost Entry

- Open `/app/monthly-cost-entry`. Expected: grid loads within 2 seconds with all Active apps.
- Edit an Actual cell → blur → green "Saved" alert. Re-open page → value persists.
- Click **Menu → Paste from spreadsheet** → paste `Google Workspace\t5555\nAtlasian Jira\t1800\nSlack Workspace\t200`. Preview: 2 matched (typo tolerated), 1 unmatched. Confirm → saved.
- Check `/app/error-log` for entries titled `SaaS Monthly Cost Audit`. Each edit logged with old → new.

### 6. SaaS Action lifecycle

- Create a SaaS Action with status=Open. Confirm it appears in the **Workflow** connection on the SaaS Application form.
- Set status=Done without `actual_monthly_saving` → server throws. Fill it → saves cleanly.

### 7. Workspaces

- Log in as an IT Manager user → only **SaaS — IT Operations** is visible.
- Log in as a Finance Manager user → only **SaaS — Finance** is visible (Monthly Cost Entry shortcut present).
- Log in as an HR Manager user → only **SaaS — HR** is visible.

### 8. avg_monthly_cost rollup

- Open Anthropic Claude (or any app with 3+ monthly_costs rows). `avg_monthly_cost` shows the mean of the latest 3. Edit one row → save → re-open → avg recomputed.

### 9. Renewal alerts

- Set any app's `renewal_date` to today. Run `bench --site <site> execute saas_register.saas_register.application_hooks.check_expiring_apps`. Expected: ToDos at `/app/todo` on business_owner.user_id + Settings.it_manager. Re-run is idempotent.
- Set another app's `renewal_date` to today+30 days. Set `n8n_webhook_base_url` in Settings. Run `emit_renewal_webhooks`. Expected: POST attempted to `{base}/saas/renewal-upcoming`. If base is blank, no-op.

### 10. Automated smoke

```python
import frappe
from frappe.utils import today
from saas_register.saas_register.doctype.saas_access.saas_access import revoke_now

emp = frappe.db.get_value("Employee", {}, "name")
app = "APP-2026-0007"  # any seeded Shared app

before = frappe.db.get_value("SaaS Application", app, "seats_active") or 0
acc = frappe.get_doc({
    "doctype": "SaaS Access",
    "employee": emp,
    "saas_application": app,
    "tier_or_plan": "Business Plus",
    "revoke_status": "Active",
    "granted_date": today(),
}).insert(ignore_permissions=True)
assert frappe.db.get_value("SaaS Application", app, "seats_active") == before + 1
revoke_now(acc.name, "test")
assert frappe.db.get_value("SaaS Application", app, "seats_active") == before
print("OK")
```

---

## Acceptance criteria checklist

Per v3 §7:

- [ ] CSV migration imports all current apps with zero dropped rows. (Migration script deferred — see Phase 1.5 if needed.)
- [ ] Employee `status = "Resigned"` triggers ToDos within 5 seconds. All 7 edge cases handled.
- [ ] `seats_active` on SaaS Application updates within 2 seconds of any SaaS Access insert / update / delete.
- [ ] `avg_monthly_cost` recomputes when a SaaS Monthly Cost row is added or edited.
- [ ] Setting `subscription_model = Per-User` hides `renewal_date` and `seats_paid` on the form; makes `per_user_renewal_date` required on its access records.
- [ ] When `tier_or_plan` is set on access records of a Shared app, the App form's Access connection groups records by tier. (Implemented in the connection card — Frappe groups by `link_fieldname` when count > 1.)
- [ ] Monthly Cost Entry loads all Active apps with existing monthly cost values for selected month within 2 seconds.
- [ ] Editing a cell auto-saves on blur; old value logged to Error Log titled "SaaS Monthly Cost Audit".
- [ ] Paste-from-spreadsheet fuzzy-matches at least 80% of typical inputs.
- [ ] Cost Allocation rows validate to 100% sum on save.
- [ ] Spend Dashboard month total = `SUM(SaaS Monthly Cost.amount)` for month over Active apps within ±1 AED.
- [ ] Finance Manager can view all Actions, edit only their own, cannot edit App identity fields.
- [ ] HR Manager cannot view SaaS Access records outside their department.
- [ ] All three department Workspaces load with curated content and respect role-based filtering.

---

## Conflict with v3 spec — kept-from-prior-iterations

The v3 spec arrived after several iterative improvements that conflicted with it. Documented here so the client sees the deltas:

| Topic | v3 says | What's shipped | Why |
| --- | --- | --- | --- |
| Offboarding output | Project + Tasks | **ToDos** (one per step) | HR explicitly asked for ToDos; less project-mgmt overhead; same Phase-2 n8n contract |
| Category | Select enum (14 fixed values) | **Linked `SaaS Category` doctype** seeded with all 14 v3 values | Allows adding categories without a code change |
| Invoice link | Free-text `invoice_reference` | Free-text `invoice_reference` **+** Purchase Invoice Custom Field with Connection card | Free text for unstructured refs; PI link for actual ERPNext invoices |
| Renewal alerts | Webhooks only (30/14/7 days) | **Both** — daily ToDo on renewal_date AND webhooks at 30/14/7 | v1 user-facing alerting works without n8n |
| Naming series | `APP-.YYYY.-.####` | Same ✓ | |
| Tier model | `tier_or_plan` Data field on Access | Same ✓ (reverted from earlier linked-doctype attempt) | |

---

## Out of scope (Phase 2)

Per v3 §8:

- **n8n auto-revocation workflows** (Google Workspace, HubSpot, 1Password, GitHub, per-user vendor APIs)
- **n8n cost ingest** from QuickBooks (POSTs to our `upsert_monthly_cost` endpoint)
- **n8n renewal reminders** via Slack
- **n8n cost-anomaly alerts**
- **QuickBooks Purchase Invoice linkage** (current is free-text + Custom Field)
- **Google Workspace API** for `last_login`, active user counts, MFA status
- **1Password SCIM** → vault membership and password rotation tracking
- **Employee self-service portal**
- **CSV upload** for Monthly Cost Entry (currently paste-only)
- **Dedicated `SaaS Monthly Cost Audit` doctype** (currently Error Log)
- **Legacy CSV migration script** (deferred — write `bench execute saas_register.migration.run` against the legacy CSV when needed)

---

## Contributing

Pre-commit configured with `ruff`, `eslint`, `prettier`, `pyupgrade`:

```bash
cd apps/saas_register
pre-commit install
```

## License

MIT
