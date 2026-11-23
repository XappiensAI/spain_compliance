# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Valoración de existencias a una fecha por clase del PGC (subgrupos 30 a 36).

El valor sale del libro de stock (suma de ``stock_value_difference``), que es la
misma valoración que contabiliza ERPNext con inventario permanente. La clase de
cada artículo y almacén se decide, por este orden:

1. Clase indicada en el almacén (campo ``clase_existencias``).
2. Almacén de trabajo en curso de fabricación → productos en curso.
3. Clase indicada en el grupo de artículos o en alguno de sus padres.
4. Cuenta de existencias del almacén, si es de los subgrupos 31 a 36.
5. Uso del artículo en listas de materiales: se fabrica y además es componente
   → semiterminado; solo se fabrica → terminado; solo es componente → materia
   prima. En otro caso, mercaderías.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from spain_compliance.contabilidad.pgc import normalizar_numero

_EPS = 0.005
MERCADERIAS = "Mercaderías"
MATERIAS_PRIMAS = "Materias primas"
OTROS_APROVISIONAMIENTOS = "Otros aprovisionamientos"
EN_CURSO = "Productos en curso"
SEMITERMINADOS = "Productos semiterminados"
TERMINADOS = "Productos terminados"
SUBPRODUCTOS = "Subproductos, residuos y materiales recuperados"
CLASES = (
	MERCADERIAS,
	MATERIAS_PRIMAS,
	OTROS_APROVISIONAMIENTOS,
	EN_CURSO,
	SEMITERMINADOS,
	TERMINADOS,
	SUBPRODUCTOS,
)
CLASE_OPTIONS = "\n" + "\n".join(CLASES)
SUBGRUPO_CLASE = {
	"30": MERCADERIAS,
	"31": MATERIAS_PRIMAS,
	"32": OTROS_APROVISIONAMIENTOS,
	"33": EN_CURSO,
	"34": SEMITERMINADOS,
	"35": TERMINADOS,
	"36": SUBPRODUCTOS,
}
DIAS_SIN_SALIDA = 180
_MAX_ARTICULOS = 1000


def _tiene_campo(doctype: str, campo: str) -> bool:
	return frappe.get_meta(doctype).has_field(campo)


def almacenes_en_curso(company: str) -> set[str]:
	almacenes = set()
	# ERPNext 16 lo guarda en la compañía; versiones anteriores, en Manufacturing Settings.
	if _tiene_campo("Company", "default_wip_warehouse"):
		por_defecto = frappe.get_cached_value("Company", company, "default_wip_warehouse")
	elif _tiene_campo("Manufacturing Settings", "default_wip_warehouse"):
		por_defecto = frappe.db.get_single_value("Manufacturing Settings", "default_wip_warehouse")
	else:
		por_defecto = None
	if por_defecto:
		almacenes.add(por_defecto)
	for row in frappe.db.sql(
		"""
		SELECT DISTINCT wip_warehouse FROM `tabWork Order`
		WHERE company = %(company)s AND docstatus < 2 AND IFNULL(wip_warehouse, '') != ''
		""",
		{"company": company},
	):
		almacenes.add(row[0])
	return almacenes


def _uso_en_listas() -> tuple[set[str], set[str]]:
	fabricados = set(
		frappe.get_all("BOM", filters={"is_active": 1, "docstatus": 1}, pluck="item", distinct=True)
	)
	componentes = {
		row[0]
		for row in frappe.db.sql(
			"""
			SELECT DISTINCT bi.item_code FROM `tabBOM Item` bi
			INNER JOIN `tabBOM` b ON b.name = bi.parent
			WHERE b.is_active = 1 AND b.docstatus = 1
			"""
		)
	}
	return fabricados, componentes


