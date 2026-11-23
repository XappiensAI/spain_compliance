# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Tesorería: partidas abiertas, antigüedad, periodo medio de pago y previsión de caja.

Las partidas abiertas salen del ``Payment Ledger Entry`` de ERPNext, que ya
deja cada cobro, pago y abono enlazado con su factura y en moneda de la compañía.
Solo se detallan clientes y proveedores; el resto de terceros (empleados,
socios…) se presenta como un total sin nombres.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_first_day, get_last_day, getdate

from spain_compliance.contabilidad.pgc import nombre_pgc, normalizar_numero

_EPS = 0.005
RANGOS_POR_DEFECTO = (30, 60, 90, 120)
ESTADOS_DUDOSOS = ("Dudoso Cobro", "Pérdida")
PLAZO_LEGAL_PAGO = 60
_MAX_DOCUMENTOS = 1000
_MAX_PARTIDAS_PREVISION = 3000

TIPOS = {
	"cobrar": {"account_type": "Receivable", "party_type": "Customer", "factura": "Sales Invoice"},
	"pagar": {"account_type": "Payable", "party_type": "Supplier", "factura": "Purchase Invoice"},
}


def parse_rangos(rangos) -> tuple[int, ...]:
	if not rangos:
		return RANGOS_POR_DEFECTO
	if isinstance(rangos, str):
		rangos = [r for r in rangos.replace(";", ",").split(",") if r.strip()]
	valores = sorted({cint(r) for r in rangos if cint(r) > 0})
	return tuple(valores[:8]) or RANGOS_POR_DEFECTO


def etiquetas_rangos(rangos: tuple[int, ...]) -> list[str]:
	etiquetas = []
	anterior = 0
	for limite in rangos:
		etiquetas.append(_("{0}-{1} días").format(anterior + 1, limite))
		anterior = limite
	etiquetas.append(_("Más de {0} días").format(anterior))
	return etiquetas


def tramo(dias_vencido: int, rangos: tuple[int, ...]) -> int | None:
	"""Índice del tramo de antigüedad. ``None`` si aún no ha vencido."""
	if dias_vencido <= 0:
		return None
	for i, limite in enumerate(rangos):
		if dias_vencido <= limite:
			return i
	return len(rangos)


# Partidas abiertas ----------------------------------------------------------------------


def partidas_abiertas(company: str, tipo: str, fecha) -> list[dict]:
	"""Saldo pendiente por documento a una fecha, en moneda de la compañía.

	Positivo es lo que se cobra (o paga) todavía; negativo, anticipos y abonos sin aplicar.
	"""
	conf = TIPOS[tipo]
	return frappe.db.sql(
		"""
		SELECT ple.party_type, ple.party,
			ple.against_voucher_type AS voucher_type, ple.against_voucher_no AS voucher_no,
			SUM(ple.amount) AS pendiente,
			SUM(CASE WHEN ple.voucher_no = ple.against_voucher_no
				AND ple.voucher_type = ple.against_voucher_type THEN ple.amount ELSE 0 END) AS importe,
			MAX(CASE WHEN ple.voucher_no = ple.against_voucher_no
				AND ple.voucher_type = ple.against_voucher_type THEN ple.due_date END) AS vencimiento,
			MIN(CASE WHEN ple.voucher_no = ple.against_voucher_no
				AND ple.voucher_type = ple.against_voucher_type THEN ple.posting_date END) AS fecha
		FROM `tabPayment Ledger Entry` ple
		WHERE ple.company = %(company)s AND ple.account_type = %(account_type)s
			AND ple.delinked = 0 AND ple.posting_date <= %(fecha)s
		GROUP BY ple.party_type, ple.party, ple.against_voucher_type, ple.against_voucher_no
		HAVING ABS(SUM(ple.amount)) > 0.005
		""",
		{"company": company, "account_type": conf["account_type"], "fecha": getdate(fecha)},
		as_dict=True,
	)


