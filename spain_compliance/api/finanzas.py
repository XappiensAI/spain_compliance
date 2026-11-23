# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Gestión financiera del portal /contabilidad: tesorería, flujos, costes e indicadores."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

from spain_compliance.api.informes import _compania, _ejercicio, _exigir_gl, _fechas, _moneda
from spain_compliance.contabilidad import cuentas_anuales as ca
from spain_compliance.finanzas import (
	costes_produccion,
	existencias,
	flujos_efectivo,
	indicadores,
	rentabilidad,
)
from spain_compliance.finanzas import tesoreria as tes


def _exigir(doctype: str, mensaje: str):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(mensaje, frappe.PermissionError)


def _base(company: str) -> dict:
	return {"company": company, "currency": _moneda(company)}


def _inicio_ejercicio(company: str, fecha):
	try:
		return _ejercicio(company, fecha)[1]
	except frappe.ValidationError:
		return getdate(fecha).replace(month=1, day=1)


@frappe.whitelist()
def estado_flujos_efectivo(company: str, from_date: str, to_date: str, comparar: int | str = 1) -> dict:
	"""Estado de flujos de efectivo del modelo normal (método indirecto)."""
	company = _compania(company)
	_exigir_gl(_("No tiene permiso para ver el estado de flujos de efectivo"))
	inicio, fin = _fechas(from_date, to_date)
	periodos = [(inicio, fin)]
	if cint(comparar):
		periodos.append(ca.periodo_anterior(inicio, fin))
	resultado = flujos_efectivo.calcular(company, periodos)
	return {
		**_base(company),
		"from_date": str(inicio),
		"to_date": str(fin),
		"periodos": [{"desde": str(d), "hasta": str(h), "label": _etiqueta(d, h)} for d, h in periodos],
		**resultado,
	}


def _etiqueta(desde, hasta) -> str:
	from spain_compliance.api.informes import _etiqueta_periodo

	return _etiqueta_periodo(desde, hasta)


@frappe.whitelist()
def cuentas_a_cobrar(company: str, to_date: str | None = None, rangos: str | None = None) -> dict:
	"""Facturas de clientes pendientes con su antigüedad."""
	company = _compania(company)
	_exigir("Sales Invoice", _("No tiene permiso para ver las cuentas a cobrar"))
	fecha = getdate(to_date or today())
	return {**_base(company), **tes.antiguedad(company, "cobrar", fecha, rangos)}


@frappe.whitelist()
def cuentas_a_pagar(
	company: str, to_date: str | None = None, rangos: str | None = None, semanas: int | str = 13
) -> dict:
	"""Facturas de proveedores pendientes: antigüedad, calendario de pagos y periodo medio de pago."""
	company = _compania(company)
	_exigir("Purchase Invoice", _("No tiene permiso para ver las cuentas a pagar"))
	fecha = getdate(to_date or today())
	datos = tes.antiguedad(company, "pagar", fecha, rangos)

	semanas = min(max(cint(semanas) or 13, 1), 53)
	periodos = tes.tramos_prevision(fecha, semanas, "week")
	calendario = [
		{"inicio": str(p["inicio"]), "fin": str(p["fin"]), "label": p["label"], "importe": 0.0, "plazos": 0}
		for p in periodos
	]
	vencido = {"importe": 0.0, "plazos": 0}
	posterior = {"importe": 0.0, "plazos": 0}
	plazos = []
	for fila in tes.vencimientos(company, "pagar", fecha):
		if fila["fecha"] < fecha:
			destino = vencido
		else:
			i = tes.indice_tramo(fila["fecha"], periodos)
			destino = calendario[i] if i is not None else posterior
		destino["importe"] += fila["importe"]
		destino["plazos"] += 1
		plazos.append({**fila, "fecha": str(fila["fecha"]), "importe": round(fila["importe"], 2)})
	for destino in (*calendario, vencido, posterior):
		destino["importe"] = round(destino["importe"], 2)
	plazos.sort(key=lambda p: (p["fecha"], -p["importe"]))

	return {
		**_base(company),
		**datos,
		"calendario": calendario,
		"vencido": vencido,
		"posterior": posterior,
		"plazos": plazos[:1000],
		"pmp": tes.periodo_medio_pago(company, _inicio_ejercicio(company, fecha), fecha),
	}


