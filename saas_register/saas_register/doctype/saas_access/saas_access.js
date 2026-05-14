function applyPerUserVisibility(frm) {
	const isPerUser = frm.doc.subscription_model === "Per-User";
	frm.toggle_display("per_user_section", isPerUser);
	frm.toggle_display("per_user_renewal_date", isPerUser);
	frm.toggle_display("per_user_billing_cycle", isPerUser);
	frm.toggle_reqd("per_user_renewal_date", isPerUser);
	frm.toggle_reqd("monthly_cost_share", isPerUser);
}

frappe.ui.form.on("SaaS Access", {
	setup(frm) {
		// Filter the Tier picker to tiers belonging to this app and still active.
		frm.set_query("tier_or_plan", () => ({
			filters: {
				saas_application: frm.doc.saas_application || "",
				is_active: 1,
			},
		}));
	},

	refresh(frm) {
		applyPerUserVisibility(frm);

		if (frm.is_new()) return;

		if (frm.doc.revoke_status !== "Revoked") {
			frm.add_custom_button(__("Revoke Now"), () => {
				frappe.prompt(
					[
						{
							fieldname: "reason",
							label: __("Reason (optional)"),
							fieldtype: "Small Text",
						},
					],
					(values) => {
						frappe.confirm(
							__("Revoke {0}'s access to {1}? This sets status to Revoked.", [
								frm.doc.employee_name || frm.doc.employee,
								frm.doc.app_name || frm.doc.saas_application,
							]),
							() => {
								frappe.call({
									method: "saas_register.saas_register.doctype.saas_access.saas_access.revoke_now",
									args: { name: frm.doc.name, reason: values.reason },
									freeze: true,
									freeze_message: __("Revoking access..."),
									callback: () => {
										frappe.show_alert({ message: __("Access revoked"), indicator: "green" });
										frm.reload_doc();
									},
								});
							}
						);
					},
					__("Revoke Access"),
					__("Revoke")
				);
			}).addClass("btn-danger");
		}

		if (frm.doc.saas_application) {
			frm.add_custom_button(__("Open Application"), () => {
				frappe.set_route("Form", "SaaS Application", frm.doc.saas_application);
			});
		}
	},

	saas_application(frm) {
		// Clear the tier when the app changes — old tier won't belong to the new app.
		frm.set_value("tier_or_plan", null);
		applyPerUserVisibility(frm);
	},

	subscription_model(frm) {
		applyPerUserVisibility(frm);
	},
});
