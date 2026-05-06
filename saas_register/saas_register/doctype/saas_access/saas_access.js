frappe.ui.form.on("SaaS Access", {
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
});
