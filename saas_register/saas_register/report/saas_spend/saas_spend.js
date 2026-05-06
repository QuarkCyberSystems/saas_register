frappe.query_reports["SaaS Spend"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 0,
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
		{
			fieldname: "vendor",
			label: __("Vendor"),
			fieldtype: "Link",
			options: "Supplier",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "utilization" && data) {
			const u = parseFloat(value || 0);
			let color = "red";
			if (u >= 75) color = "green";
			else if (u >= 50) color = "orange";
			value = `<span style="color:${color}">${u.toFixed(0)}%</span>`;
			return value;
		}
		if (column.fieldname === "days_to_renewal" && data) {
			const d = parseInt(value);
			if (!isNaN(d) && d <= 60 && d >= 0) {
				return `<span style="color:#E53935;font-weight:600">${d}</span>`;
			}
		}
		return default_formatter(value, row, column, data);
	},
};
