# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Hitos de facturación: el calendario de pagos de las órdenes de venta.

Cada fila de la tabla Payment Schedule de una orden de venta validada es un hito.
Si el sitio tiene el seguimiento de proyectos (``SRG Hito Facturacion``), se añade
el estado y la nota que marca el jefe de proyecto.

Lo facturado se sabe por las líneas de factura ligadas a la orden. La factura creada
desde un hito guarda la fila en ``hito_pedido``. Las ligadas sin esa marca se asignan
a los hitos por orden, saltando los que el seguimiento ya da por facturados.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, nowdate

from spain_compliance.api.facturas import _rellenar, _respuesta

SEGUIMIENTO = "SRG Hito Facturacion"
# Margen para dar un hito por cubierto (puntos porcentuales del pedido).
TOLERANCIA = 0.5


def _etiqueta(fila, total: int) -> str:
	descripcion = (fila.get("description") or "").strip()
	if descripcion:
		return descripcion
	if (fila.get("payment_term") or "").strip():
		return fila.payment_term.strip()
	return _("Facturación del pedido") if total <= 1 else _("Hito {0}").format(int(fila.idx or 0))


def _seguimiento(pedidos: list[str]) -> dict:
	if not pedidos or not frappe.db.exists("DocType", SEGUIMIENTO):
		return {}
	filas = frappe.get_all(
		SEGUIMIENTO,
		filters={"sales_order": ["in", pedidos], "payment_schedule_row": ["is", "set"]},
		fields=["payment_schedule_row", "billing_status", "progress_percent", "progress_note"],
		ignore_permissions=True,
	)
	return {f.payment_schedule_row: f for f in filas}


def _facturas(pedidos: list[str]) -> dict[str, list[dict]]:
	"""Facturas en borrador o validadas con líneas de cada pedido.

	Una rectificativa hereda el hito de la factura que rectifica (``hito_pedido`` no se copia).
	"""
	if not pedidos:
		return {}
	tiene_hito = frappe.get_meta("Sales Invoice").has_field("hito_pedido")
	hito = "COALESCE(NULLIF(si.hito_pedido, ''), orig.hito_pedido)" if tiene_hito else "NULL"
	filas = frappe.db.sql(
		f"""
		SELECT si.name, si.docstatus, si.posting_date, si.is_return, si.return_against,
			{hito} AS hito_pedido, sii.sales_order, SUM(sii.amount) AS importe
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		LEFT JOIN `tabSales Invoice` orig ON orig.name = si.return_against
		WHERE sii.sales_order IN %(pedidos)s AND si.docstatus < 2
		GROUP BY si.name, sii.sales_order
		ORDER BY si.is_return, si.docstatus DESC, si.posting_date, si.creation
		""",
		{"pedidos": tuple(pedidos)},
		as_dict=True,
	)
	por_pedido: dict[str, list[dict]] = {}
	for f in filas:
		por_pedido.setdefault(f.sales_order, []).append(f)
	return por_pedido


def _factura(f, parte: float, importe: float) -> dict:
	return {
		"name": f.name,
		"docstatus": f.docstatus,
		"posting_date": str(f.posting_date) if f.posting_date else None,
		"importe": flt(importe, 2),
		"parte": parte,
		"rectifica": f.return_against if f.get("is_return") else None,
	}


def _validado(h) -> float:
	return sum(x["parte"] for x in h["facturas"] if x["docstatus"] == 1)


def _libre(h) -> bool:
	"""Ni marcado a mano, ni cubierto por facturas validadas, ni con un borrador."""
	return (
		not h["marcado_facturado"]
		and _validado(h) < h["porcentaje"] - TOLERANCIA
		and not any(x["docstatus"] == 0 and x["parte"] > 0 for x in h["facturas"])
	)


def _con_factura(hitos: list[dict], nombre: str | None) -> dict | None:
	return next((h for h in hitos if any(x["name"] == nombre for x in h["facturas"])), None)


def _asignar(hitos: list[dict], facturas: list[dict], total_lineas: float) -> None:
	"""Reparte las facturas del pedido entre sus hitos (ver docstring del módulo).

	La parte de cada factura es la suma de sus líneas entre la suma de las líneas del pedido,
	las dos antes del descuento sobre el total.
	"""
	por_fila = {h["fila"]: h for h in hitos}
	for f in facturas:  # primero las facturas, luego las rectificativas
		parte = flt(f.importe) / total_lineas * 100 if total_lineas else 0
		factura = _factura(f, parte, f.importe)
		destino = por_fila.get(f.hito_pedido)
		if not destino and f.is_return:
			destino = _con_factura(hitos, f.return_against)
		if not destino and not f.is_return:
			destino = next((h for h in hitos if _libre(h)), None) or hitos[-1]
		if destino:
			destino["facturas"].append(factura)


