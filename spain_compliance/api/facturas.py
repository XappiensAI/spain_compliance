# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Vista de detalle de facturas en /contabilidad, sin pasar por el Desk.

La SPA trabaja con el documento completo (cabecera, líneas, impuestos y plazos)
y delega en el servidor todo lo que el formulario de Desk hace en JavaScript:

- ``calcular`` rellena lo que falta (datos del cliente, del artículo, cuentas,
  almacén, impuestos de la plantilla) y recalcula totales **sin guardar**.
  El parámetro ``cambio`` dice qué campo acaba de tocar el usuario para vaciar
  antes lo que depende de él (p. ej. al cambiar de artículo se vuelven a traer
  precio, unidad y cuentas de la línea).
- ``guardar`` / ``validar`` / ``cancelar`` / ``eliminar`` usan el ciclo normal
  del DocType, con sus validaciones, permisos y control de concurrencia.

Permisos: los del DocType (``frappe.has_permission``). No hay reglas propias.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

# Lo que cambia entre facturas de venta y de compra.
TIPOS = {
	"Sales Invoice": {
		"tercero": "customer",
		"cuenta": "debit_to",
		"tarifa": "selling_price_list",
		"direccion": "customer_address",
		"envio": ("shipping_address_name", "shipping_address"),
		"extra": ("customer_group", "territory", "dispatch_address_name", "dispatch_address"),
		"limpiar_al_duplicar": ("hito_pedido",),
	},
	"Purchase Invoice": {
		"tercero": "supplier",
		"cuenta": "credit_to",
		"tarifa": "buying_price_list",
		"direccion": "supplier_address",
		"envio": ("shipping_address", "shipping_address_display"),
		"extra": ("supplier_group", "billing_address", "billing_address_display"),
		# El número de factura del proveedor no puede repetirse.
		"limpiar_al_duplicar": ("bill_no", "bill_date"),
	},
}
DOCTYPES = tuple(TIPOS)

# Tipos de campo que no son datos.
_SIN_DATOS = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Fold",
	"Heading",
	"Image",
}


def _dependientes(doctype: str) -> dict:
	"""Campos de la cabecera que dependen de otro: se vacían para que `set_missing_values` los vuelva a traer."""
	t = TIPOS[doctype]
	tercero = t["tercero"]
	envio_link, envio_texto = t["envio"]
	return {
		tercero: (
			f"{tercero}_name",
			t["cuenta"],
			"party_account_currency",
			t["direccion"],
			"address_display",
			"contact_person",
			"contact_display",
			"contact_email",
			"contact_mobile",
			envio_link,
			envio_texto,
			"tax_id",
			"tax_category",
			"payment_terms_template",
			"due_date",
			t["tarifa"],
			"price_list_currency",
			"plc_conversion_rate",
			"language",
			*t["extra"],
		),
		"company": (t["cuenta"], "company_address", "company_address_display", "cost_center", "taxes_and_charges"),
		"posting_date": ("due_date",),
		"bill_date": ("due_date",),
		t["direccion"]: ("address_display",),
		envio_link: (envio_texto,) if envio_link != envio_texto else (),
		"payment_terms_template": ("due_date",),
		t["tarifa"]: ("price_list_currency", "plc_conversion_rate"),
	}


# Campos de la línea que se conservan al cambiar de artículo.
_LINEA_CONSERVA = {"name", "idx", "doctype", "item_code", "qty", "__islocal"}

# Campos de la línea que se vuelven a calcular al cambiar la unidad.
_LINEA_UOM = ("conversion_factor", "price_list_rate", "base_price_list_rate", "rate", "base_rate")

_DOCSTATUS_LABEL = {0: "Borrador", 1: "Validada", 2: "Cancelada"}


# --- utilidades -------------------------------------------------------------


def _exigir_doctype(doctype: str) -> str:
	doctype = doctype or "Sales Invoice"
	if doctype not in DOCTYPES:
		frappe.throw(_("Tipo de documento no admitido: {0}").format(doctype))
	return doctype


def _doc_dict(doc) -> dict:
	data = doc.as_dict(convert_dates_to_str=True, no_nulls=False)
	data["__islocal"] = 1 if doc.is_new() else 0
	return data