def _nombres(party_type: str, parties: set[str]) -> dict[str, str]:
	if not parties:
		return {}
	campo = "customer_name" if party_type == "Customer" else "supplier_name"
	return {
		row.name: row.get(campo) or row.name
		for row in frappe.get_all(party_type, filters={"name": ["in", list(parties)]}, fields=["name", campo])
	}


def _estados_factura(doctype: str, nombres: list[str]) -> dict[str, dict]:
	if not nombres:
		return {}
	campos = ["name", "status", "posting_date"]
	if doctype == "Purchase Invoice":
		campos.append("bill_date")
	return {
		row.name: row for row in frappe.get_all(doctype, filters={"name": ["in", nombres]}, fields=campos)
	}


def antiguedad(company: str, tipo: str, fecha, rangos=None) -> dict:
	"""Antigüedad de saldos de clientes (``cobrar``) o proveedores (``pagar``) a una fecha."""
	conf = TIPOS[tipo]
	fecha = getdate(fecha)
	rangos = parse_rangos(rangos)
	n_tramos = len(rangos) + 1
	partidas = partidas_abiertas(company, tipo, fecha)

	propias = [p for p in partidas if p.party_type == conf["party_type"]]
	otros = round(sum(flt(p.pendiente) for p in partidas if p.party_type != conf["party_type"]), 2)
	nombres = _nombres(conf["party_type"], {p.party for p in propias})
	facturas = _estados_factura(
		conf["factura"], [p.voucher_no for p in propias if p.voucher_type == conf["factura"]]
	)

	def vacio():
		return {
			"total": 0.0,
			"no_vencido": 0.0,
			"tramos": [0.0] * n_tramos,
			"sin_aplicar": 0.0,
			"documentos": 0,
		}

	resumen = vacio()
	resumen.update({"dudoso": 0.0, "perdida": 0.0, "vencido": 0.0})
	terceros: dict[str, dict] = {}
	documentos = []
	for p in propias:
		pendiente = flt(p.pendiente)
		vencimiento = getdate(p.vencimiento or p.fecha or fecha)
		dias = date_diff(fecha, vencimiento)
		factura = facturas.get(p.voucher_no) if p.voucher_type == conf["factura"] else None
		estado = factura.status if factura else ""
		tercero = terceros.setdefault(
			p.party,
			{**vacio(), "party": p.party, "nombre": nombres.get(p.party, p.party), "dias_max": 0},
		)
		for destino in (resumen, tercero):
			destino["total"] += pendiente
			destino["documentos"] += 1
			if pendiente < 0:
				destino["sin_aplicar"] += pendiente
				continue
			indice = tramo(dias, rangos)
			if indice is None:
				destino["no_vencido"] += pendiente
			else:
				destino["tramos"][indice] += pendiente
		if pendiente > 0 and dias > 0:
			resumen["vencido"] += pendiente
			tercero["dias_max"] = max(tercero["dias_max"], dias)
		if estado == "Dudoso Cobro":
			resumen["dudoso"] += pendiente
		elif estado == "Pérdida":
			resumen["perdida"] += pendiente
		documentos.append(
			{
				"voucher_type": p.voucher_type,
				"voucher_no": p.voucher_no,
				"party": p.party,
				"nombre": nombres.get(p.party, p.party),
				"fecha": str(getdate(p.fecha)) if p.fecha else "",
				"vencimiento": str(vencimiento),
				"dias": dias,
				"importe": round(flt(p.importe), 2),
				"pendiente": round(pendiente, 2),
				"estado": estado,
			}
		)

	def redondear(fila):
		for campo in ("total", "no_vencido", "sin_aplicar", "dudoso", "perdida", "vencido"):
			if campo in fila:
				fila[campo] = round(fila[campo], 2)
		fila["tramos"] = [round(v, 2) for v in fila["tramos"]]
		return fila

	documentos.sort(key=lambda d: (-d["dias"], -abs(d["pendiente"])))
	return {
		"fecha": str(fecha),
		"rangos": list(rangos),
		"etiquetas": etiquetas_rangos(rangos),
		"resumen": redondear(resumen),
		"terceros": sorted((redondear(t) for t in terceros.values()), key=lambda t: -t["total"]),
		"documentos": documentos[:_MAX_DOCUMENTOS],
		"documentos_total": len(documentos),
		"otros_terceros": otros,
	}


