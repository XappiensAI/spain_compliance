# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Hitos de facturación: el calendario de pagos de las órdenes de venta.

Cada fila de la tabla Payment Schedule de una orden de venta validada es un hito.
Si otra app del sitio lleva el seguimiento de los hitos (hook ``hitos_seguimiento``), se
añade el estado, el avance y la nota que da.

Lo que se factura es el hito, no las líneas del pedido: la factura lleva una sola línea,
sin artículo, con el nombre del hito, su porcentaje y su importe sobre la base del pedido.
Esa línea va ligada a la orden (``sales_order``) pero no a una línea de ella, así que aquí se
reparte lo facturado entre las líneas del pedido (``actualizar_pedidos``) y se comprueba que
no se factura más que su total (``validar_total_pedido``).

Lo facturado se sabe por las líneas de factura ligadas a la orden. La factura creada
desde un hito guarda la fila en ``hito_pedido``. Las ligadas sin esa marca se asignan
a los hitos por orden, saltando los que el seguimiento ya da por facturados.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import escape_html, flt, fmt_money, nowdate

from spain_compliance.api.facturas import _rellenar, _respuesta

# Margen para dar un hito por cubierto (puntos porcentuales del pedido).
TOLERANCIA = 0.5
# Margen de redondeo al comparar lo facturado con el total del pedido (moneda del pedido).
MARGEN_IMPORTE = 0.5


def _etiqueta(fila, total: int) -> str:
	descripcion = (fila.get("description") or "").strip()
	if descripcion:
		return descripcion
	if (fila.get("payment_term") or "").strip():
		return fila.payment_term.strip()
	return _("Facturación del pedido") if total <= 1 else _("Hito {0}").format(int(fila.idx or 0))


def _bases(neto: float, porcentajes: list[float]) -> list[float]:
	"""Base de cada hito sobre el neto del pedido. Si suman 100, el último absorbe el redondeo."""
	bases = [flt(flt(neto) * flt(p) / 100, 2) for p in porcentajes]
	if bases and abs(sum(flt(p) for p in porcentajes) - 100) < 0.01:
		bases[-1] = flt(flt(neto) - sum(bases[:-1]), 2)
	return bases


def _seguimiento(pedidos: list[str]) -> dict:
	"""Seguimiento de los hitos según las funciones del hook ``hitos_seguimiento``.

	Cada una recibe los pedidos y devuelve, por fila del calendario de pagos, un dict con
	``billing_status``, ``progress_percent`` y ``progress_note``. Con «Facturado» el hito se da
	por facturado; cualquier otro estado se enseña tal cual.
	"""
	salida: dict = {}
	if pedidos:
		for ruta in frappe.get_hooks("hitos_seguimiento"):
			salida.update(frappe.get_attr(ruta)(pedidos) or {})
	return salida


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
			{hito} AS hito_pedido, sii.sales_order, SUM(sii.net_amount) AS importe
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


def _asignar(hitos: list[dict], facturas: list[dict], neto_pedido: float) -> None:
	"""Reparte las facturas del pedido entre sus hitos (ver docstring del módulo).

	La parte de cada factura es el neto de sus líneas entre el neto del pedido.
	"""
	por_fila = {h["fila"]: h for h in hitos}
	for f in facturas:  # primero las facturas, luego las rectificativas
		parte = flt(f.importe) / neto_pedido * 100 if neto_pedido else 0
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
			"name",
			"customer",
			"customer_name",
			"project",
			"po_no",
			"currency",
			"company",
			"net_total",
			"conversion_rate",
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
		dict(
			frappe.get_all(
				"Project",
				filters={"name": ["in", con_proyecto]},
				fields=["name", "project_name"],
				as_list=True,
			)
		)
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
		bases = _bases(p.net_total, [fila.invoice_portion for fila in filas])
		for fila, base in zip(filas, bases, strict=True):
			marca = seguimiento.get(fila.name) or {}
			porcentaje = flt(fila.invoice_portion)
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
			_asignar(hitos, facturas.get(p.name) or [], flt(p.net_total))
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


def _neto_facturado(pedido: str, salvo: str | None = None) -> float:
	"""Neto de las líneas de factura validadas ligadas al pedido (las rectificativas restan)."""
	return flt(
		frappe.db.sql(
			"""
			SELECT SUM(sii.net_amount) FROM `tabSales Invoice Item` sii
			JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE sii.sales_order = %s AND si.docstatus = 1 AND si.name != %s
			""",
			(pedido, salvo or ""),
		)[0][0]
	)


# Líneas de factura de un hito: ligadas al pedido y no a una de sus líneas, en una factura
# creada desde un hito o en su rectificativa (que solo cuenta si ERPNext la contaría).
_LINEAS_HITO = """
	FROM `tabSales Invoice Item` sii
	JOIN `tabSales Invoice` si ON si.name = sii.parent
	LEFT JOIN `tabSales Invoice` orig ON orig.name = si.return_against
	WHERE sii.sales_order = %(pedido)s AND IFNULL(sii.so_detail, '') = ''
		AND COALESCE(NULLIF(si.hito_pedido, ''), NULLIF(orig.hito_pedido, '')) IS NOT NULL
		AND si.docstatus = 1 AND (si.is_return = 0 OR si.update_billed_amount_in_sales_order = 1)
"""