def _limpiar_payload(data: dict) -> dict:
	"""Quita del documento que llega de la SPA lo que solo gestiona el servidor."""
	data = dict(data)
	for k in ("owner", "creation", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by", "_seen"):
		data.pop(k, None)
	nuevo = cint(data.get("__islocal")) or str(data.get("name") or "").startswith("new-")
	if nuevo:
		data.pop("name", None)
		data.pop("modified", None)
		data["docstatus"] = 0
	for campo, valor in list(data.items()):
		if not isinstance(valor, list):
			continue
		filas = []
		for fila in valor:
			if not isinstance(fila, dict):
				continue
			fila = dict(fila)
			for k in ("parent", "parenttype", "owner", "creation", "modified_by", "__temporary_name"):
				fila.pop(k, None)
			if nuevo or cint(fila.get("__islocal")) or str(fila.get("name") or "").startswith("new-"):
				fila.pop("name", None)
				fila.pop("modified", None)
			for k in [k for k in fila if k.startswith("__")]:
				fila.pop(k)
			filas.append(fila)
		data[campo] = filas
	data.pop("__unsaved", None)
	return data


def _en_memoria(doctype: str, data: dict):
	data = _limpiar_payload(data)
	data["doctype"] = doctype
	doc = frappe.get_doc(data)
	if not data.get("name"):
		doc.set("__islocal", 1)
	return doc


def _capturar_avisos(fn, *args, **kwargs) -> list[str]:
	"""Ejecuta `fn` y devuelve los msgprint que ha dejado, sin mandarlos al cliente como diálogos.

	Un error de validación no corta el cálculo: se devuelve como aviso y el resto sigue.
	"""
	log = frappe.local.message_log
	inicio = len(log)
	error = None
	try:
		fn(*args, **kwargs)
	except frappe.ValidationError as e:
		error = str(e)
	nuevos = _mensajes(log[inicio:])
	del log[inicio:]
	if error and not nuevos:
		nuevos = [frappe.utils.strip_html(error)]
	return nuevos


def _mensajes(entradas) -> list[str]:
	out = []
	for m in entradas:
		if isinstance(m, dict):
			texto = m.get("message")
		else:
			try:
				texto = frappe.parse_json(m).get("message")
			except Exception:
				texto = str(m)
		if texto and texto not in out:
			out.append(frappe.utils.strip_html(str(texto)))
	return out


def _aplicar_cambio(doc, cambio: dict | None) -> None:
	"""Vacía lo que depende del campo tocado para que se vuelva a traer."""
	if not cambio:
		return
	campo = cambio.get("campo")
	fila = cambio.get("fila")
	tabla = cambio.get("tabla") or "items"

	if fila:
		row = next(
			(r for r in doc.get(tabla) or [] if r.name == fila or str(r.idx) == str(fila)),
			None,
		)
		if not row or tabla != "items":
			return
		if campo == "item_code":
			for k in row.meta.get_valid_columns():
				if k not in _LINEA_CONSERVA:
					row.set(k, None)
			if not flt(row.qty):
				row.qty = -1 if doc.get("is_return") else 1
		elif campo == "uom":
			for k in _LINEA_UOM:
				row.set(k, None)
		elif campo == "item_tax_template":
			row.item_tax_rate = None
		elif campo in ("discount_percentage", "discount_amount", "price_list_rate", "margin_rate_or_amount"):
			# El precio neto se recalcula desde tarifa, margen y descuento (`calculate_item_rate`).
			if not flt(row.price_list_rate) and flt(row.rate) and campo != "price_list_rate":
				row.price_list_rate = row.rate
			if campo == "discount_amount":
				row.discount_percentage = 0
			row.rate = None
		return

	t = TIPOS[doc.doctype]
	for k in _dependientes(doc.doctype).get(campo, ()):
		if doc.meta.get_field(k):
			doc.set(k, None)

	if campo == t["tercero"]:
		# Las líneas con precio de tarifa toman el de la tarifa del nuevo tercero; las tecleadas se respetan.
		_reiniciar_precios(doc, solo_de_tarifa=True)
		# Con reglas de impuestos, la plantilla depende del tercero (país): se vuelve a elegir.
		# Unos impuestos puestos a mano, sin plantilla, se respetan.
		tipo_regla = "Purchase" if doc.doctype == "Purchase Invoice" else "Sales"
		if doc.get("taxes_and_charges") and frappe.db.exists(
			"Tax Rule", {"tax_type": tipo_regla, "company": doc.company}
		):
			doc.taxes_and_charges = None
			doc.set("taxes", [])
	elif campo == "company":
		doc.set("taxes", [])
		for row in doc.get("items") or []:
			for k in ("income_account", "expense_account", "cost_center", "warehouse", "item_tax_template", "item_tax_rate"):
				row.set(k, None)
	elif campo == "taxes_and_charges":
		doc.set("taxes", [])
		if doc.get("taxes_and_charges"):
			doc.append_taxes_from_master()
	elif campo == t["tarifa"]:
		_reiniciar_precios(doc, solo_de_tarifa=False)
	elif campo == "payment_terms_template":
		doc.set("payment_schedule", [])
	elif campo == "set_warehouse":
		for row in doc.get("items") or []:
			row.warehouse = doc.set_warehouse


def _reiniciar_precios(doc, solo_de_tarifa: bool) -> None:
	"""Vacía el precio de las líneas para que se vuelva a traer de la tarifa.

	Con `solo_de_tarifa` solo se tocan las líneas cuyo precio sale de la tarifa (y su
	descuento); un precio tecleado a mano se conserva. Si la nueva tarifa no tiene precio
	para el artículo, `_restaurar_precios` devuelve el anterior en lugar de dejarlo a cero.
	"""
	previos = {}
	for row in doc.get("items") or []:
		plr = flt(row.price_list_rate)
		# Precio que sale de la tarifa: tarifa (+ margen) − descuento, como `calculate_item_rate`.
		esperado = flt(row.rate_with_margin or plr) - flt(row.discount_amount)
		de_tarifa = bool(plr) and abs(flt(row.rate) - esperado) < 0.005
		if solo_de_tarifa and not de_tarifa:
			row.price_list_rate = None
			row.base_price_list_rate = None
			continue
		previos[row.idx] = row.rate
		for k in ("price_list_rate", "base_price_list_rate", "rate", "base_rate"):
			row.set(k, None)
	doc.flags.precios_previos = previos


def _restaurar_precios(doc) -> None:
	previos = doc.flags.pop("precios_previos", None) or {}
	for row in doc.get("items") or []:
		if row.idx in previos and not flt(row.price_list_rate) and not flt(row.rate):
			row.rate = previos[row.idx]


def _tarifa_activa(doc, avisos: list[str]) -> list[str]:
	"""Si la tarifa de la factura está desactivada, pone la activa por defecto.

	ERPNext no deja guardar con una tarifa desactivada, y la de los ajustes, la del cliente o la
	del pedido puede estarlo. Los precios ya puestos en las líneas no cambian.
	"""
	campo = TIPOS[doc.doctype]["tarifa"]
	actual = doc.get(campo)
	if not actual or frappe.get_cached_value("Price List", actual, "enabled"):
		return avisos
	venta = doc.doctype == "Sales Invoice"
	tipo = "selling" if venta else "buying"
	defecto = frappe.db.get_single_value(
		"Selling Settings" if venta else "Buying Settings",
		"selling_price_list" if venta else "buying_price_list",
	)
	# ERPNext también rechaza una tarifa limitada a otros países que el de la dirección del cliente.
	pais = (
		frappe.db.get_value("Address", doc.customer_address, "country")
		if venta and doc.get("customer_address")
		else None
	)

	def sirve(tarifa) -> bool:
		if not tarifa or not frappe.get_cached_value("Price List", tarifa, "enabled"):
			return False
		paises = frappe.get_all("Price List Country", filters={"parent": tarifa}, pluck="country")
		return not (pais and paises and pais not in paises)

	if not sirve(defecto):
		candidatas = frappe.get_all(
			"Price List", filters={tipo: 1, "enabled": 1}, pluck="name", order_by="creation asc"
		)
		defecto = next((c for c in candidatas if sirve(c)), None)
	if not defecto:
		return avisos
	doc.set(campo, defecto)
	_capturar_avisos(doc.set_price_list_currency, "Selling" if venta else "Buying")
	# Las líneas sin precio lo buscaron en la tarifa desactivada: se vuelve a buscar en la nueva.
	if doc.get("items"):
		_capturar_avisos(doc.set_missing_item_details)
	# El aviso de ERPNext sobre la tarifa desactivada ya no aplica.
	avisos = [a for a in avisos if actual not in a]
	avisos.append(_("La tarifa {0} está desactivada. La factura usa {1}.").format(actual, defecto))
	return avisos


def _plantilla_activa(doc, avisos: list[str]) -> list[str]:
	"""Una plantilla de impuestos desactivada no deja guardar.

	Solo llega así copiada de otro documento (pedido o factura duplicada): el buscador de la
	vista no ofrece plantillas desactivadas. Se quita el enlace y se conservan las filas de
	impuestos, que siguen siendo válidas.
	"""
	actual = doc.get("taxes_and_charges")
	if not actual:
		return avisos
	plantilla = doc.meta.get_field("taxes_and_charges").options
	if not frappe.get_cached_value(plantilla, actual, "disabled"):
		return avisos
	doc.taxes_and_charges = None
	avisos = list(avisos)
	avisos.append(
		_("La plantilla de impuestos {0} está desactivada. Se mantienen sus filas de impuestos sin plantilla.").format(actual)
	)
	return avisos


def _rellenar(doc, plantilla: bool = False) -> list[str]:
	"""Lo que haría el formulario de Desk: datos del tercero y de las líneas, impuestos y totales.

	Con `plantilla` (factura nueva, cambio de tercero o de compañía) se ponen los impuestos
	de la plantilla. Sin ella, si el usuario ha dejado la factura sin filas de impuestos se
	respeta: `set_missing_values` de ERPNext las volvería a añadir.
	"""
	avisos: list[str] = []
	sin_impuestos = not doc.get("taxes")

	if not doc.get("company"):
		doc.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)
	if not doc.get("posting_date"):
		doc.posting_date = nowdate()
	if not doc.get("currency") and doc.company:
		doc.currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	if not flt(doc.get("conversion_rate")):
		doc.conversion_rate = 1
	# Sin «fijar fecha» ERPNext pone la fecha de hoy al guardar: una fecha elegida la activa.
	if (
		doc.docstatus == 0
		and doc.meta.get_field("set_posting_time")
		and doc.get("posting_date")
		and getdate(doc.posting_date) != getdate(nowdate())
	):
		doc.set_posting_time = 1

	tercero = TIPOS[doc.doctype]["tercero"]
	if doc.get(tercero):
		avisos += _capturar_avisos(doc.run_method, "set_missing_values")
	elif doc.get("items"):
		if hasattr(doc, "set_price_list_and_item_details"):
			avisos += _capturar_avisos(doc.set_price_list_and_item_details)
		else:
			avisos += _capturar_avisos(doc.set_price_list_currency, "Buying")
			avisos += _capturar_avisos(doc.set_missing_item_details)
	avisos = _tarifa_activa(doc, avisos)
	_restaurar_precios(doc)
	# Muchos artículos no tienen descripción en el maestro; la línea toma su nombre, como en BC.
	for row in doc.get("items") or []:
		if row.get("item_code") and not (row.get("description") or "").strip():
			row.description = row.get("item_name") or row.item_code

	if not plantilla:
		if sin_impuestos:
			doc.set("taxes", [])
	elif not doc.get("taxes"):
		if doc.get("taxes_and_charges"):
			doc.append_taxes_from_master()
		elif doc.company:
			# Plantilla por defecto de la compañía, como el formulario de Desk al crear.
			avisos += _capturar_avisos(doc.set_taxes)
	if doc.get("items"):
		avisos += _capturar_avisos(doc.append_taxes_from_item_tax_template)

	try:
		from spain_compliance.contabilidad.registro_fiscal import aplica_registro_fiscal, copiar_clasificacion

		if aplica_registro_fiscal(doc.company):
			copiar_clasificacion(doc)
	except Exception:
		pass

	for row in doc.get("items") or []:
		if not flt(row.get("conversion_factor")):
			row.conversion_factor = 1
		if row.get("qty") is None:
			row.qty = 1

	_traer_fetch_from(doc)
	avisos += _capturar_avisos(doc.calculate_taxes_and_totals)
	if doc.get(tercero) and doc.get("due_date"):
		avisos += _capturar_avisos(doc.set_payment_schedule)
	return avisos