# Vencimientos por plazos -----------------------------------------------------------------


def _plazos(parenttype: str, nombres: list[str]) -> dict[str, list[dict]]:
	if not nombres:
		return {}
	plazos: dict[str, list[dict]] = defaultdict(list)
	for row in frappe.get_all(
		"Payment Schedule",
		filters={"parenttype": parenttype, "parent": ["in", nombres]},
		fields=["parent", "due_date", "payment_amount", "outstanding"],
		order_by="due_date asc",
	):
		plazos[row.parent].append(row)
	return plazos


def repartir_en_plazos(pendiente: float, vencimiento, plazos: list[dict]) -> list[tuple[date, float]]:
	"""Reparte el pendiente de un documento entre sus plazos aún abiertos.

	Se usa el pendiente de cada plazo como peso (ERPNext lo lleva en moneda del
	documento); si los plazos no lo tienen informado, todo vence en ``vencimiento``.
	"""
	abiertos = [p for p in plazos or [] if flt(p.get("outstanding")) > _EPS]
	peso_total = sum(flt(p["outstanding"]) for p in abiertos)
	if not abiertos or peso_total < _EPS:
		return [(getdate(vencimiento), pendiente)]
	return [(getdate(p["due_date"]), pendiente * flt(p["outstanding"]) / peso_total) for p in abiertos]


def vencimientos(company: str, tipo: str, fecha, excluir_dudosos: bool = False) -> list[dict]:
	"""Partidas abiertas positivas de clientes o proveedores, una fila por plazo."""
	conf = TIPOS[tipo]
	partidas = [
		p
		for p in partidas_abiertas(company, tipo, fecha)
		if p.party_type == conf["party_type"] and flt(p.pendiente) > _EPS
	]
	facturas = [p.voucher_no for p in partidas if p.voucher_type == conf["factura"]]
	plazos = _plazos(conf["factura"], facturas)
	estados = _estados_factura(conf["factura"], facturas) if excluir_dudosos else {}
	nombres = _nombres(conf["party_type"], {p.party for p in partidas})
	filas = []
	for p in partidas:
		estado = estados.get(p.voucher_no)
		if estado and estado.status in ESTADOS_DUDOSOS:
			continue
		vencimiento = p.vencimiento or p.fecha or fecha
		for dia, importe in repartir_en_plazos(flt(p.pendiente), vencimiento, plazos.get(p.voucher_no)):
			filas.append(
				{
					"fecha": dia,
					"importe": importe,
					"doctype": p.voucher_type,
					"documento": p.voucher_no,
					"tercero": nombres.get(p.party, p.party),
				}
			)
	return filas


# Periodo medio de pago a proveedores ----------------------------------------------------------


