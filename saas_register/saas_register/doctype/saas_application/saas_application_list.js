frappe.listview_settings["SaaS Application"] = {
	add_fields: ["status", "sso_status", "vault_status", "renewal_date", "seats_paid", "seats_active"],

	get_indicator(doc) {
		const map = {
			Active: ["Active", "green"],
			Review: ["Review", "yellow"],
			"Kill-Replace": ["Kill / Replace", "red"],
		};
		const [label, color] = map[doc.status] || ["Active", "gray"];
		return [__(label), color, `status,=,${doc.status}`];
	},

	formatters: {
		sso_status(value) {
			if (!value || value === "Not Applicable") {
				return `<span class="text-muted">—</span>`;
			}
			if (value === "No") {
				return `<span style="color:var(--red-500);font-weight:600">✗</span>`;
			}
			return `<span style="color:var(--green-600);font-weight:600">✓</span>`;
		},
		vault_status(value) {
			if (!value || value === "Not Applicable") {
				return `<span class="text-muted">—</span>`;
			}
			if (value === "No") {
				return `<span style="color:var(--red-500);font-weight:600">✗</span>`;
			}
			return `<span style="color:var(--green-600);font-weight:600">✓</span>`;
		},
		renewal_date(value) {
			if (!value) return "";
			const days = frappe.datetime.get_day_diff(value, frappe.datetime.get_today());
			const formatted = frappe.datetime.global_date_format(value);
			if (days < 0) {
				return `${formatted} <span style="color:var(--red-500);font-weight:600">(overdue)</span>`;
			}
			if (days <= 60) {
				return `${formatted} <span style="color:var(--orange-600);font-weight:600">(${days}d)</span>`;
			}
			return formatted;
		},
	},

	onload(listview) {
		listview.page.add_inner_button(__("Renews < 60 days"), () => {
			const horizon = frappe.datetime.add_days(frappe.datetime.get_today(), 60);
			listview.filter_area.clear();
			listview.filter_area.add([
				["SaaS Application", "renewal_date", "<=", horizon],
				["SaaS Application", "renewal_date", ">=", frappe.datetime.get_today()],
			]);
		});

		listview.page.add_inner_button(__("Underutilized"), () => {
			frappe.set_route("query-report", "SaaS Spend");
		});
	},
};