def _traer_fetch_from(doc) -> None:
	"""Rellena los campos «fetch_from» vacíos (NIF del cliente, grupo del artículo…) como hace Desk."""

	def rellenar(d):
		for df in d.meta.fields:
			origen = df.get("fetch_from")
			if not origen or "." not in origen or d.get(df.fieldname) not in (None, ""):
				continue
			enlace, campo = origen.split(".", 1)
			valor_enlace = d.get(enlace)
			link_df = d.meta.get_field(enlace)
			if not valor_enlace or not link_df or link_df.fieldtype != "Link":
				continue
			try:
				valor = frappe.db.get_value(link_df.options, valor_enlace, campo, cache=True)
			except Exception:
				continue
			if valor not in (None, ""):
				d.set(df.fieldname, valor)

	rellenar(doc)
	for row in doc.get("items") or []:
		rellenar(row)


def _permisos(doc) -> dict:
	nuevo = doc.is_new()
	dt = doc.doctype
	tiene = lambda p: bool(frappe.has_permission(dt, p, doc=None if nuevo else doc))  # noqa: E731
	return {
		"read": tiene("read"),
		"write": doc.docstatus == 0 and tiene("create" if nuevo else "write"),
		"write_on_submit": doc.docstatus == 1 and tiene("write"),
		"submit": doc.docstatus == 0 and not nuevo and tiene("submit"),
		"cancel": doc.docstatus == 1 and tiene("cancel"),
		"delete": doc.docstatus == 0 and not nuevo and tiene("delete"),
		"create": bool(frappe.has_permission(dt, "create")),
		"amend": doc.docstatus == 2 and tiene("amend"),
	}


