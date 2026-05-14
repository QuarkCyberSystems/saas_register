function applySubscriptionModelVisibility(frm) {
	const model = frm.doc.subscription_model || "Shared";

	// Renewal date: Shared owns one app-level renewal; Per-User keeps renewal on each access.
	frm.toggle_display("renewal_date", model !== "Per-User");
	frm.toggle_display("auto_renew", model !== "Per-User");

	// Seats: only Shared has a "Seats Paid" concept the user maintains manually.
	frm.toggle_display("seats_section", model === "Shared");
	frm.toggle_display("seats_paid", model === "Shared");
	frm.toggle_display("seats_active", model !== "Usage-Based");

	// Steady-state monthly_cost is meaningless for Usage-Based (cost varies every month).
	frm.toggle_display("monthly_cost", model !== "Usage-Based");
}

frappe.ui.form.on("SaaS Application", {
	refresh(frm) {
		applySubscriptionModelVisibility(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("View Access Records"),
				() => frappe.set_route("List", "SaaS Access", { saas_application: frm.doc.name }),
				__("Actions")
			);

			frm.add_custom_button(
				__("Recompute"),
				() => {
					// Re-runs seats_active + avg_monthly_cost server-side. Useful
					// after data migrations or when a hook didn't fire.
					frappe.call({
						method: "saas_register.saas_register.doctype.saas_application.saas_application.recompute",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Recomputing..."),
						callback: (r) => {
							if (!r.exc) {
								frappe.show_alert({
									message: __("Recomputed: seats_active={0}, avg_monthly_cost={1}", [
										r.message.seats_active,
										format_currency(r.message.avg_monthly_cost, frm.doc.currency),
									]),
									indicator: "green",
								});
								frm.reload_doc();
							}
						},
					});
				},
				__("Actions")
			);

			frm.add_custom_button(
				__("Raise Action"),
				() => {
					frappe.new_doc("SaaS Action", { saas_application: frm.doc.name });
				},
				__("Actions")
			);
		}

		if (frm.doc.seats_paid && frm.doc.seats_active != null && frm.doc.subscription_model === "Shared") {
			const u = frm.doc.seats_paid
				? Math.round((frm.doc.seats_active / frm.doc.seats_paid) * 100)
				: 0;
			frm.dashboard.add_indicator(
				__("Utilization: {0}%", [u]),
				u >= 75 ? "green" : u >= 50 ? "yellow" : "red"
			);
		}
	},

	subscription_model(frm) {
		applySubscriptionModelVisibility(frm);
	},
});