def _clase_grupos() -> dict[str, str]:
	"""Clase de cada grupo de artículos, heredada del padre más cercano que la tenga."""
	if not _tiene_campo("Item Group", "clase_existencias"):
		return {}
	grupos = {
		row.name: row
		for row in frappe.get_all("Item Group", fields=["name", "parent_item_group", "clase_existencias"])
	}
	resultado: dict[str, str] = {}

	def buscar(nombre, visitados=()):
		if nombre in resultado:
			return resultado[nombre]
		grupo = grupos.get(nombre)
		if not grupo or nombre in visitados:
			return ""
		clase = grupo.clase_existencias or buscar(grupo.parent_item_group, (*visitados, nombre))
		resultado[nombre] = clase
		return clase

	for nombre in grupos:
		buscar(nombre)
	return {k: v for k, v in resultado.items() if v}


def _almacenes(company: str) -> dict[str, dict]:
	campos = ["name", "warehouse_name", "account", "parent_warehouse", "is_group"]
	if _tiene_campo("Warehouse", "clase_existencias"):
		campos.append("clase_existencias")
	almacenes = {
		row.name: row for row in frappe.get_all("Warehouse", filters={"company": company}, fields=campos)
	}
	por_defecto = frappe.get_cached_value("Company", company, "default_inventory_account")

	def cuenta(nombre, visitados=()):
		almacen = almacenes.get(nombre)
		if not almacen or nombre in visitados:
			return por_defecto
		return almacen.account or cuenta(almacen.parent_warehouse, (*visitados, nombre))

	numeros = {
		row.name: normalizar_numero(row.account_number)
		for row in frappe.get_all("Account", filters={"company": company}, fields=["name", "account_number"])
	}
	for nombre, almacen in almacenes.items():
		almacen["cuenta"] = cuenta(nombre)
		almacen["numero_cuenta"] = numeros.get(almacen["cuenta"], "")
	return almacenes


def clasificar(
	item_code: str,
	item_group: str,
	almacen: dict | None,
	en_curso: set[str],
	clase_grupos: dict[str, str],
	fabricados: set[str],
	componentes: set[str],
) -> tuple[str, str]:
	"""Clase de existencias y motivo de la clasificación."""
	if almacen and almacen.get("clase_existencias"):
		return almacen["clase_existencias"], _("almacén")
	if almacen and almacen.get("name") in en_curso:
		return EN_CURSO, _("almacén de trabajo en curso")
	if clase_grupos.get(item_group):
		return clase_grupos[item_group], _("grupo de artículos")
	numero = (almacen or {}).get("numero_cuenta") or ""
	if numero[:2] in SUBGRUPO_CLASE and numero[:2] != "30":
		return SUBGRUPO_CLASE[numero[:2]], _("cuenta {0}").format(numero)
	if item_code in fabricados:
		return (SEMITERMINADOS if item_code in componentes else TERMINADOS), _("lista de materiales")
	if item_code in componentes:
		return MATERIAS_PRIMAS, _("lista de materiales")
	return MERCADERIAS, _("por defecto")


def _saldo_contable(company: str, cuentas: set[str], fecha) -> float | None:
	if not cuentas:
		return None
	return flt(
		frappe.db.sql(
			"""
			SELECT SUM(debit) - SUM(credit) FROM `tabGL Entry`
			WHERE company = %(company)s AND account IN %(cuentas)s
				AND posting_date <= %(fecha)s AND is_cancelled = 0
			""",
			{"company": company, "cuentas": list(cuentas), "fecha": getdate(fecha)},
		)[0][0]
	)