def _por_proyecto(hitos: list[dict]) -> None:
	"""Facturas del proyecto sin líneas del pedido (hechas a mano o desde BC).

	Cuentan para el hito del mismo proyecto cuya base coincide con la de la factura. Así no
	se confunde un hito con una factura de portes o de extras. Los hitos marcados como
	facturados en el seguimiento se quedan primero con su factura, para que no la tome otro
	hito con la misma base (repartos 50/50, 30/30/40…).
	"""
	por_proyecto: dict[str, list[dict]] = {}
	for h in hitos:
		if h["proyecto"]:
			por_proyecto.setdefault(h["proyecto"], []).append(h)
	proyectos = [p for p, lista in por_proyecto.items() if any(_libre(h) for h in lista)]
	if not proyectos:
		return
	facturas = frappe.db.sql(
		"""
		SELECT si.name, si.docstatus, si.posting_date, si.project, si.net_total,
			si.is_return, si.return_against
		FROM `tabSales Invoice` si
		WHERE si.project IN %(proyectos)s AND si.docstatus < 2
			AND NOT EXISTS (
				SELECT 1 FROM `tabSales Invoice Item` sii
				WHERE sii.parent = si.name AND IFNULL(sii.sales_order, '') != ''
			)
		ORDER BY si.is_return, si.docstatus DESC, si.posting_date, si.creation
		""",
		{"proyectos": tuple(proyectos)},
		as_dict=True,
	)
	for lista in por_proyecto.values():
		lista.sort(key=lambda h: (h["fecha"] or "9999", h["pedido"], h["numero"]))

	def coincide(h, neto) -> bool:
		return abs(h["base"] - neto) <= max(1.0, abs(h["base"]) * 0.002)

	for f in facturas:
		neto = flt(f.net_total, 2)
		lista = por_proyecto.get(f.project) or []
		if f.is_return:
			destino = _con_factura(lista, f.return_against)
			if destino and destino["base"]:
				destino["facturas"].append(_factura(f, neto / destino["base"] * destino["porcentaje"], neto))
			continue
		destino = next(
			(h for h in lista if h["marcado_facturado"] and not h["facturas"] and coincide(h, neto)),
			None,
		) or next((h for h in lista if _libre(h) and coincide(h, neto)), None)
		if destino:
			destino["facturas"].append(_factura(f, destino["porcentaje"], neto))


def _estado(h) -> None:
	if h["marcado_facturado"] or _validado(h) >= h["porcentaje"] - TOLERANCIA:
		h["estado"] = "Facturado"
		return
	borrador = next((x for x in h["facturas"] if x["docstatus"] == 0 and x["parte"] > 0), None)
	if borrador:
		h["estado"] = "Borrador"
		h["borrador"] = borrador["name"]
	else:
		h["estado"] = h["seguimiento"] or "Pendiente"