def periodo_medio_pago(company: str, desde, hasta, plazo_legal: int = PLAZO_LEGAL_PAGO) -> dict:
	"""Periodo medio de pago a proveedores (Resolución ICAC de 29 de enero de 2016).

	Se cuenta desde la fecha de la factura del proveedor (o de contabilización si
	no la tiene), no desde la recepción de la mercancía, que ERPNext no guarda en
	la factura. Solo facturas de compra y pagos aplicados a ellas.
	"""
	desde, hasta = getdate(desde), getdate(hasta)
	pagos = frappe.db.sql(
		"""
		SELECT ple.against_voucher_no AS factura, ple.posting_date, -ple.amount AS importe
		FROM `tabPayment Ledger Entry` ple
		WHERE ple.company = %(company)s AND ple.account_type = 'Payable' AND ple.delinked = 0
			AND ple.party_type = 'Supplier' AND ple.against_voucher_type = 'Purchase Invoice'
			AND ple.voucher_no != ple.against_voucher_no
			AND ple.voucher_type IN ('Payment Entry', 'Journal Entry')
			AND ple.amount < 0 AND ple.posting_date BETWEEN %(desde)s AND %(hasta)s
		""",
		{"company": company, "desde": desde, "hasta": hasta},
		as_dict=True,
	)
	pendientes = [
		p
		for p in partidas_abiertas(company, "pagar", hasta)
		if p.party_type == "Supplier" and p.voucher_type == "Purchase Invoice" and flt(p.pendiente) > _EPS
	]
	facturas = _estados_factura(
		"Purchase Invoice", list({p.factura for p in pagos} | {p.voucher_no for p in pendientes})
	)

	def fecha_factura(nombre, defecto):
		factura = facturas.get(nombre)
		if not factura:
			return getdate(defecto)
		return getdate(factura.bill_date or factura.posting_date)

	pagado = dias_pagado = 0.0
	dentro_plazo = 0.0
	n_pagos = n_dentro = 0
	for pago in pagos:
		importe = flt(pago.importe)
		dias = max(date_diff(pago.posting_date, fecha_factura(pago.factura, pago.posting_date)), 0)
		pagado += importe
		dias_pagado += dias * importe
		n_pagos += 1
		if dias <= plazo_legal:
			dentro_plazo += importe
			n_dentro += 1

	pendiente = dias_pendiente = 0.0
	fuera_plazo_pendiente = 0.0
	for p in pendientes:
		importe = flt(p.pendiente)
		dias = max(date_diff(hasta, fecha_factura(p.voucher_no, p.fecha or hasta)), 0)
		pendiente += importe
		dias_pendiente += dias * importe
		if dias > plazo_legal:
			fuera_plazo_pendiente += importe

	ratio_pagadas = dias_pagado / pagado if pagado > _EPS else None
	ratio_pendientes = dias_pendiente / pendiente if pendiente > _EPS else None
	total = pagado + pendiente
	pmp = (dias_pagado + dias_pendiente) / total if total > _EPS else None
	return {
		"desde": str(desde),
		"hasta": str(hasta),
		"plazo_legal": plazo_legal,
		"pmp": round(pmp, 1) if pmp is not None else None,
		"ratio_pagadas": round(ratio_pagadas, 1) if ratio_pagadas is not None else None,
		"ratio_pendientes": round(ratio_pendientes, 1) if ratio_pendientes is not None else None,
		"pagado": round(pagado, 2),
		"pendiente": round(pendiente, 2),
		"pagos": n_pagos,
		"pagado_en_plazo": round(dentro_plazo, 2),
		"pagos_en_plazo": n_dentro,
		"pendiente_fuera_plazo": round(fuera_plazo_pendiente, 2),
	}


# Efectivo ---------------------------------------------------------------------------------------


def cuentas_tesoreria(company: str) -> list[dict]:
	"""Cuentas de caja y bancos: tipo Bank o Cash, o número del subgrupo 57."""
	return frappe.db.sql(
		"""
		SELECT name, account_name, account_number, account_type
		FROM `tabAccount`
		WHERE company = %(company)s AND is_group = 0
			AND (account_type IN ('Bank', 'Cash') OR account_number LIKE '57%%')
		ORDER BY account_number, name
		""",
		{"company": company},
		as_dict=True,
	)


def saldos_tesoreria(company: str, fecha) -> list[dict]:
	cuentas = cuentas_tesoreria(company)
	if not cuentas:
		return []
	saldos = {
		row.account: flt(row.saldo)
		for row in frappe.db.sql(
			"""
			SELECT account, SUM(debit) - SUM(credit) AS saldo
			FROM `tabGL Entry`
			WHERE company = %(company)s AND account IN %(cuentas)s
				AND posting_date <= %(fecha)s AND is_cancelled = 0
			GROUP BY account
			""",
			{"company": company, "cuentas": [c.name for c in cuentas], "fecha": getdate(fecha)},
			as_dict=True,
		)
	}
	return [
		{
			"account": c.name,
			"numero": normalizar_numero(c.account_number),
			"nombre": c.account_name,
			"saldo": round(saldos.get(c.name, 0.0), 2),
		}
		for c in cuentas
		if abs(saldos.get(c.name, 0.0)) >= _EPS
	]


