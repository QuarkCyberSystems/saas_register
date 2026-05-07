frappe.ui.form.on("SaaS Application", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Add Tier"),
				() => {
					frappe.new_doc("SaaS Application Tier", { saas_application: frm.doc.name });
				},
				__("Actions")
			);

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
});