@frappe.whitelist()
def prevision_tesoreria(
	company: str,
	grano: str = "week",
	periodos: int | str = 13,
	incluir_pedidos: int | str = 1,
	incluir_recurrentes: int | str = 1,
	meses_historico: int | str = 3,
	vencidos: str = "prudente",
	excluir_dudosos: int | str = 1,
) -> dict:
	"""Previsión de cobros, pagos y saldo de tesorería desde hoy."""
	company = _compania(company)
	_exigir_gl(_("No tiene permiso para ver la previsión de tesorería"))
	_exigir("Sales Invoice", _("No tiene permiso para ver las facturas de venta"))
	_exigir("Purchase Invoice", _("No tiene permiso para ver las facturas de compra"))
	return {
		**_base(company),
		**tes.prevision(
			company,
			today(),
			numero=cint(periodos),
			grano=grano,
			incluir_pedidos=bool(cint(incluir_pedidos)),
			incluir_recurrentes=bool(cint(incluir_recurrentes)),
			meses_historico=cint(meses_historico) or 3,
			vencidos=vencidos,
			excluir_dudosos=bool(cint(excluir_dudosos)),
		),
	}


@frappe.whitelist()
def costes_de_produccion(company: str, from_date: str, to_date: str, item_code: str | None = None) -> dict:
	"""Coste estándar y real de las órdenes de fabricación y sus desviaciones."""
	company = _compania(company)
	_exigir("Work Order", _("No tiene permiso para ver las órdenes de fabricación"))
	inicio, fin = _fechas(from_date, to_date)
	return {
		**_base(company),
		"from_date": str(inicio),
		"to_date": str(fin),
		**costes_produccion.calcular(company, inicio, fin, item_code or None),
	}


@frappe.whitelist()
def valoracion_existencias(
	company: str, to_date: str | None = None, dias_sin_salida: int | str = 180
) -> dict:
	"""Existencias valoradas a una fecha por clase del PGC, almacén y artículo."""
	company = _compania(company)
	_exigir("Stock Ledger Entry", _("No tiene permiso para ver el libro de stock"))
	fecha = getdate(to_date or today())
	return {
		**_base(company),
		**existencias.valorar(company, fecha, cint(dias_sin_salida) or existencias.DIAS_SIN_SALIDA),
	}


@frappe.whitelist()
def opciones_rentabilidad() -> dict:
	from spain_compliance.api.informes import _exigir_acceso

	_exigir_acceso()
	return rentabilidad.agrupaciones()


@frappe.whitelist()
def rentabilidad_por_linea(
	company: str, from_date: str, to_date: str, modo: str = "comercial", agrupar: str = "item_group"
) -> dict:
	"""Margen comercial por artículo, cliente… o resultado analítico por proyecto, centro de coste…"""
	company = _compania(company)
	inicio, fin = _fechas(from_date, to_date)
	if modo == "analitica":
		_exigir_gl(_("No tiene permiso para ver el resultado analítico"))
		datos = rentabilidad.resultado_analitico(company, inicio, fin, agrupar)
	else:
		_exigir("Sales Invoice", _("No tiene permiso para ver las facturas de venta"))
		datos = rentabilidad.margen_comercial(company, inicio, fin, agrupar)
	return {**_base(company), "from_date": str(inicio), "to_date": str(fin), **datos}


@frappe.whitelist()
def indicadores_gestion(company: str, from_date: str, to_date: str, comparar: int | str = 1) -> dict:
	"""EBITDA, márgenes, liquidez, solvencia, ciclo de caja e ingreso por empleado."""
	company = _compania(company)
	_exigir_gl(_("No tiene permiso para ver los indicadores"))
	inicio, fin = _fechas(from_date, to_date)
	datos = indicadores.calcular(company, inicio, fin, bool(cint(comparar)))
	for periodo in datos["periodos"]:
		periodo["label"] = _etiqueta(periodo["desde"], periodo["hasta"])
	tesoreria = tes.saldos_tesoreria(company, min(fin, getdate(today())))
	return {
		**_base(company),
		"from_date": str(inicio),
		"to_date": str(fin),
		**datos,
		"tesoreria": round(sum(c["saldo"] for c in tesoreria), 2),
		"tesoreria_fecha": str(min(fin, getdate(today()))),
		"pmp": tes.periodo_medio_pago(company, inicio, fin),
	}
