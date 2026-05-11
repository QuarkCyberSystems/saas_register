// Monthly Cost Entry page
// Spreadsheet-style grid for Finance to capture actual monthly SaaS spend.

frappe.pages["monthly-cost-entry"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Monthly Cost Entry"),
		single_column: true,
	});

	new MonthlyCostEntry(page);
};

class MonthlyCostEntry {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.dirty = new Set();
		this.month = frappe.datetime.month_start();
		this.status_filter = "Active";
		this.category_filter = "";
		this.search_q = "";

		this.setup_toolbar();
		this.render_skeleton();
		this.load();
	}

	// ---------------------------------------------------------------------
	// Toolbar
	// ---------------------------------------------------------------------

	setup_toolbar() {
		const me = this;

		this.page.add_field({
			fieldtype: "Date",
			fieldname: "month",
			label: __("Month"),
			default: this.month,
			change: () => {
				me.month = frappe.datetime.month_start(me.page.fields_dict.month.get_value());
				me.load();
			},
		});

		this.page.add_field({
			fieldtype: "Select",
			fieldname: "status",
			label: __("App Status"),
			options: "Active\nReview\nKill-Replace\nAll",
			default: "Active",
			change: () => {
				me.status_filter = me.page.fields_dict.status.get_value() || "Active";
				me.load();
			},
		});

		this.page.add_field({
			fieldtype: "Link",
			fieldname: "category",
			label: __("Category"),
			options: "SaaS Category",
			change: () => {
				me.category_filter = me.page.fields_dict.category.get_value() || "";
				me.load();
			},
		});

		this.page.add_field({
			fieldtype: "Data",
			fieldname: "search",
			label: __("Search"),
			change: () => {
				me.search_q = (me.page.fields_dict.search.get_value() || "").toLowerCase();
				me.render_rows();
			},
		});

		this.page.set_primary_action(__("Save All"), () => me.save_all());
		this.page.add_menu_item(__("Paste from spreadsheet"), () => me.show_paste_dialog());
	}

	render_skeleton() {
		this.page.main.html(`
			<div class="mce-wrap" style="padding: 12px 0;">
				<div class="mce-status" style="margin-bottom:8px;color:var(--text-muted);font-size:12px"></div>
				<table class="table table-bordered mce-grid" style="font-size:13px;">
					<thead style="background:#FAFBFC">
						<tr>
							<th style="width:28%">Application</th>
							<th>Model</th>
							<th>Cost Center</th>
							<th class="text-right">Expected</th>
							<th class="text-right" style="background:#FFFBEA">Actual (${frappe.datetime.global_date_format(this.month)})</th>
							<th class="text-right">Δ%</th>
							<th>Note</th>
						</tr>
					</thead>
					<tbody class="mce-body">
						<tr><td colspan="7" class="text-center text-muted">${__("Loading…")}</td></tr>
					</tbody>
				</table>
			</div>
		`);
	}

	// ---------------------------------------------------------------------
	// Data
	// ---------------------------------------------------------------------

	async load() {
		const me = this;
		this.page.main.find(".mce-body").html(
			`<tr><td colspan="7" class="text-center text-muted">${__("Loading…")}</td></tr>`
		);
		const r = await frappe.call({
			method: "saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry.get_grid",
			args: {
				month: this.month,
				status: this.status_filter,
				category: this.category_filter,
			},
		});
		this.rows = r.message || [];
		this.dirty.clear();
		this.update_header();
		this.render_rows();
	}

	update_header() {
		this.page.main.find(".mce-status").text(
			__("{0} apps · month {1}", [this.rows.length, frappe.datetime.global_date_format(this.month)])
		);
	}

	render_rows() {
		const me = this;
		const tbody = this.page.main.find(".mce-body");
		const q = me.search_q;
		const rows = q
			? me.rows.filter(
					(r) =>
						(r.app_name || "").toLowerCase().includes(q) ||
						(r.vendor || "").toLowerCase().includes(q)
				)
			: me.rows;

		if (!rows.length) {
			tbody.html(`<tr><td colspan="7" class="text-center text-muted">${__("No apps match the filters")}</td></tr>`);
			return;
		}

		tbody.html(
			rows
				.map((r) => {
					const delta = me.compute_delta(r);
					const deltaCell =
						delta == null
							? "—"
							: `<span style="color:${Math.abs(delta) > 25 ? "#FF9800" : "var(--text-muted)"};font-weight:500">${delta > 0 ? "+" : ""}${delta.toFixed(1)}%</span>`;
					const actual = r.actual_amount == null ? "" : r.actual_amount;
					return `
				<tr data-app="${frappe.utils.escape_html(r.app)}">
					<td><a href="/app/saas-application/${frappe.utils.escape_html(r.app)}">${frappe.utils.escape_html(r.app_name)}</a></td>
					<td><span class="badge" style="background:#E8F4FE;color:#2490EF;font-size:11px;font-weight:500;padding:2px 6px;border-radius:3px">${frappe.utils.escape_html(r.subscription_model || "")}</span></td>
					<td style="color:var(--text-muted)">${frappe.utils.escape_html(r.cost_center || "—")}</td>
					<td class="text-right" style="color:var(--text-muted);font-variant-numeric:tabular-nums">${me.fmt(r.expected_amount, r.currency)}</td>
					<td class="text-right" style="font-variant-numeric:tabular-nums;background:#FFFBEA">
						<input type="number" class="mce-actual form-control"
							style="text-align:right;background:transparent;border:none;padding:2px 4px;font-variant-numeric:tabular-nums"
							value="${actual}"
							placeholder="0">
					</td>
					<td class="text-right">${deltaCell}</td>
					<td><input type="text" class="mce-note form-control" style="border:none;padding:2px 4px;font-size:12px" value="${frappe.utils.escape_html(r.notes || "")}" placeholder="…"></td>
				</tr>`;
				})
				.join("")
		);

		// Bind input handlers
		tbody.find("input.mce-actual").on("blur", function () {
			const tr = $(this).closest("tr");
			const app = tr.data("app");
			const val = $(this).val();
			const note = tr.find("input.mce-note").val();
			me.upsert_cell(app, val, note);
		});

		tbody.find("input.mce-note").on("blur", function () {
			const tr = $(this).closest("tr");
			const app = tr.data("app");
			const val = tr.find("input.mce-actual").val();
			const note = $(this).val();
			if (val !== "") me.upsert_cell(app, val, note);
		});
	}

	compute_delta(r) {
		if (r.expected_amount == null || r.expected_amount === 0) return null;
		if (r.actual_amount == null) return null;
		return ((r.actual_amount - r.expected_amount) / r.expected_amount) * 100;
	}

	fmt(amount, currency) {
		if (amount == null || amount === "") return "—";
		return format_currency(amount, currency || "AED");
	}

	// ---------------------------------------------------------------------
	// Save
	// ---------------------------------------------------------------------

	async upsert_cell(app, amount, notes) {
		if (amount === "" || amount == null) return;
		try {
			const r = await frappe.call({
				method: "saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry.upsert_monthly_cost",
				args: { application: app, month: this.month, amount: parseFloat(amount), notes },
			});
			// Mirror saved value back into local cache for delta recompute
			const row = this.rows.find((r) => r.app === app);
			if (row) {
				row.actual_amount = parseFloat(amount);
				row.notes = notes || "";
			}
			frappe.show_alert({ message: __("Saved"), indicator: "green" }, 2);
			this.render_rows();
		} catch (e) {
			frappe.show_alert({ message: __("Save failed: {0}", [e.message || ""]), indicator: "red" });
		}
	}

	async save_all() {
		const me = this;
		const rows = me.page.main.find("tr[data-app]").toArray();
		let saved = 0;
		for (const tr of rows) {
			const $tr = $(tr);
			const app = $tr.data("app");
			const val = $tr.find("input.mce-actual").val();
			const note = $tr.find("input.mce-note").val();
			if (val === "" || val == null) continue;
			try {
				await frappe.call({
					method: "saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry.upsert_monthly_cost",
					args: { application: app, month: me.month, amount: parseFloat(val), notes: note },
				});
				saved++;
			} catch (e) {
				// keep going
			}
		}
		frappe.show_alert({ message: __("Saved {0} rows", [saved]), indicator: "green" });
		me.load();
	}

	// ---------------------------------------------------------------------
	// Paste dialog
	// ---------------------------------------------------------------------

	show_paste_dialog() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __("Paste from spreadsheet"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options:
						"<p>Paste two tab- or comma-separated columns: <b>Application</b>, <b>Amount</b>. One row per line. App name matching is fuzzy.</p>",
				},
				{
					fieldname: "rows",
					fieldtype: "Code",
					label: __("Rows"),
					reqd: 1,
				},
			],
			primary_action_label: __("Preview"),
			primary_action: async (values) => {
				const lines = (values.rows || "").split(/\n/).map((l) => l.trim()).filter(Boolean);
				const parsed = lines.map((l) => {
					const parts = l.split(/\t|,/).map((p) => p.trim());
					return { app_name: parts[0], amount: parseFloat(parts[1]) };
				});
				const r = await frappe.call({
					method: "saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry.paste_monthly_costs",
					args: { month: me.month, rows: parsed, commit: 0 },
				});
				const { matched, unmatched } = r.message || { matched: [], unmatched: [] };
				const html = `
					<div style="font-size:12px">
						<p><b>${matched.length}</b> matched, <b>${unmatched.length}</b> unmatched.</p>
						${matched.length ? `<details><summary>Matched (${matched.length})</summary><ul>${matched.map((m) => `<li>${frappe.utils.escape_html(m.input)} → ${frappe.utils.escape_html(m.app)} (${frappe.utils.escape_html(m.app_name)}) → ${m.amount}</li>`).join("")}</ul></details>` : ""}
						${unmatched.length ? `<details open><summary>Unmatched (${unmatched.length})</summary><ul>${unmatched.map((u) => `<li>${frappe.utils.escape_html(u.app_name)} → ${u.amount}</li>`).join("")}</ul></details>` : ""}
					</div>`;
				d.fields_dict.info.$wrapper.html(html);
				d.set_primary_action(__("Confirm & save {0}", [matched.length]), async () => {
					await frappe.call({
						method: "saas_register.saas_register.page.monthly_cost_entry.monthly_cost_entry.paste_monthly_costs",
						args: { month: me.month, rows: parsed, commit: 1 },
					});
					frappe.show_alert({ message: __("Saved"), indicator: "green" });
					d.hide();
					me.load();
				});
			},
		});
		d.show();
	}
}
