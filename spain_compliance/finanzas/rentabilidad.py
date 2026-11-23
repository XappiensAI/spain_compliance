# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Rentabilidad por línea de producto, cliente, proyecto o centro de coste.

Dos lecturas complementarias:

- **Margen comercial**: ventas menos coste de lo vendido por artículo, grupo,
  marca, cliente… Usa el generador del informe *Gross Profit* de ERPNext, que
  toma el coste del libro de stock (o de la valoración si la venta no mueve stock).
- **Resultado analítico**: ingresos y gastos contabilizados (grupos 6 y 7) por
  proyecto, centro de coste o cualquier dimensión contable, ordenados con las
  líneas de la cuenta de pérdidas y ganancias. Incluye mano de obra y servicios,
  que no pasan por el stock.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import flt, getdate

from spain_compliance.contabilidad import cuentas_anuales as ca
from spain_compliance.contabilidad.pgc import normalizar_numero

_EPS = 0.005
AGRUPACIONES_COMERCIALES = {
	"item_group": ("Item Group", "Grupo de artículos"),
	"item_code": ("Item Code", "Artículo"),
	"brand": ("Brand", "Marca"),
	"customer_group": ("Customer Group", "Grupo de clientes"),
	"customer": ("Customer", "Cliente"),
	"territory": ("Territory", "Territorio"),
}
# Columnas del resultado analítico: línea (o líneas) de la PyG que suman en cada una.
COLUMNAS_ANALITICAS = (
	("cifra_negocios", "Cifra de negocios", ("1",)),
	("otros_ingresos", "Otros ingresos de explotación", ("2", "3", "5", "9", "10", "12")),
	("aprovisionamientos", "Aprovisionamientos", ("4",)),
	("personal", "Gastos de personal", ("6",)),
	("otros_gastos", "Otros gastos de explotación", ("7",)),
	("amortizacion", "Amortización", ("8",)),
	("otros_resultados", "Deterioros y otros resultados", ("11", "13")),
	("financiero", "Resultado financiero", ("14", "15", "16", "17", "18", "19")),
)
_LINEA_COLUMNA = {linea: clave for clave, _label, lineas in COLUMNAS_ANALITICAS for linea in lineas}


def dimensiones_analiticas() -> list[dict]:
	"""Proyecto, centro de coste y las dimensiones contables activas con columna en el GL."""
	dimensiones = [
		{"value": "project", "label": _("Proyecto"), "doctype": "Project"},
		{"value": "cost_center", "label": _("Centro de coste"), "doctype": "Cost Center"},
	]
	if frappe.db.exists("DocType", "Accounting Dimension"):
		for row in frappe.get_all(
			"Accounting Dimension", filters={"disabled": 0}, fields=["fieldname", "label", "document_type"]
		):
			if row.fieldname and frappe.db.has_column("GL Entry", row.fieldname):
				dimensiones.append(
					{
						"value": row.fieldname,
						"label": row.label or row.document_type,
						"doctype": row.document_type,
					}
				)
	return dimensiones


def agrupaciones() -> dict:
	return {
		"comercial": [{"value": k, "label": _(label)} for k, (_g, label) in AGRUPACIONES_COMERCIALES.items()],
		"analitica": dimensiones_analiticas(),
		"columnas": [{"key": k, "label": _(label)} for k, label, _l in COLUMNAS_ANALITICAS],
	}


def margen_comercial(company: str, desde, hasta, agrupar: str) -> dict:
	from erpnext.accounts.report.gross_profit.gross_profit import GrossProfitGenerator

	if agrupar not in AGRUPACIONES_COMERCIALES:
		frappe.throw(_("Agrupación no válida"))
	group_by = AGRUPACIONES_COMERCIALES[agrupar][0]
	filtros = frappe._dict(
		company=company,
		from_date=getdate(desde),
		to_date=getdate(hasta),
		group_by=group_by,
		currency=frappe.get_cached_value("Company", company, "default_currency"),
	)
	generador = GrossProfitGenerator(filtros)
	filas = []
	sin_coste = 0.0
	for row in generador.grouped_data:
		ventas = flt(row.base_amount)
		coste = flt(row.buying_amount)
		margen = ventas - coste
		if abs(coste) < _EPS and abs(ventas) >= _EPS:
			sin_coste += ventas
		clave = row.get(agrupar) or ""
		nombre = clave
		if agrupar == "item_code":
			nombre = row.get("item_name") or clave
		elif agrupar == "customer":
			nombre = row.get("customer_name") or clave
		filas.append(
			{
				"clave": clave,
				"nombre": nombre or _("Sin asignar"),
				"qty": round(flt(row.qty), 4),
				"ventas": round(ventas, 2),
				"coste": round(coste, 2),
				"margen": round(margen, 2),
				"margen_pct": round(margen / ventas, 4) if abs(ventas) >= _EPS else None,
			}
		)
	filas.sort(key=lambda f: -f["ventas"])
	ventas = sum(f["ventas"] for f in filas)
	coste = sum(f["coste"] for f in filas)
	return {
		"modo": "comercial",
		"agrupar": agrupar,
		"filas": filas,
		"total": {
			"ventas": round(ventas, 2),
			"coste": round(coste, 2),
			"margen": round(ventas - coste, 2),
			"margen_pct": round((ventas - coste) / ventas, 4) if abs(ventas) >= _EPS else None,
		},
		"ventas_sin_coste": round(sin_coste, 2),
	}


