frappe.listview_settings["SaaS Access"] = {
	add_fields: ["revoke_status"],
	get_indicator(doc) {
		const map = {
			Active: ["Active", "green"],
			"Pending Revoke": ["Pending Revoke", "yellow"],
			"In Progress": ["In Progress", "orange"],
			Revoked: ["Revoked", "red"],
		};
		const [label, color] = map[doc.revoke_status] || ["Active", "gray"];
		return [__(label), color, `revoke_status,=,${doc.revoke_status}`];
	},
};