def movimientos_tesoreria(company: str, desde, hasta, grano: str = "month") -> list[dict]:
	"""Entradas y salidas reales de caja y bancos por día o mes, sin traspasos internos."""
	cuentas = [c.name for c in cuentas_tesoreria(company)]
	if not cuentas:
		return []
	formato = "%Y-%m-%d" if grano == "day" else "%Y-%m-01"
	return frappe.db.sql(
		"""
		SELECT DATE_FORMAT(g.posting_date, %(formato)s) AS fecha,
			SUM(g.debit) AS entradas, SUM(g.credit) AS salidas
		FROM `tabGL Entry` g
		WHERE g.company = %(company)s AND g.account IN %(cuentas)s AND g.is_cancelled = 0
			AND g.posting_date BETWEEN %(desde)s AND %(hasta)s AND IFNULL(g.is_opening, 'No') = 'No'
			AND NOT EXISTS (
				SELECT 1 FROM `tabPayment Entry` pe
				WHERE g.voucher_type = 'Payment Entry' AND pe.name = g.voucher_no
					AND pe.payment_type = 'Internal Transfer'
			)
			AND NOT (g.voucher_type = 'Journal Entry' AND NOT EXISTS (
				SELECT 1 FROM `tabJournal Entry Account` jea
				WHERE jea.parent = g.voucher_no AND jea.account NOT IN %(cuentas)s
			))
		GROUP BY fecha
		ORDER BY fecha
		""",
		{
			"company": company,
			"cuentas": cuentas,
			"desde": getdate(desde),
			"hasta": getdate(hasta),
			"formato": formato,
		},
		as_dict=True,
	)


# Previsión ------------------------------------------------------------------------------------------


def tramos_prevision(inicio, numero: int, grano: str) -> list[dict]:
	"""Periodos de la previsión. El primero empieza en ``inicio``; semanas de lunes a domingo."""
	inicio = getdate(inicio)
	periodos = []
	actual = inicio
	for _i in range(numero):
		if grano == "month":
			fin = getdate(get_last_day(actual))
			label = actual.strftime("%m/%Y")
		else:
			fin = actual + timedelta(days=6 - actual.weekday())
			label = _("Sem. {0}").format(actual.strftime("%d/%m"))
		periodos.append({"inicio": actual, "fin": fin, "label": label})
		actual = fin + timedelta(days=1)
	return periodos


def indice_tramo(fecha, periodos: list[dict]) -> int | None:
	"""Periodo que contiene la fecha. Lo anterior al primero va al primero; lo posterior, ``None``."""
	fecha = getdate(fecha)
	if fecha < periodos[0]["inicio"]:
		return 0
	for i, periodo in enumerate(periodos):
		if fecha <= periodo["fin"]:
			return i
	return None