def _pedidos_por_hitos(doc) -> list[str]:
	"""Pedidos de la factura que se facturan por hitos con una línea por hito."""
	if not doc.meta.has_field("hito_pedido"):
		return []
	es_hito = bool(doc.get("hito_pedido")) or bool(
		doc.get("return_against") and frappe.db.get_value("Sales Invoice", doc.return_against, "hito_pedido")
	)
	salida = []
	for pedido in dict.fromkeys(i.sales_order for i in doc.items if i.get("sales_order")):
		propia = es_hito and any(i.sales_order == pedido and not i.get("so_detail") for i in doc.items)
		if propia or frappe.db.sql(f"SELECT 1 {_LINEAS_HITO} LIMIT 1", {"pedido": pedido}):
			salida.append(pedido)
	return salida


def validar_total_pedido(doc, method=None) -> None:
	"""doc_event validate: en un pedido facturado por hitos no se factura más que su total.

	ERPNext lo comprueba línea a línea, y la línea de un hito no corresponde a ninguna.
	"""
	if doc.get("is_return"):
		return
	ajustes = frappe.get_cached_doc("Accounts Settings")
	rol = ajustes.get("role_allowed_to_over_bill")
	if rol and rol in frappe.get_roles():
		return
	for pedido in _pedidos_por_hitos(doc):
		neto = flt(frappe.db.get_value("Sales Order", pedido, "net_total"))
		propio = sum(flt(i.net_amount) for i in doc.items if i.get("sales_order") == pedido)
		previo = _neto_facturado(pedido, salvo=doc.name)
		maximo = neto * (1 + flt(ajustes.get("over_billing_allowance")) / 100)
		if previo + propio > maximo + MARGEN_IMPORTE:
			frappe.throw(
				_(
					"La orden de venta {0} tiene un total de {1} sin impuestos y ya hay {2} facturados. "
					"Esta factura la pasaría en {3}."
				).format(
					pedido,
					fmt_money(neto, precision=2, currency=doc.currency),
					fmt_money(previo, precision=2, currency=doc.currency),
					fmt_money(previo + propio - neto, precision=2, currency=doc.currency),
				)
			)


def actualizar_pedidos(doc, method=None) -> None:
	"""doc_event on_submit/on_cancel: reparte lo facturado por hitos entre las líneas del pedido.

	Así el «% facturado» y el estado del pedido, y lo que depende de ellos, siguen siendo ciertos.
	"""
	for pedido in _pedidos_por_hitos(doc):
		neto = flt(frappe.db.get_value("Sales Order", pedido, "net_total"))
		por_hitos = flt(frappe.db.sql(f"SELECT SUM(sii.net_amount) {_LINEAS_HITO}", {"pedido": pedido})[0][0])
		parte = por_hitos / neto if neto else 0
		directo = dict(
			frappe.db.sql(
				"""
				SELECT sii.so_detail, SUM(sii.amount) FROM `tabSales Invoice Item` sii
				JOIN `tabSales Invoice` si ON si.name = sii.parent
				WHERE sii.sales_order = %s AND IFNULL(sii.so_detail, '') != '' AND si.docstatus = 1
					AND (si.is_return = 0 OR si.update_billed_amount_in_sales_order = 1)
				GROUP BY sii.so_detail
				""",
				pedido,
			)
		)
		for linea in frappe.get_all(
			"Sales Order Item", filters={"parent": pedido}, fields=["name", "amount"], ignore_permissions=True
		):
			frappe.db.set_value(
				"Sales Order Item",
				linea.name,
				"billed_amt",
				flt(flt(directo.get(linea.name)) + flt(linea.amount) * parte, 2),
				update_modified=False,
			)
		doc._update_percent_field(
			{
				"name": pedido,
				"target_parent_dt": "Sales Order",
				"target_parent_field": "per_billed",
				"target_dt": "Sales Order Item",
				"target_ref_field": "amount",
				"target_field": "billed_amt",
				"status_field": "billing_status",
				"keyword": "Billed",
			}
		)


def _porcentaje(valor) -> str:
	"""30 → «30», 8.666 → «8,666»."""
	return f"{flt(valor):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _linea_hito(pedido, plazo, importe: float, cuenta: str | None, centro: str | None) -> dict:
	"""La única línea de la factura: nombre del hito, su porcentaje y su importe."""
	pct = _porcentaje(plazo.invoice_portion)
	nombre = _etiqueta(plazo, len(pedido.payment_schedule))
	# «Entrega 50%» ya dice el porcentaje.
	if not re.search(rf"(?<![\d.,]){re.escape(pct)}\s*%", nombre):
		nombre = f"{nombre[: 138 - len(pct) - 4]} — {pct} %"
	idioma = (
		frappe.get_cached_value("Customer", pedido.customer, "language") or pedido.get("language") or ""
	).lower()
	de, proyecto = ("of", "Project") if idioma.startswith("en") else ("de", "Proyecto")
	descripcion = f"{pct} % {de} {fmt_money(pedido.net_total, precision=2)} {pedido.currency}"
	if pedido.project:
		titulo = frappe.get_cached_value("Project", pedido.project, "project_name") or ""
		descripcion += f"<br>{proyecto} {escape_html(pedido.project)}"
		if titulo and titulo != pedido.project:
			descripcion += f" · {escape_html(titulo)}"
	uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
	return {
		"item_name": nombre,
		"description": descripcion,
		"qty": 1,
		"uom": uom,
		"stock_uom": uom,
		"conversion_factor": 1,
		"stock_qty": 1,
		"rate": importe,
		"amount": importe,
		"income_account": cuenta,
		"cost_center": centro,
		"project": pedido.project,
		"sales_order": pedido.name,
	}