def valorar(company: str, fecha, dias_sin_salida: int = DIAS_SIN_SALIDA) -> dict:
	fecha = getdate(fecha)
	filas = frappe.db.sql(
		"""
		SELECT sle.item_code, sle.warehouse, SUM(sle.actual_qty) AS qty,
			SUM(sle.stock_value_difference) AS valor,
			MAX(sle.posting_date) AS ultimo_movimiento,
			MAX(CASE WHEN sle.actual_qty < 0 THEN sle.posting_date END) AS ultima_salida
		FROM `tabStock Ledger Entry` sle
		WHERE sle.company = %(company)s AND sle.is_cancelled = 0 AND sle.posting_date <= %(fecha)s
		GROUP BY sle.item_code, sle.warehouse
		HAVING ABS(SUM(sle.actual_qty)) > 0.000001 OR ABS(SUM(sle.stock_value_difference)) > 0.005
		""",
		{"company": company, "fecha": fecha},
		as_dict=True,
	)
	codigos = list({f.item_code for f in filas})
	articulos = (
		{
			row.name: row
			for row in frappe.get_all(
				"Item",
				filters={"name": ["in", codigos]},
				fields=["name", "item_name", "item_group", "stock_uom"],
			)
		}
		if codigos
		else {}
	)
	almacenes = _almacenes(company)
	en_curso = almacenes_en_curso(company)
	clase_grupos = _clase_grupos()
	fabricados, componentes = _uso_en_listas()

	por_clase: dict[str, dict] = {clase: {"clase": clase, "valor": 0.0, "articulos": 0} for clase in CLASES}
	por_almacen: dict[str, dict] = {}
	detalle = []
	sin_salida = {"valor": 0.0, "articulos": 0}
	negativos = 0
	for f in filas:
		articulo = articulos.get(f.item_code) or frappe._dict(
			item_name=f.item_code, item_group="", stock_uom=""
		)
		almacen = almacenes.get(f.warehouse)
		clase, motivo = clasificar(
			f.item_code, articulo.item_group, almacen, en_curso, clase_grupos, fabricados, componentes
		)
		valor = flt(f.valor)
		qty = flt(f.qty)
		referencia = f.ultima_salida or f.ultimo_movimiento
		dias = date_diff(fecha, referencia) if referencia else None
		lento = dias is not None and dias > dias_sin_salida and valor > _EPS
		if qty < 0:
			negativos += 1
		por_clase[clase]["valor"] += valor
		por_clase[clase]["articulos"] += 1
		destino = por_almacen.setdefault(
			f.warehouse,
			{
				"warehouse": f.warehouse,
				"nombre": (almacen or {}).get("warehouse_name") or f.warehouse,
				"cuenta": (almacen or {}).get("numero_cuenta") or "",
				"valor": 0.0,
				"articulos": 0,
			},
		)
		destino["valor"] += valor
		destino["articulos"] += 1
		if lento:
			sin_salida["valor"] += valor
			sin_salida["articulos"] += 1
		detalle.append(
			{
				"item_code": f.item_code,
				"item_name": articulo.item_name,
				"item_group": articulo.item_group,
				"uom": articulo.stock_uom,
				"warehouse": f.warehouse,
				"clase": clase,
				"motivo": motivo,
				"qty": round(qty, 4),
				"valor": round(valor, 2),
				"precio_medio": round(valor / qty, 4) if abs(qty) > 1e-6 else None,
				"ultima_salida": str(f.ultima_salida) if f.ultima_salida else "",
				"dias_sin_salida": dias,
				"lento": lento,
			}
		)

	total = sum(c["valor"] for c in por_clase.values())
	cuentas_stock = {a["cuenta"] for a in almacenes.values() if a.get("cuenta")}
	perpetuo = bool(frappe.get_cached_value("Company", company, "enable_perpetual_inventory"))
	contable = _saldo_contable(company, cuentas_stock, fecha) if perpetuo else None
	detalle.sort(key=lambda d: -abs(d["valor"]))
	return {
		"fecha": str(fecha),
		"total": round(total, 2),
		"clases": [
			{**c, "valor": round(c["valor"], 2)} for c in por_clase.values() if c["articulos"] or c["valor"]
		],
		"almacenes": sorted(
			({**a, "valor": round(a["valor"], 2)} for a in por_almacen.values()), key=lambda a: -a["valor"]
		),
		"articulos": detalle[:_MAX_ARTICULOS],
		"articulos_total": len(detalle),
		"sin_salida": {**sin_salida, "valor": round(sin_salida["valor"], 2), "dias": dias_sin_salida},
		"negativos": negativos,
		"contable": round(contable, 2) if contable is not None else None,
		"diferencia_contable": round(total - contable, 2) if contable is not None else None,
		"cuentas_stock": sorted(cuentas_stock),
	}