def _pedidos(company: str, doctype: str, hasta) -> list[dict]:
	"""Importe de pedidos validados aún sin facturar, por plazo o fecha prevista."""
	campo_fecha = "delivery_date" if doctype == "Sales Order" else "schedule_date"
	campo_tercero = "customer_name" if doctype == "Sales Order" else "supplier_name"
	pedidos = frappe.get_all(
		doctype,
		filters={
			"company": company,
			"docstatus": 1,
			"status": ["not in", ["Closed", "Completed", "On Hold"]],
			"per_billed": ["<", 99.99],
		},
		fields=[
			"name",
			"transaction_date",
			campo_fecha,
			campo_tercero,
			"base_grand_total",
			"per_billed",
			"advance_paid",
			"conversion_rate",
		],
		limit_page_length=0,
	)
	plazos = _plazos(doctype, [p.name for p in pedidos])
	filas = []
	for p in pedidos:
		pendiente = flt(p.base_grand_total) * (1 - flt(p.per_billed) / 100) - flt(p.advance_paid) * flt(
			p.conversion_rate or 1
		)
		if pendiente < _EPS:
			continue
		filas_plazo = [
			{"due_date": row.due_date, "outstanding": row.payment_amount} for row in plazos.get(p.name, [])
		]
		vencimiento = p.get(campo_fecha) or p.transaction_date
		for dia, importe in repartir_en_plazos(pendiente, vencimiento, filas_plazo):
			if getdate(dia) > getdate(hasta):
				continue
			filas.append(
				{
					"fecha": getdate(dia),
					"importe": importe,
					"doctype": doctype,
					"documento": p.name,
					"tercero": p.get(campo_tercero) or "",
				}
			)
	return filas


def _cuenta_dominante(asientos: list[str], cuentas_caja: set[str]) -> dict[str, str]:
	"""Contrapartida principal (la de mayor importe que no es de tesorería) de cada asiento."""
	if not asientos:
		return {}
	mejor: dict[str, tuple[float, str]] = {}
	for row in frappe.get_all(
		"Journal Entry Account",
		filters={"parent": ["in", asientos], "parenttype": "Journal Entry"},
		fields=["parent", "account", "debit", "credit"],
		limit_page_length=0,
	):
		if row.account in cuentas_caja:
			continue
		importe = abs(flt(row.debit) - flt(row.credit))
		if row.parent not in mejor or importe > mejor[row.parent][0]:
			mejor[row.parent] = (importe, row.account)
	return {parent: account for parent, (_importe, account) in mejor.items()}


def _concepto_cuenta(account: str, numeros: dict[str, str]) -> str:
	numero = normalizar_numero(numeros.get(account))
	if len(numero) >= 2:
		nombre = nombre_pgc(numero[:2])
		if nombre:
			return f"{numero[:2]} {nombre}"
	return _("Otros movimientos")