@frappe.whitelist()
def listar(incluir_facturados: int = 0) -> dict:
	"""Hitos de las órdenes de venta validadas y abiertas.

	Sin ``incluir_facturados`` solo se leen los pedidos que aún no están facturados del todo.
	"""
	frappe.has_permission("Sales Order", "read", throw=True)
	filtros = {"docstatus": 1, "status": ["not in", ["Closed", "Cancelled"]]}
	if not int(incluir_facturados or 0):
		filtros["per_billed"] = ["<", 99.99]
	pedidos = frappe.get_list(
		"Sales Order",
		filters=filtros,
		fields=[
			"name", "customer", "customer_name", "project", "po_no", "currency", "company",
			"net_total", "total", "conversion_rate",
		],
		order_by="transaction_date desc",
		limit_page_length=0,
	)
	nombres = [p.name for p in pedidos]
	calendario: dict[str, list] = {}
	if nombres:
		for fila in frappe.get_all(
			"Payment Schedule",
			filters={"parenttype": "Sales Order", "parent": ["in", nombres]},
			fields=["name", "parent", "idx", "description", "payment_term", "due_date", "invoice_portion"],
			order_by="parent, idx",
			ignore_permissions=True,
		):
			calendario.setdefault(fila.parent, []).append(fila)

	seguimiento = _seguimiento(nombres)
	facturas = _facturas(nombres)
	con_proyecto = list({p.project for p in pedidos if p.project})
	proyectos = (
		dict(frappe.get_all("Project", filters={"name": ["in", con_proyecto]}, fields=["name", "project_name"], as_list=True))
		if con_proyecto
		else {}
	)
	monedas = {
		c: frappe.get_cached_value("Company", c, "default_currency") for c in {p.company for p in pedidos}
	}

	salida = []
	for p in pedidos:
		filas = calendario.get(p.name) or []
		hitos = []
		for fila in filas:
			marca = seguimiento.get(fila.name) or {}
			porcentaje = flt(fila.invoice_portion)
			base = flt(flt(p.net_total) * porcentaje / 100, 2)
			hitos.append(
				{
					"fila": fila.name,
					"pedido": p.name,
					"numero": fila.idx,
					"total_hitos": len(filas),
					"etiqueta": _etiqueta(fila, len(filas)),
					"fecha": str(fila.due_date) if fila.due_date else None,
					"porcentaje": porcentaje,
					"base": base,
					"base_empresa": flt(base * flt(p.conversion_rate or 1), 2),
					"moneda": p.currency,
					"moneda_empresa": monedas.get(p.company) or p.currency,
					"seguimiento": marca.get("billing_status"),
					"marcado_facturado": marca.get("billing_status") == "Facturado",
					"avance": flt(marca.get("progress_percent")),
					"nota": marca.get("progress_note") or "",
					"facturas": [],
					"cliente": p.customer,
					"cliente_nombre": p.customer_name,
					"proyecto": p.project,
					"proyecto_nombre": proyectos.get(p.project) or "",
					"po_no": p.po_no,
				}
			)
		if hitos:
			_asignar(hitos, facturas.get(p.name) or [], flt(p.total) or flt(p.net_total))
		salida += hitos

	_por_proyecto(salida)
	ver_facturas = bool(frappe.has_permission("Sales Invoice", "read"))
	for h in salida:
		_estado(h)
		h.pop("seguimiento")
		h.pop("marcado_facturado")
		# Quien no puede leer facturas ve el estado del hito, no qué factura lo cubre.
		h["facturas"] = (
			[{"name": x["name"], "docstatus": x["docstatus"]} for x in h["facturas"] if x["parte"] > 0]
			if ver_facturas
			else []
		)
		if not ver_facturas:
			h.pop("borrador", None)

	salida.sort(key=lambda h: (h["fecha"] or "9999", h["pedido"], h["numero"]))
	return {
		"hitos": salida,
		"hoy": nowdate(),
		"puede_facturar": bool(frappe.has_permission("Sales Invoice", "create")),
		"ver_facturas": ver_facturas,
	}


def _factura_del_hito(fila: str, salvo: str | None = None) -> str | None:
	"""Factura (borrador o validada, no rectificativa) que ya factura esa fila del calendario."""
	filtros = {"hito_pedido": fila, "docstatus": ["<", 2], "is_return": 0}
	if salvo:
		filtros["name"] = ["!=", salvo]
	return frappe.db.get_value("Sales Invoice", filtros, "name")


def validar_hito_unico(doc, method=None) -> None:
	"""doc_event validate: un hito del pedido solo se factura una vez."""
	if doc.get("is_return") or not doc.get("hito_pedido"):
		return
	otra = _factura_del_hito(doc.hito_pedido, salvo=doc.name if not doc.is_new() else None)
	if otra:
		frappe.throw(_("Este hito del pedido ya tiene la factura {0}.").format(otra))


def _porcentaje(valor) -> str:
	"""30 → «30», 8.666 → «8,666»."""
	return f"{flt(valor):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _escalar_linea(linea, origen, parte: float) -> bool:
	"""Precio de la línea del pedido por la parte del hito, sin pasar de lo pendiente de facturar."""
	importe = flt(origen.amount)
	if not importe:
		return False
	objetivo = importe * parte
	restante = importe - flt(origen.billed_amt)
	if abs(objetivo) > abs(restante):
		objetivo = restante
	if abs(objetivo) < 0.005 or (objetivo > 0) != (importe > 0):
		return False
	f = objetivo / importe
	linea.qty = origen.qty
	linea.stock_qty = flt(origen.qty) * flt(origen.conversion_factor or 1)
	linea.price_list_rate = flt(origen.price_list_rate) * f
	linea.discount_percentage = flt(origen.discount_percentage)
	linea.discount_amount = flt(origen.discount_amount) * f
	linea.rate_with_margin = flt(origen.rate_with_margin) * f
	linea.margin_rate_or_amount = (
		flt(origen.margin_rate_or_amount) * f
		if origen.margin_type == "Amount"
		else flt(origen.margin_rate_or_amount)
	)
	linea.rate = flt(origen.rate) * f
	linea.amount = flt(linea.rate) * flt(linea.qty)
	return True


