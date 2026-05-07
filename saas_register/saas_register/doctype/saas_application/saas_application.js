function rollupTiers(frm) {
	const tiers = frm.doc.tiers || [];
	let seats = 0;
	let cost = 0;
	const labels = [];
	for (const t of tiers) {
		seats += parseInt(t.seats_paid || 0);
		cost += parseFloat(t.monthly_cost || 0);
		const lbl = (t.tier_name || "").trim() || __("Tier");
		labels.push(t.seats_paid ? `${lbl} ${t.seats_paid}` : lbl);
	}
	frm.set_value("seats_paid", seats);
	frm.set_value("monthly_cost", cost);
	frm.set_value("annual_cost", cost * 12);
	frm.set_value("plan_summary", labels.join(" / "));
}

frappe.ui.form.on("SaaS Application", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("View Access Records"),
				() => frappe.set_route("List", "SaaS Access", { saas_application: frm.doc.name }),
				__("Actions")
			);

			frm.add_custom_button(
				__("Recompute Seats Active"),
				() => {
					frappe.call({
						method: "frappe.client.get_count",
						args: {
							doctype: "SaaS Access",
							filters: { saas_application: frm.doc.name, revoke_status: "Active" },
						},
						callback: (r) => {
							frm.set_value("seats_active", r.message || 0);
							frm.save();
						},
					});
				},
				__("Actions")
			);
		}

		if (frm.doc.seats_paid && frm.doc.seats_active != null) {
			const u = frm.doc.seats_paid
				? Math.round((frm.doc.seats_active / frm.doc.seats_paid) * 100)
				: 0;
			frm.dashboard.add_indicator(
				__("Utilization: {0}%", [u]),
				u >= 75 ? "green" : u >= 50 ? "yellow" : "red"
			);
		}
	},

	tiers_add: rollupTiers,
	tiers_remove: rollupTiers,
});

frappe.ui.form.on("SaaS Application Tier", {
	tier_name: rollupTiers,
	seats_paid: rollupTiers,
	monthly_cost: rollupTiers,
});