def recurrentes(company: str, hasta, meses: int = 3) -> dict:
	"""Media mensual de entradas y salidas de caja que no son cobros ni pagos de facturas.

	Nóminas, impuestos, cuotas de préstamos y otros cargos que se pagan con asientos
	o con pagos a terceros que no son clientes ni proveedores. Excluye traspasos
	entre cuentas de tesorería y asientos de apertura.
	"""
	meses = max(cint(meses), 1)
	fin = getdate(add_days(get_first_day(hasta), -1))
	inicio = getdate(get_first_day(add_months(fin, -(meses - 1))))
	cuentas = [c.name for c in cuentas_tesoreria(company)]
	vacio = {
		"meses": meses,
		"desde": str(inicio),
		"hasta": str(fin),
		"entradas_mes": 0.0,
		"salidas_mes": 0.0,
		"desglose": [],
	}
	if not cuentas:
		return vacio
	movimientos = frappe.db.sql(
		"""
		SELECT g.voucher_type, g.voucher_no, SUM(g.debit) AS entradas, SUM(g.credit) AS salidas
		FROM `tabGL Entry` g
		WHERE g.company = %(company)s AND g.account IN %(cuentas)s AND g.is_cancelled = 0
			AND g.posting_date BETWEEN %(inicio)s AND %(fin)s AND IFNULL(g.is_opening, 'No') = 'No'
			AND g.voucher_type IN ('Journal Entry', 'Payment Entry')
			AND NOT EXISTS (
				SELECT 1 FROM `tabPayment Entry` pe
				WHERE g.voucher_type = 'Payment Entry' AND pe.name = g.voucher_no
					AND (pe.payment_type = 'Internal Transfer' OR pe.party_type IN ('Customer', 'Supplier'))
			)
			AND NOT EXISTS (
				SELECT 1 FROM `tabJournal Entry Account` jea
				WHERE g.voucher_type = 'Journal Entry' AND jea.parent = g.voucher_no
					AND jea.party_type IN ('Customer', 'Supplier')
			)
		GROUP BY g.voucher_type, g.voucher_no
		""",
		{"company": company, "cuentas": cuentas, "inicio": inicio, "fin": fin},
		as_dict=True,
	)
	caja = set(cuentas)
	asientos = [m.voucher_no for m in movimientos if m.voucher_type == "Journal Entry"]
	dominante = _cuenta_dominante(asientos, caja)
	pagos = (
		{
			row.name: row
			for row in frappe.get_all(
				"Payment Entry",
				filters={
					"name": ["in", [m.voucher_no for m in movimientos if m.voucher_type == "Payment Entry"]]
				},
				fields=["name", "party_type"],
			)
		}
		if any(m.voucher_type == "Payment Entry" for m in movimientos)
		else {}
	)
	numeros = (
		{
			row.name: row.account_number
			for row in frappe.get_all(
				"Account",
				filters={"name": ["in", list(set(dominante.values()))]},
				fields=["name", "account_number"],
			)
		}
		if dominante
		else {}
	)

	desglose: dict[str, dict[str, float]] = defaultdict(lambda: {"entradas": 0.0, "salidas": 0.0})
	for m in movimientos:
		neto_entrada = flt(m.entradas) - flt(m.salidas)
		if abs(neto_entrada) < _EPS:
			continue
		if m.voucher_type == "Journal Entry":
			cuenta = dominante.get(m.voucher_no)
			if not cuenta:
				continue
			concepto = _concepto_cuenta(cuenta, numeros)
		else:
			party_type = (pagos.get(m.voucher_no) or {}).get("party_type") or ""
			concepto = (
				_("Pagos y cobros a {0}").format(_(party_type)) if party_type else _("Otros movimientos")
			)
		clave = "entradas" if neto_entrada > 0 else "salidas"
		desglose[concepto][clave] += abs(neto_entrada)

	filas = [
		{
			"concepto": concepto,
			"entradas_mes": round(v["entradas"] / meses, 2),
			"salidas_mes": round(v["salidas"] / meses, 2),
		}
		for concepto, v in desglose.items()
	]
	filas.sort(key=lambda f: -(f["salidas_mes"] + f["entradas_mes"]))
	return {
		**vacio,
		"entradas_mes": round(sum(f["entradas_mes"] for f in filas), 2),
		"salidas_mes": round(sum(f["salidas_mes"] for f in filas), 2),
		"desglose": filas,
	}


FUENTES = ("facturas", "pedidos", "recurrentes")
TRATAMIENTO_VENCIDOS = {
	"prudente": {"cobros": False, "pagos": True},
	"todos": {"cobros": True, "pagos": True},
	"ninguno": {"cobros": False, "pagos": False},
}