def _cuenta_principal(lineas, importes: dict[str, float], campo: str) -> tuple[str | None, bool]:
	"""Valor del campo con más importe entre las líneas, y si hay más de uno."""
	suma: dict[str, float] = {}
	for linea in lineas:
		if linea.get(campo):
			suma[linea.get(campo)] = suma.get(linea.get(campo), 0) + abs(flt(importes.get(linea.so_detail)))
	return (max(suma, key=suma.get) if suma else None), len(suma) > 1


@frappe.whitelist()
def factura_desde_hito(sales_order: str, fila: str) -> dict:
	"""Factura de venta sin guardar con lo que factura un hito del pedido.

	Copia la cabecera del pedido (cliente, proyecto, pedido del cliente) y lleva una sola línea,
	la del hito, con su porcentaje sobre la base imponible del pedido (los descuentos ya
	descontados). La cuenta de ingresos es la de más importe del pedido. Los impuestos son los
	del pedido si tienen plantilla activa; si no, los de una factura nueva para ese cliente. El
	vencimiento sale de las condiciones del cliente, no del calendario del pedido.
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
	filas = pedido.payment_schedule
	bases = _bases(pedido.net_total, [r.invoice_portion for r in filas])
	base = next(b for r, b in zip(filas, bases, strict=True) if r.name == plazo.name)
	importe = min(base, flt(flt(pedido.net_total) - _neto_facturado(pedido.name), 2))
	if importe < 0.005:
		frappe.throw(_("No queda nada por facturar en la orden de venta {0}.").format(sales_order))
	parte = importe / flt(pedido.net_total)

	importes = {i.name: i.net_amount for i in pedido.items}
	cuenta, varias_cuentas = _cuenta_principal(factura.items, importes, "income_account")
	centro, _varios = _cuenta_principal(factura.items, importes, "cost_center")
	if not cuenta:
		cuenta = frappe.get_cached_value("Company", pedido.company, "default_income_account")
	if not centro:
		centro = frappe.get_cached_value("Company", pedido.company, "cost_center")

	factura.set("items", [])
	factura.set("packed_items", [])
	factura.append("items", _linea_hito(pedido, plazo, importe, cuenta, centro))
	# La base del pedido ya lleva su descuento, y no hay tarifa que aplicar a un hito.
	factura.ignore_pricing_rule = 1
	factura.additional_discount_percentage = 0
	factura.discount_amount = 0
	factura.update_stock = 0
	# Los impuestos del pedido solo valen si llevan una plantilla activa. Si no los trae o su
	# plantilla está retirada, se deciden como en una factura nueva (reglas de impuestos por país
	# del cliente o plantilla por defecto).
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
		# El importe del hito es la base, sin impuestos incluidos.
		impuesto.included_in_print_rate = 0

	if factura.meta.has_field("hito_pedido"):
		factura.hito_pedido = plazo.name
	factura.posting_date = nowdate()
	factura.due_date = None
	factura.set("payment_schedule", [])
	factura.payment_terms_template = frappe.get_cached_value("Customer", pedido.customer, "payment_terms")

	factura.remarks = (
		_("Pedido del cliente {0}").format(pedido.po_no)
		if pedido.po_no
		else _("Pedido {0}").format(pedido.name)
	)

	avisos = _rellenar(factura, plantilla=not usar_pedido)
	if importe < base - 0.005:
		avisos.append(
			_("El hito es de {0}, pero en el pedido solo quedan {1} por facturar.").format(
				fmt_money(base, precision=2, currency=pedido.currency),
				fmt_money(importe, precision=2, currency=pedido.currency),
			)
		)
	if not factura.items[0].get("income_account"):
		avisos.append(_("La línea no tiene cuenta de ingresos. Elígela en el panel de la línea."))
	elif varias_cuentas:
		avisos.append(
			_(
				"El pedido reparte sus líneas entre varias cuentas de ingresos. La línea del hito usa {0}, "
				"la de más importe. Cámbiala en el panel de la línea si no es la correcta."
			).format(cuenta)
		)
	if any(i.item_tax_template for i in pedido.items):
		# La línea no tiene artículo del que traer su tipo: lleva el de los impuestos de la cabecera.
		avisos.append(
			_("Hay líneas del pedido con plantilla de impuestos propia. Revisa los impuestos de la factura.")
		)
	return _respuesta(factura, avisos)