def _contexto(doc) -> dict:
	"""Lo que no está en el documento pero ayuda a entenderlo: asientos, cobros, rectificativas, SII."""
	if doc.is_new():
		return {}
	out: dict = {"docstatus_label": _(_DOCSTATUS_LABEL.get(doc.docstatus, ""))}

	if doc.docstatus == 1:
		out["asientos"] = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
			fields=["account", "debit", "credit", "party", "cost_center", "project", "remarks"],
			order_by="debit desc, account",
		)
		out["cobros"] = frappe.get_all(
			"Payment Ledger Entry",
			filters={
				"against_voucher_type": doc.doctype,
				"against_voucher_no": doc.name,
				"voucher_no": ("!=", doc.name),
				"delinked": 0,
			},
			fields=["voucher_type", "voucher_no", "posting_date", "amount"],
			order_by="posting_date",
		)

	out["rectificativas"] = frappe.get_all(
		doc.doctype,
		filters={"return_against": doc.name, "docstatus": ("<", 2)},
		fields=["name", "posting_date", "grand_total", "docstatus", "status"],
		order_by="posting_date",
	)
	out["adjuntos"] = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		fields=["name", "file_name", "file_url", "is_private"],
		order_by="creation",
	)
	out["actividad"] = {
		"owner": doc.owner,
		"creation": str(doc.creation) if doc.creation else None,
		"modified_by": doc.modified_by,
		"modified": str(doc.modified) if doc.modified else None,
	}

	if doc.docstatus:
		try:
			from spain_compliance.api.sii import estado_documentos, puede_leer

			if puede_leer():
				res = estado_documentos(doc.doctype, [doc.name])
				out["sii"] = (res.get("estados") or {}).get(doc.name)
				out["sii_puede_enviar"] = res.get("puede_enviar")
		except Exception:
			pass
	return out