def prevision(
	company: str,
	fecha=None,
	numero: int = 13,
	grano: str = "week",
	incluir_pedidos: bool = True,
	incluir_recurrentes: bool = True,
	meses_historico: int = 3,
	vencidos: str = "prudente",
	excluir_dudosos: bool = True,
) -> dict:
	"""Previsión de tesorería: saldo de hoy más cobros y pagos esperados por periodo.

	``vencidos`` decide qué hacer con lo que debía cobrarse o pagarse antes de hoy:
	``prudente`` lleva los pagos al primer periodo y deja fuera los cobros,
	``todos`` lleva ambos al primer periodo y ``ninguno`` los deja fuera.
	"""
	fecha = getdate(fecha)
	grano = "month" if grano == "month" else "week"
	numero = min(max(cint(numero) or 13, 1), 53 if grano == "week" else 24)
	periodos = tramos_prevision(fecha, numero, grano)
	horizonte = periodos[-1]["fin"]

	cuentas = saldos_tesoreria(company, fecha)
	saldo_inicial = round(sum(c["saldo"] for c in cuentas), 2)

	importes = {sentido: {fuente: [0.0] * numero for fuente in FUENTES} for sentido in ("cobros", "pagos")}
	if vencidos not in TRATAMIENTO_VENCIDOS:
		vencidos = "prudente"
	incluir_vencidos = TRATAMIENTO_VENCIDOS[vencidos]
	atrasado = {s: {f: 0.0 for f in FUENTES} for s in ("cobros", "pagos")}
	partidas: list[dict] = []

	def sumar(sentido: str, fuente: str, filas: list[dict]):
		for fila in filas:
			if fila["fecha"] < fecha:
				atrasado[sentido][fuente] += fila["importe"]
				if not incluir_vencidos[sentido]:
					continue
			i = indice_tramo(fila["fecha"], periodos)
			if i is None:
				continue
			importes[sentido][fuente][i] += fila["importe"]
			partidas.append(
				{
					"periodo": i,
					"sentido": sentido,
					"fuente": fuente,
					"fecha": str(fila["fecha"]),
					"vencida": fila["fecha"] < fecha,
					"importe": round(fila["importe"], 2),
					"doctype": fila["doctype"],
					"documento": fila["documento"],
					"tercero": fila["tercero"],
				}
			)

	sumar("cobros", "facturas", vencimientos(company, "cobrar", fecha, excluir_dudosos=excluir_dudosos))
	sumar("pagos", "facturas", vencimientos(company, "pagar", fecha))
	if incluir_pedidos:
		sumar("cobros", "pedidos", _pedidos(company, "Sales Order", horizonte))
		sumar("pagos", "pedidos", _pedidos(company, "Purchase Order", horizonte))

	historico = recurrentes(company, fecha, meses_historico) if incluir_recurrentes else None
	if historico:
		for i, periodo in enumerate(periodos):
			dias = (periodo["fin"] - periodo["inicio"]).days + 1
			factor = dias / 30.4375
			importes["cobros"]["recurrentes"][i] = historico["entradas_mes"] * factor
			importes["pagos"]["recurrentes"][i] = historico["salidas_mes"] * factor

	filas = []
	saldo = saldo_inicial
	minimo = {"saldo": saldo_inicial, "periodo": None}
	primer_negativo = None
	for i, periodo in enumerate(periodos):
		cobros = {f: round(importes["cobros"][f][i], 2) for f in FUENTES}
		pagos = {f: round(importes["pagos"][f][i], 2) for f in FUENTES}
		total_cobros = round(sum(cobros.values()), 2)
		total_pagos = round(sum(pagos.values()), 2)
		saldo_inicio = saldo
		saldo = round(saldo + total_cobros - total_pagos, 2)
		if saldo < minimo["saldo"]:
			minimo = {"saldo": saldo, "periodo": i}
		if saldo < 0 and primer_negativo is None:
			primer_negativo = i
		filas.append(
			{
				"inicio": str(periodo["inicio"]),
				"fin": str(periodo["fin"]),
				"label": periodo["label"],
				"saldo_inicial": saldo_inicio,
				"cobros": cobros,
				"pagos": pagos,
				"total_cobros": total_cobros,
				"total_pagos": total_pagos,
				"neto": round(total_cobros - total_pagos, 2),
				"saldo_final": saldo,
			}
		)

	partidas.sort(key=lambda p: (p["periodo"], -p["importe"]))
	return {
		"fecha": str(fecha),
		"grano": grano,
		"saldo_inicial": saldo_inicial,
		"cuentas": cuentas,
		"periodos": filas,
		"vencidos": {
			sentido: {
				**{f: round(v, 2) for f, v in por_fuente.items()},
				"total": round(sum(por_fuente.values()), 2),
				"incluidos": incluir_vencidos[sentido],
			}
			for sentido, por_fuente in atrasado.items()
		},
		"tratamiento_vencidos": vencidos,
		"minimo": minimo,
		"primer_negativo": primer_negativo,
		"recurrentes": historico,
		"partidas": partidas[:_MAX_PARTIDAS_PREVISION],
		"partidas_total": len(partidas),
	}
