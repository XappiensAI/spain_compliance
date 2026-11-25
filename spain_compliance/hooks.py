app_name = "spain_compliance"
app_title = "Spain Compliance"
app_publisher = "Xappiens"
app_description = (
	"Contabilidad española para ERPNext: Plan General Contable, correlatividad de "
	"facturas, series de facturas rectificativas, estados de cobro "
	"(dudoso cobro / pérdida), registro fiscal de IVA e interfaz de contabilidad."
)
app_email = "hello@xappiens.com"
app_license = "mit"
app_icon_url = "/assets/spain_compliance/images/logo.svg"
app_icon_title = "Contabilidad"
app_icon_route = "/contabilidad"

required_apps = ["frappe/erpnext"]

# Apps screen -----------------------------------------------------------------

add_to_apps_screen = [
	{
		"name": "spain_compliance",
		"logo": "/assets/spain_compliance/images/logo.svg",
		"title": "Contabilidad",
		"route": "/contabilidad",
		"has_permission": "spain_compliance.api.permission.has_app_permission",
	}
]

website_route_rules = [
	{"from_route": "/contabilidad/<path:app_path>", "to_route": "contabilidad"},
]

# Install / migrate -------------------------------------------------------------
# Custom Fields (Company, Sales Invoice) + "Dudoso Cobro" / "Pérdida" in Sales Invoice.status

after_install = "spain_compliance.install.after_install"
after_migrate = "spain_compliance.install.after_migrate"
before_uninstall = "spain_compliance.install.before_uninstall"

# DocType extensions ------------------------------------------------------------
# Prefer extend_doctype_class (Frappe v16+) over override_doctype_class so other
# apps can extend the same DocTypes. On Frappe v15 the framework ignores this
# hook; monkey_patches.aplicar_doctype_extensions() patches the same methods.

extend_doctype_class = {
	# Preserve Dudoso Cobro / Pérdida across ERPNext status recalculation
	"Sales Invoice": "spain_compliance.overrides.sales_invoice.SalesInvoiceMixin",
	# PGC: each account keeps its own root_type inside the 9-group tree
	"Account": "spain_compliance.overrides.account.AccountMixin",
}

doc_events = {
	# PGC: cuenta auxiliar 430xxxxx / 400xxxxx por tercero (opción en Company)
	"Company": {"validate": "spain_compliance.contabilidad.cuentas_tercero.validate_company"},
	"Customer": {
		"after_insert": "spain_compliance.contabilidad.cuentas_tercero.on_party_insert",
		"validate": "spain_compliance.contabilidad.identificacion.validate_party",
	},
	"Supplier": {
		"after_insert": "spain_compliance.contabilidad.cuentas_tercero.on_party_insert",
		"validate": "spain_compliance.contabilidad.identificacion.validate_party",
	},
	"Sales Invoice": {
		"before_naming": "spain_compliance.overrides.sales_invoice.on_before_naming",
		"before_validate": "spain_compliance.contabilidad.cuentas_tercero.on_invoice_before_validate",
		"validate": [
			"spain_compliance.contabilidad.series.on_validate",
			"spain_compliance.contabilidad.registro_fiscal.validar_factura",
			"spain_compliance.overrides.sales_invoice.on_validate_correlatividad",
			"spain_compliance.api.hitos.validar_hito_unico",
			"spain_compliance.api.hitos.validar_total_pedido",
		],
		"before_submit": "spain_compliance.contabilidad.registro_fiscal.before_submit",
		# SII: registro pendiente al validar, baja pendiente al cancelar
		"on_submit": [
			"spain_compliance.contabilidad.sii.registro.on_submit",
			"spain_compliance.api.hitos.actualizar_pedidos",
		],
		"on_cancel": [
			"spain_compliance.contabilidad.sii.registro.on_cancel",
			"spain_compliance.api.hitos.actualizar_pedidos",
		],
	},
	"Purchase Invoice": {
		"before_naming": "spain_compliance.contabilidad.series.on_before_naming",
		"before_validate": "spain_compliance.contabilidad.cuentas_tercero.on_invoice_before_validate",
		"validate": [
			"spain_compliance.contabilidad.series.on_validate",
			"spain_compliance.contabilidad.registro_fiscal.validar_factura",
		],
		"before_submit": "spain_compliance.contabilidad.registro_fiscal.before_submit",
		"on_submit": "spain_compliance.contabilidad.sii.registro.on_submit",
		"on_cancel": "spain_compliance.contabilidad.sii.registro.on_cancel",
	},
}

doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Company": "public/js/company.js",
}

# Scheduler -------------------------------------------------------------------------

scheduler_events = {
	"cron": {
		# SII: envío de pendientes en las compañías con envío automático
		"*/15 * * * *": ["spain_compliance.contabilidad.sii.registro.tarea_envio_automatico"],
	},
	"daily": [
		# Overdue invoices → "Dudoso Cobro" after Company.meses_dudoso_cobro months
		"spain_compliance.tasks.auto_mark_dudoso_cobro",
		# Certificado Digital: estado y avisos de caducidad (60/30/15/7/1/0 días)
		"spain_compliance.contabilidad.certificados.revisar_caducidad",
	],
}
