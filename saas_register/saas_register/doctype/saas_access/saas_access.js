async function loadTierOptions(frm) {
	if (!frm.doc.saas_application) {
		frm.set_df_property("tier_name", "options", []);
		return;
	}
	const r = await frappe.call({
		method: "saas_register.saas_register.doctype.saas_application.saas_application.get_tiers",
		args: { saas_application: frm.doc.saas_application },
	});
	const tiers = r.message || [];
	frm.tier_options_map = Object.fromEntries(tiers.map((t) => [t.tier_name, t]));
	const labels = tiers.map((t) =>
		t.seats_paid
			? `${t.tier_name}  ·  ${t.seats_paid} seats  ·  ${format_currency(t.monthly_cost, t.currency)}/mo`
			: t.tier_name
	);
	frm.set_df_property("tier_name", "options", labels.length ? labels.join("\n") : []);
}

frappe.ui.form.on("SaaS Access", {
	refresh(frm) {
		loadTierOptions(frm);

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
		frm.set_value("tier_name", null);
		frm.set_value("monthly_cost_share", 0);
		loadTierOptions(frm);
	},

	tier_name(frm) {
		if (!frm.doc.tier_name || !frm.tier_options_map) return;
		// Strip the "  ·  N seats..." suffix back to the bare tier name on save:
		const bare = frm.doc.tier_name.split("  ·")[0].trim();
		if (bare !== frm.doc.tier_name) {
			frm.set_value("tier_name", bare);
			return;
		}
		const tier = frm.tier_options_map[bare];
		if (tier && tier.seats_paid) {
			const perSeat = tier.monthly_cost / tier.seats_paid;
			frm.set_value("monthly_cost_share", perSeat);
			if (!frm.doc.currency && tier.currency) frm.set_value("currency", tier.currency);
		}
	},
});