def _respuesta(doc, avisos: list[str] | None = None) -> dict:
	return {
		"doc": _doc_dict(doc),
		"permisos": _permisos(doc),
		"contexto": _contexto(doc),
		"avisos": avisos or [],
	}


# --- API --------------------------------------------------------------------


@frappe.whitelist()
def configuracion(doctype: str = "Sales Invoice") -> dict:
	"""Metadatos de los campos (etiquetas, opciones, solo lectura) y dimensiones contables."""
	doctype = _exigir_doctype(doctype)
	frappe.has_permission(doctype, "read", throw=True)

	meta = frappe.get_meta(doctype)
	tablas = {df.fieldname: df.options for df in meta.get_table_fields()}

	def campos(m) -> dict:
		out = {}
		for df in m.fields:
			if df.fieldtype in _SIN_DATOS:
				continue
			out[df.fieldname] = {
				"fieldname": df.fieldname,
				"label": _(df.label) if df.label else df.fieldname,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": cint(df.reqd),
				"read_only": cint(df.read_only),
				"hidden": cint(df.hidden),
				"allow_on_submit": cint(df.allow_on_submit),
				"is_custom": cint(df.get("is_custom_field")),
				"description": _(df.description) if df.description else None,
				"precision": df.precision,
				"idx": df.idx,
			}
		return out

	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)

		dimensiones = [
			{"fieldname": d.fieldname, "label": _(d.label), "document_type": d.document_type}
			for d in get_accounting_dimensions(as_list=False)
		]
	except Exception:
		dimensiones = []

	companias = frappe.get_all("Company", fields=["name", "abbr", "default_currency"], order_by="name")
	return {
		"doctype": doctype,
		"campos": campos(meta),
		"tablas": {campo: {"doctype": dt, "campos": campos(frappe.get_meta(dt))} for campo, dt in tablas.items()},
		"dimensiones": dimensiones,
		"companias": companias,
		"compania_defecto": frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company"),
		"impuestos_desde_articulo": cint(
			frappe.db.get_single_value("Accounts Settings", "add_taxes_from_item_tax_template")
		),
	}


