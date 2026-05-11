app_name = "saas_register"
app_title = "Saas Register"
app_publisher = "QCS"
app_description = "Small app to track all the Saas accounts"
app_email = "info@quarkcs.com"
app_license = "mit"


# ---------------------------------------------------------------------------
# Required apps
# ---------------------------------------------------------------------------

required_apps = ["erpnext", "hrms"]


# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------

doc_events = {
	"Employee": {
		"on_update": "saas_register.saas_register.employee_hooks.on_employee_update",
		"after_insert": "saas_register.saas_register.employee_hooks.on_employee_update",
	},
}


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

scheduler_events = {
	"daily": [
		"saas_register.saas_register.application_hooks.check_expiring_apps",
		"saas_register.saas_register.application_hooks.emit_renewal_webhooks",
	],
}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

permission_query_conditions = {
	"SaaS Access": "saas_register.saas_register.permissions.saas_access_query",
}

has_permission = {
	"SaaS Access": "saas_register.saas_register.permissions.saas_access_has_permission",
}


# ---------------------------------------------------------------------------
# Fixtures (auto-imported on install/migrate from saas_register/fixtures/*.json)
# ---------------------------------------------------------------------------

fixtures = [
	{"dt": "Role", "filters": [["role_name", "in", ["IT Manager", "Finance Manager"]]]},
	"SaaS Category",
	{"dt": "Custom Field", "filters": [["name", "in", ["Purchase Invoice-saas_application"]]]},
]

# Webhooks are NOT shipped as fixtures because the Webhook doctype validates
# request_url with urlparse at save time, and our Jinja-templated URL
# ({{ ...get_single_value('SaaS Register Settings', 'n8n_webhook_base_url') }})
# trips that validation. The 4 webhook events from v3 §3.5 are documented in
# README.md — admins create them once `n8n_webhook_base_url` is set in Settings.
# Renewal-at-30/14/7-days uses `application_hooks.emit_renewal_webhooks` and
# POSTs directly (no Webhook record needed).


# ---------------------------------------------------------------------------
# Connections shown on standard doctypes (Employee → SaaS Access)
# ---------------------------------------------------------------------------

override_doctype_dashboards = {
	"Employee": "saas_register.saas_register.employee_dashboard.extend_employee_dashboard",
}

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "saas_register",
# 		"logo": "/assets/saas_register/logo.png",
# 		"title": "Saas Register",
# 		"route": "/saas_register",
# 		"has_permission": "saas_register.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/saas_register/css/saas_register.css"
# app_include_js = "/assets/saas_register/js/saas_register.js"

# include js, css files in header of web template
# web_include_css = "/assets/saas_register/css/saas_register.css"
# web_include_js = "/assets/saas_register/js/saas_register.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "saas_register/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "saas_register/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "saas_register.utils.jinja_methods",
# 	"filters": "saas_register.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "saas_register.install.before_install"
after_install = "saas_register.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "saas_register.uninstall.before_uninstall"
# after_uninstall = "saas_register.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "saas_register.utils.before_app_install"
# after_app_install = "saas_register.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "saas_register.utils.before_app_uninstall"
# after_app_uninstall = "saas_register.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "saas_register.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "saas_register.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"saas_register.tasks.all"
# 	],
# 	"daily": [
# 		"saas_register.tasks.daily"
# 	],
# 	"hourly": [
# 		"saas_register.tasks.hourly"
# 	],
# 	"weekly": [
# 		"saas_register.tasks.weekly"
# 	],
# 	"monthly": [
# 		"saas_register.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "saas_register.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "saas_register.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "saas_register.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "saas_register.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["saas_register.utils.before_request"]
# after_request = ["saas_register.utils.after_request"]

# Job Events
# ----------
# before_job = ["saas_register.utils.before_job"]
# after_job = ["saas_register.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"saas_register.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

