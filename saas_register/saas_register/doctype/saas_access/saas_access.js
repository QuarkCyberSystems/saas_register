frappe.ui.form.on("SaaS Access", {
	setup(frm) {
		// Constrain the Tier dropdown to tiers belonging to the selected app.
		frm.set_query("tier", () => ({
			filters: { saas_application: frm.doc.saas_application || "" },
		}));
	},

	refresh(frm) {
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
		// When the app changes, the previously-picked tier is almost certainly
		// wrong — clear it.
		frm.set_value("tier", null);
		frm.set_value("monthly_cost_share", 0);
	},

	tier(frm) {
		// On tier pick, fetch its per-seat cost and prefill monthly_cost_share.
		if (!frm.doc.tier) {
			frm.set_value("monthly_cost_share", 0);
			return;
		}
		frappe.db
			.get_value("SaaS Application Tier", frm.doc.tier, [
				"seats_paid",
				"monthly_cost",
				"currency",
			])
			.then((r) => {
				const t = (r && r.message) || {};
				if (t.seats_paid && t.monthly_cost) {
					frm.set_value("monthly_cost_share", t.monthly_cost / t.seats_paid);
				}
				if (!frm.doc.currency && t.currency) {
					frm.set_value("currency", t.currency);
				}
			});
	},
});
