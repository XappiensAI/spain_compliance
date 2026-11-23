# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Indicadores de gestión: márgenes, liquidez, solvencia, ciclo de caja y productividad.

Todo sale de la PyG y el balance del PGC que ya calcula la app, salvo la
facturación con IVA (para los periodos medios de cobro y pago) y la plantilla
media, que es un recuento de empleados sin ningún otro dato personal.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, cint, date_diff, flt, get_first_day, get_last_day, getdate

from spain_compliance.contabilidad import cuentas_anuales as ca

_EPS = 0.005
CAMPO_PLANTILLA = "plantilla_media"


def _division(a, b):
	if a is None or b is None or abs(flt(b)) < _EPS:
		return None
	return round(flt(a) / flt(b), 4)


def plantilla_media(company: str, desde, hasta) -> dict:
	"""Media de empleados en alta al cierre de cada mes del periodo.

	El valor manual de la compañía (``plantilla_media``) tiene prioridad.
	"""
	manual = 0.0
	if frappe.get_meta("Company").has_field(CAMPO_PLANTILLA):
		manual = flt(frappe.get_cached_value("Company", company, CAMPO_PLANTILLA))
	if manual > 0:
		return {"valor": manual, "origen": "manual"}
	desde, hasta = getdate(desde), getdate(hasta)
	meses = []
	actual = getdate(get_first_day(desde))
	while actual <= hasta:
		meses.append(min(getdate(get_last_day(actual)), hasta))
		actual = getdate(add_months(actual, 1))
	if not meses or not frappe.db.exists("DocType", "Employee"):
		return {"valor": None, "origen": "empleados"}
	recuentos = []
	for cierre in meses:
		recuentos.append(
			cint(
				frappe.db.sql(
					"""
					SELECT COUNT(*) FROM `tabEmployee`
					WHERE company = %(company)s AND date_of_joining <= %(cierre)s
						AND (relieving_date IS NULL OR relieving_date >= %(cierre)s)
					""",
					{"company": company, "cierre": cierre},
				)[0][0]
			)
		)
	media = sum(recuentos) / len(recuentos)
	return {"valor": round(media, 1) if media else None, "origen": "empleados"}


def _facturado(doctype: str, company: str, desde, hasta) -> float:
	t = frappe.qb.DocType(doctype)
	return flt(
		frappe.qb.from_(t)
		.select(Sum(t.base_grand_total))
		.where(
			(t.company == company) & (t.docstatus == 1) & (t.posting_date[getdate(desde) : getdate(hasta)])
		)
		.run()[0][0]
	)


def _valores_balance(fecha, company) -> tuple[dict[str, float], dict]:
	periodo = ca.calcular_balance(company, fecha)
	activo = ca.construir_arbol(ca.ACTIVO, [periodo])
	pasivo = ca.construir_arbol(ca.PATRIMONIO_PASIVO, [periodo])
	valores: dict[str, float] = {}

	def visitar(nodo):
		valores[nodo["code"]] = nodo["importes"][0]
		for hijo in nodo["hijos"]:
			visitar(hijo)

	visitar(activo)
	visitar(pasivo)
	return valores, ca.masas_balance(activo, pasivo)[0]


def calcular_periodo(company: str, desde, hasta) -> dict:
	desde, hasta = getdate(desde), getdate(hasta)
	dias = date_diff(hasta, desde) + 1
	anualizar = 365 / dias if dias > 0 else 1

	pyg, mensual = ca.calcular_pyg(company, desde, hasta)
	lineas = ca.lineas_pyg([pyg])
	kpis = ca.kpis_pyg(lineas, 0)
	linea = {nodo["code"]: nodo["importes"][0] for nodo in lineas}
	balance, masas = _valores_balance(hasta, company)
	ratios = ca.ratios_balance(masas)
	plantilla = plantilla_media(company, desde, hasta)

	cifra = kpis["cifra_negocios"]
	ventas_iva = _facturado("Sales Invoice", company, desde, hasta)
	compras_iva = _facturado("Purchase Invoice", company, desde, hasta)
	clientes = balance.get("B.III.1", 0.0) + balance.get("B.III.2", 0.0)
	proveedores = balance.get("PC.V.1", 0.0) + balance.get("PC.V.2", 0.0) + balance.get("PC.V.3", 0.0)
	consumos = -linea.get("4", 0.0)
	existencias = masas["existencias"]

	dso = _division(clientes * dias, ventas_iva)
	dpo = _division(proveedores * dias, compras_iva)
	dio = _division(existencias * dias, consumos) if consumos > _EPS else None
	ciclo = None
	if dso is not None and dpo is not None:
		ciclo = round(dso + (dio or 0) - dpo, 1)

	empleados = plantilla["valor"]
	meses = ca.meses_entre(desde, hasta)
	series = ca.totales_pyg_mensuales(mensual, meses)
	ebitda_mensual = [
		round(a - b - c, 2) for a, b, c in zip(series["A.1"], series["8"], series["11"], strict=True)
	]
	return {
		"desde": str(desde),
		"hasta": str(hasta),
		"dias": dias,
		"cifra_negocios": cifra,
		"ebitda": kpis["ebitda"],
		"resultado_explotacion": kpis["resultado_explotacion"],
		"resultado": kpis["resultado"],
		"gastos_personal": round(-linea.get("6", 0.0), 2),
		"margen_bruto": kpis["margen_bruto"],
		"margen_bruto_pct": _division(kpis["margen_bruto"], cifra),
		"margen_ebitda": _division(kpis["ebitda"], cifra),
		"margen_operativo": _division(kpis["resultado_explotacion"], cifra),
		"margen_neto": _division(kpis["resultado"], cifra),
		"peso_personal": _division(-linea.get("6", 0.0), cifra),
		"liquidez": ratios["liquidez"],
		"acida": ratios["acida"],
		"disponibilidad": ratios["disponibilidad"],
		"fondo_maniobra": ratios["fondo_maniobra"],
		"endeudamiento": ratios["endeudamiento"],
		"solvencia": ratios["solvencia"],
		"roa": _division(kpis["resultado_explotacion"] * anualizar, masas["activo"]),
		"roe": _division(kpis["resultado"] * anualizar, masas["pn"]),
		"dso": round(dso, 1) if dso is not None else None,
		"dpo": round(dpo, 1) if dpo is not None else None,
		"dio": round(dio, 1) if dio is not None else None,
		"ciclo_caja": ciclo,
		"plantilla": empleados,
		"plantilla_origen": plantilla["origen"],
		"ingreso_por_empleado": round(cifra / empleados, 2) if empleados else None,
		"ingreso_por_empleado_anual": round(cifra * anualizar / empleados, 2) if empleados else None,
		"ebitda_por_empleado": round(kpis["ebitda"] / empleados, 2) if empleados else None,
		"meses": meses,
		"serie_cifra": series["1"],
		"serie_ebitda": ebitda_mensual,
		"serie_explotacion": series["A.1"],
		"masas": masas,
	}


def calcular(company: str, desde, hasta, comparar: bool = True) -> dict:
	periodos = [(desde, hasta)]
	if comparar:
		periodos.append(ca.periodo_anterior(desde, hasta))
	return {"periodos": [calcular_periodo(company, d, h) for d, h in periodos]}