@frappe.whitelist()
def obtener(name: str, doctype: str = "Sales Invoice") -> dict:
	doctype = _exigir_doctype(doctype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return _respuesta(doc)


@frappe.whitelist()
def nueva(
	doctype: str = "Sales Invoice",
	company: str | None = None,
	customer: str | None = None,
	supplier: str | None = None,
) -> dict:
	"""Factura nueva sin guardar, con los valores por defecto ya puestos."""
	doctype = _exigir_doctype(doctype)
	frappe.has_permission(doctype, "create", throw=True)
	doc = frappe.new_doc(doctype)
	if company:
		doc.company = company
	tercero = customer if doctype == "Sales Invoice" else supplier
	if tercero:
		doc.set(TIPOS[doctype]["tercero"], tercero)
	doc.posting_date = nowdate()
	avisos = _rellenar(doc, plantilla=True)
	return _respuesta(doc, avisos)


@frappe.whitelist()
def calcular(doc, cambio=None, doctype: str = "Sales Invoice") -> dict:
	"""Rellena y recalcula sin guardar. Devuelve el documento completo."""
	doctype = _exigir_doctype(doctype)
	data = frappe.parse_json(doc) or {}
	cambios = frappe.parse_json(cambio) if cambio else []
	if isinstance(cambios, dict):
		cambios = [cambios]

	nuevo = cint(data.get("__islocal")) or not data.get("name")
	if nuevo:
		frappe.has_permission(doctype, "create", throw=True)
	else:
		frappe.has_permission(doctype, "write", doc=data.get("name"), throw=True)

	d = _en_memoria(doctype, data)
	if d.docstatus != 0:
		frappe.throw(_("Solo se recalculan facturas en borrador."))

	for c in cambios:
		_aplicar_cambio(d, c)
	campos = {c.get("campo") for c in cambios if not c.get("fila")}
	avisos = _rellenar(d, plantilla=bool(campos & {TIPOS[doctype]["tercero"], "company"}))
	out = _doc_dict(d)
	if not nuevo:
		# `get_doc(dict)` no carga del disco: se conserva el nombre y la marca de tiempo del cliente.
		out["__islocal"] = 0
		out["name"] = data.get("name")
		out["modified"] = data.get("modified")
	return {"doc": out, "avisos": avisos}


@frappe.whitelist(methods=["POST"])
def guardar(doc, doctype: str = "Sales Invoice") -> dict:
	"""Crea o actualiza. En una factura validada solo cambian los campos «permitir al validar»."""
	doctype = _exigir_doctype(doctype)
	data = _limpiar_payload(frappe.parse_json(doc) or {})

	if data.get("name") and frappe.db.exists(doctype, data["name"]):
		d = frappe.get_doc(doctype, data["name"])
		if d.docstatus == 0:
			d.check_permission("write")
			data.pop("docstatus", None)
			d.update(data)
		elif d.docstatus == 1:
			d.check_permission("write")
			if data.get("modified") and str(data["modified"]) != str(d.modified):
				frappe.throw(
					_("La factura ha cambiado desde que la abrió. Recárguela antes de guardar."),
					frappe.TimestampMismatchError,
				)
			for df in d.meta.fields:
				if df.allow_on_submit and df.fieldtype not in _SIN_DATOS and df.fieldname in data:
					if df.fieldtype in ("Table", "Table MultiSelect"):
						continue
					d.set(df.fieldname, data[df.fieldname])
		else:
			frappe.throw(_("Una factura cancelada no se puede modificar."))
		d.save()
	else:
		data["doctype"] = doctype
		d = frappe.get_doc(data)
		d.insert()
	return _respuesta(d)


@frappe.whitelist(methods=["POST"])
def validar(name: str, doctype: str = "Sales Invoice") -> dict:
	doctype = _exigir_doctype(doctype)
	d = frappe.get_doc(doctype, name)
	d.check_permission("submit")
	d.submit()
	return _respuesta(d)


@frappe.whitelist(methods=["POST"])
def cancelar(name: str, doctype: str = "Sales Invoice") -> dict:
	doctype = _exigir_doctype(doctype)
	d = frappe.get_doc(doctype, name)
	d.check_permission("cancel")
	d.cancel()
	return _respuesta(d)


@frappe.whitelist(methods=["POST"])
def eliminar(name: str, doctype: str = "Sales Invoice") -> dict:
	doctype = _exigir_doctype(doctype)
	frappe.delete_doc(doctype, name)
	return {"ok": True}


@frappe.whitelist()
def duplicar(name: str, doctype: str = "Sales Invoice") -> dict:
	"""Copia sin guardar, con fecha de hoy y vencimiento recalculado."""
	doctype = _exigir_doctype(doctype)
	origen = frappe.get_doc(doctype, name)
	origen.check_permission("read")
	frappe.has_permission(doctype, "create", throw=True)
	d = frappe.copy_doc(origen)
	d.posting_date = nowdate()
	d.due_date = None
	d.set("payment_schedule", [])
	for campo in ("return_against", "amended_from", *TIPOS[doctype]["limpiar_al_duplicar"]):
		if d.meta.get_field(campo):
			d.set(campo, None)
	avisos = _plantilla_activa(d, _rellenar(d))
	return _respuesta(d, avisos)


@frappe.whitelist()
def rectificar(name: str, doctype: str = "Sales Invoice") -> dict:
	"""Rectificativa (abono) sin guardar a partir de una factura validada."""
	doctype = _exigir_doctype(doctype)
	frappe.has_permission(doctype, "create", throw=True)
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	d = make_return_doc(doctype, name)
	return _respuesta(d)


@frappe.whitelist(methods=["POST"])
def modificar(name: str, doctype: str = "Sales Invoice") -> dict:
	"""Copia de una factura cancelada con `amended_from`, sin guardar (equivale a «Modificar» del Desk)."""
	doctype = _exigir_doctype(doctype)
	origen = frappe.get_doc(doctype, name)
	if origen.docstatus != 2:
		frappe.throw(_("Solo se modifican facturas canceladas."))
	frappe.has_permission(doctype, "amend", doc=origen, throw=True)
	d = frappe.copy_doc(origen)
	d.amended_from = origen.name
	return _respuesta(d)
