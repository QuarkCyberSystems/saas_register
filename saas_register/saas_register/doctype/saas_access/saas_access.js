function applyPerUserVisibility(frm) {
	const isPerUser = frm.doc.subscription_model === "Per-User";
	frm.toggle_display("per_user_section", isPerUser);
	frm.toggle_display("per_user_renewal_date", isPerUser);
	frm.toggle_display("per_user_billing_cycle", isPerUser);
	frm.toggle_reqd("per_user_renewal_date", isPerUser);
	frm.toggle_reqd("monthly_cost_share", isPerUser);
}

async function refreshTierAutosuggest(frm) {
	if (!frm.doc.saas_application) {
		frm.fields_dict.tier_or_plan.df.options = "";
		frm.refresh_field("tier_or_plan");
		return;
	}
	const r = await frappe.call({
		method: "saas_register.saas_register.doctype.saas_access.saas_access.autocomplete_tier_or_plan",
		args: { saas_application: frm.doc.saas_application },
	});
	// tier_or_plan is a Data field — we use awesomplete-style helper for suggestions
	const suggestions = r.message || [];
	if (frm.tier_autocomplete) {
		frm.tier_autocomplete.list = suggestions;
		return;
	}
	const input = frm.fields_dict.tier_or_plan?.$input?.get(0);
	if (input && window.Awesomplete) {
		frm.tier_autocomplete = new Awesomplete(input, { list: suggestions, minChars: 0, autoFirst: true });
	}
}

frappe.ui.form.on("SaaS Access", {
	refresh(frm) {
		applyPerUserVisibility(frm);
		refreshTierAutosuggest(frm);

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
		// Reset tier suggestions and clear per-user-derived state when app changes.
		frm.set_value("tier_or_plan", null);
		refreshTierAutosuggest(frm);
		applyPerUserVisibility(frm);
	},

	subscription_model(frm) {
		applyPerUserVisibility(frm);
	},
});
