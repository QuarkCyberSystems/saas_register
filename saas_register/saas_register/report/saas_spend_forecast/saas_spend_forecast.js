frappe.query_reports["SaaS Spend Forecast"] = {
	filters: [
		{
			fieldname: "start_month",
			label: __("Start Month"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nActive\nReview\nKill-Replace",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		// Highlight zero-cost months for Kill-Replace apps in red
		if (
			data &&
			data.status === "Kill-Replace" &&
			column.fieldname &&
			column.fieldname.startsWith("m_") &&
			(!value || parseFloat(value) === 0)
		) {
			return `<span style="color:#E53935">${default_formatter(value, row, column, data)}</span>`;
		}
		return default_formatter(value, row, column, data);
	},
};
