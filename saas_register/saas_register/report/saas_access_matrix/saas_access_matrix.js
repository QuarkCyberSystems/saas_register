frappe.query_reports["SaaS Access Matrix"] = {
	filters: [
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "employee_status",
			label: __("Employee Status"),
			fieldtype: "Select",
			options: "\nActive\nLeft\nInactive\nSuspended",
		},
		{
			fieldname: "include_revoked",
			label: __("Include Revoked Access"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "include_no_access",
			label: __("Show Employees with No Access"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		// Cells for SaaS Application columns are encoded as "marker|status|tier".
		if (typeof value === "string" && value.includes("|")) {
			const [marker, status, tier] = value.split("|");
			const colors = {
				Active: "#28A745",
				"Pending Revoke": "#FF9800",
				"In Progress": "#FF9800",
				Revoked: "#E53935",
			};
			const color = colors[status] || "#687178";
			const title = tier ? `${status} · ${tier}` : status;
			return `<span title="${title}" style="font-size:14px;font-weight:700;color:${color}">${marker}</span>`;
		}

		// Highlight Left employees in the Status column
		if (column.fieldname === "status" && value === "Left") {
			return `<span style="color:#E53935;font-weight:600">${value}</span>`;
		}

		return default_formatter(value, row, column, data);
	},
};