def _nombres_dimension(doctype: str, valores: set[str]) -> dict[str, str]:
	if not valores or not doctype or not frappe.db.exists("DocType", doctype):
		return {}
	meta = frappe.get_meta(doctype)
	campo = meta.title_field or next(
		(c for c in ("project_name", "cost_center_name") if meta.has_field(c)), None
	)
	if not campo or campo == "name":
		return {}
	return {
		row.name: row.get(campo) or row.name
		for row in frappe.get_all(doctype, filters={"name": ["in", list(valores)]}, fields=["name", campo])
	}


def resultado_analitico(company: str, desde, hasta, dimension: str) -> dict:
	dimensiones = {d["value"]: d for d in dimensiones_analiticas()}
	if dimension not in dimensiones:
		frappe.throw(_("Dimensión no válida"))
	finance_book = frappe.get_cached_value("Company", company, "default_finance_book") or ""
	g = frappe.qb.DocType("GL Entry")
	a = frappe.qb.DocType("Account")
	valor = IfNull(g[dimension], "")
	filas = (
		frappe.qb.from_(g)
		.inner_join(a)
		.on(a.name == g.account)
		.select(
			valor.as_("valor"),
			g.account,
			a.account_number,
			a.root_type,
			a.account_type,
			(Sum(g.credit) - Sum(g.debit)).as_("importe"),
		)
		.where(
			(g.company == company)
			& (g.posting_date[getdate(desde) : getdate(hasta)])
			& (g.is_cancelled == 0)
			& (g.voucher_type != "Period Closing Voucher")
			& (g.finance_book.isnull() | g.finance_book.isin(["", finance_book]))
			& (
				a.root_type.isin(["Income", "Expense"])
				| a.account_number.like("6%")
				| a.account_number.like("7%")
			)
		)
		.groupby(valor, g.account)
	).run(as_dict=True)
	claves = [k for k, _label, _lineas in COLUMNAS_ANALITICAS]
	por_valor: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(claves, 0.0))
	impuestos = 0.0
	for row in filas:
		numero = normalizar_numero(row.account_number)
		if not ca.es_pyg(numero, row.root_type):
			continue
		partida, _inferida = ca.partida_pyg(numero, row.root_type, row.account_type)
		linea = partida.split(".")[0]
		columna = _LINEA_COLUMNA.get(linea)
		if not columna:
			impuestos += flt(row.importe)
			continue
		por_valor[row.valor][columna] += flt(row.importe)

	nombres = _nombres_dimension(dimensiones[dimension]["doctype"], {v for v in por_valor if v})
	resultado = []
	for valor, columnas in por_valor.items():
		explotacion = sum(v for k, v in columnas.items() if k != "financiero")
		ingresos = columnas["cifra_negocios"] + columnas["otros_ingresos"]
		resultado.append(
			{
				"clave": valor,
				"nombre": nombres.get(valor, valor) if valor else _("Sin asignar"),
				**{k: round(v, 2) for k, v in columnas.items()},
				"resultado_explotacion": round(explotacion, 2),
				"resultado": round(explotacion + columnas["financiero"], 2),
				"margen_pct": round(explotacion / ingresos, 4) if abs(ingresos) >= _EPS else None,
			}
		)
	resultado.sort(key=lambda f: (f["clave"] == "", -f["cifra_negocios"], f["nombre"]))
	total = {
		k: round(sum(f[k] for f in resultado), 2) for k in (*claves, "resultado_explotacion", "resultado")
	}
	ingresos_total = total["cifra_negocios"] + total["otros_ingresos"]
	total["margen_pct"] = (
		round(total["resultado_explotacion"] / ingresos_total, 4) if abs(ingresos_total) >= _EPS else None
	)
	return {
		"modo": "analitica",
		"agrupar": dimension,
		"filas": resultado,
		"total": total,
		"impuestos": round(impuestos, 2),
		"sin_asignar": next((f for f in resultado if f["clave"] == ""), None),
	}