@frappe.whitelist()
def factura_desde_hito(sales_order: str, fila: str) -> dict:
	"""Factura de venta sin guardar con lo que factura un hito del pedido.

	Copia el pedido (cliente, proyecto, pedido del cliente, cuentas) con el precio de cada línea
	por el porcentaje del hito. Los impuestos son los del pedido si tienen plantilla activa; si
	no, los de una factura nueva para ese cliente. El vencimiento sale de las condiciones del
	cliente, no del calendario del pedido.
	"""
	frappe.has_permission("Sales Invoice", "create", throw=True)
	pedido = frappe.get_doc("Sales Order", sales_order)
	pedido.check_permission("read")
	if pedido.docstatus != 1:
		frappe.throw(_("La orden de venta {0} no está validada.").format(sales_order))
	plazo = next((r for r in pedido.payment_schedule if r.name == fila), None)
	if not plazo:
		frappe.throw(_("El hito no pertenece a la orden de venta {0}.").format(sales_order))

	existente = _factura_del_hito(plazo.name)
	if existente:
		frappe.throw(_("Este hito ya tiene la factura {0}.").format(existente))

	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	factura = make_sales_invoice(pedido.name)
	parte = flt(plazo.invoice_portion) / 100
	origen = {i.name: i for i in pedido.items}
	lineas = [
		linea
		for linea in factura.items
		if origen.get(linea.so_detail) and _escalar_linea(linea, origen[linea.so_detail], parte)
	]
	if not lineas:
		frappe.throw(_("No queda nada por facturar en la orden de venta {0}.").format(sales_order))
	for i, linea in enumerate(lineas, 1):
		linea.idx = i
	factura.set("items", lineas)
	# Los impuestos del pedido solo valen si llevan una plantilla activa. Muchos pedidos del
	# portal no traen impuestos o traen una plantilla retirada: entonces se deciden como en una
	# factura nueva (reglas de impuestos por país del cliente o plantilla por defecto).
	plantilla_pedido = pedido.get("taxes_and_charges")
	usar_pedido = bool(
		plantilla_pedido
		and not frappe.get_cached_value("Sales Taxes and Charges Template", plantilla_pedido, "disabled")
	)
	if not usar_pedido:
		factura.taxes_and_charges = None
		factura.set("taxes", [])
	for impuesto in factura.get("taxes") or []:
		if impuesto.charge_type == "Actual":
			impuesto.tax_amount = flt(impuesto.tax_amount) * parte
	# Un descuento sobre el total en porcentaje ya vale tal cual; uno en importe se reparte.
	if not flt(pedido.additional_discount_percentage) and flt(pedido.discount_amount):
		factura.discount_amount = flt(pedido.discount_amount) * parte

	if factura.meta.has_field("hito_pedido"):
		factura.hito_pedido = plazo.name
	factura.posting_date = nowdate()
	factura.due_date = None
	factura.set("payment_schedule", [])
	factura.payment_terms_template = frappe.get_cached_value("Customer", pedido.customer, "payment_terms")

	total = len(pedido.payment_schedule)
	partes = [
		_("Pedido del cliente {0}").format(pedido.po_no) if pedido.po_no else _("Pedido {0}").format(pedido.name),
		_("{0}, hito {1} de {2}, {3} % de {4}").format(
			_etiqueta(plazo, total),
			plazo.idx,
			total,
			_porcentaje(plazo.invoice_portion),
			f"{fmt_money(pedido.grand_total, precision=2)} {pedido.currency}",
		),
	]
	factura.remarks = "\n".join(partes)

	avisos = _rellenar(factura, plantilla=not usar_pedido)
	sin_cuenta = [str(linea.idx) for linea in factura.items if not linea.get("income_account")]
	if sin_cuenta:
		avisos.append(
			_(
				"Las líneas {0} no tienen cuenta de ingresos. Elígela en el panel de la línea, o ponla "
				"por defecto en el artículo o en su grupo para que salga sola."
			).format(", ".join(sin_cuenta))
		)
	return _respuesta(factura, avisos)
