# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Coste de producción por orden de fabricación: estándar frente a real.

- **Estándar** (planificado): materiales y coste de operación que la orden copió
  de la lista de materiales al crearse, escalados a la cantidad producida.
- **Real**: lo que registraron las entradas de stock de fabricación y de consumo
  de la orden (materiales a valor de stock y costes adicionales).

El coste de operación se reparte entre mano de obra (MO) y costes indirectos de
fabricación (CIF) con la naturaleza de cada componente de coste del puesto de
trabajo (campo ``naturaleza_coste`` de *Workstation Operating Component*). Si un
componente no la tiene, se deduce de su nombre.
"""

from __future__ import annotations

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

_EPS = 0.005
NATURALEZA_MO = "Mano de obra"
NATURALEZA_CIF = "Costes indirectos"
NATURALEZA_OPTIONS = f"\n{NATURALEZA_MO}\n{NATURALEZA_CIF}"
_PATRON_MO = re.compile(
	r"wage|labou?r|mano de obra|\bm\.?o\.?\b|salari|sueldo|personal|operari|n[oó]mina|man ?power",
	re.IGNORECASE,
)
PROPOSITOS_REALES = ("Manufacture", "Material Consumption for Manufacture")
_MAX_ORDENES = 2000


def naturaleza_por_nombre(nombre: str | None) -> str:
	return NATURALEZA_MO if nombre and _PATRON_MO.search(nombre) else NATURALEZA_CIF


def naturalezas_componentes() -> dict[str, str]:
	"""Naturaleza (MO o CIF) de cada componente de coste de puesto de trabajo."""
	if not frappe.db.exists("DocType", "Workstation Operating Component"):
		return {}
	campos = ["name"]
	if frappe.get_meta("Workstation Operating Component").has_field("naturaleza_coste"):
		campos.append("naturaleza_coste")
	return {
		row.name: row.get("naturaleza_coste") or naturaleza_por_nombre(row.name)
		for row in frappe.get_all("Workstation Operating Component", fields=campos)
	}


def reparto_puestos(puestos: set[str], naturalezas: dict[str, str]) -> dict[str, float]:
	"""Proporción de mano de obra en el coste por hora de cada puesto.

	Un puesto sin componentes no desglosa su tarifa: se trata como CIF.
	"""
	if not puestos:
		return {}
	por_puesto: dict[str, dict[str, float]] = defaultdict(lambda: {"mo": 0.0, "total": 0.0})
	if frappe.db.exists("DocType", "Workstation Cost"):
		for row in frappe.get_all(
			"Workstation Cost",
			filters={"parenttype": "Workstation", "parent": ["in", list(puestos)]},
			fields=["parent", "operating_component", "operating_cost"],
		):
			coste = flt(row.operating_cost)
			por_puesto[row.parent]["total"] += coste
			if naturalezas.get(row.operating_component) == NATURALEZA_MO:
				por_puesto[row.parent]["mo"] += coste
	return {
		puesto: (valores["mo"] / valores["total"] if valores["total"] > _EPS else 0.0)
		for puesto, valores in por_puesto.items()
	}


def _vacio() -> dict[str, float]:
	return {"mp": 0.0, "mo": 0.0, "cif": 0.0, "subproductos": 0.0, "total": 0.0}


def _cerrar(costes: dict[str, float], cantidad: float) -> dict[str, float]:
	costes["total"] = costes["mp"] + costes["mo"] + costes["cif"] - costes["subproductos"]
	salida = {k: round(v, 2) for k, v in costes.items()}
	salida["unitario"] = round(costes["total"] / cantidad, 4) if cantidad > _EPS else None
	return salida


def _ordenes(company: str, desde, hasta, item_code: str | None) -> list[dict]:
	"""Órdenes validadas que empiezan en el periodo o tienen fabricación real en él."""
	return frappe.db.sql(
		"""
		SELECT wo.name, wo.production_item, wo.item_name, wo.bom_no, wo.status, wo.qty,
			wo.produced_qty, wo.planned_start_date, wo.actual_end_date, wo.planned_operating_cost,
			wo.additional_operating_cost, wo.project, wo.stock_uom
		FROM `tabWork Order` wo
		WHERE wo.company = %(company)s AND wo.docstatus = 1
			AND (%(item)s = '' OR wo.production_item = %(item)s)
			AND (
				DATE(wo.planned_start_date) BETWEEN %(desde)s AND %(hasta)s
				OR EXISTS (
					SELECT 1 FROM `tabStock Entry` se
					WHERE se.work_order = wo.name AND se.docstatus = 1
						AND se.purpose IN %(propositos)s
						AND se.posting_date BETWEEN %(desde)s AND %(hasta)s
				)
			)
		ORDER BY wo.planned_start_date DESC
		LIMIT %(limite)s
		""",
		{
			"company": company,
			"desde": getdate(desde),
			"hasta": getdate(hasta),
			"item": item_code or "",
			"propositos": PROPOSITOS_REALES,
			"limite": _MAX_ORDENES,
		},
		as_dict=True,
	)


def _por_orden(doctype: str, ordenes: list[str], campos: list[str], parent_field="parent") -> dict[str, list]:
	agrupado: dict[str, list] = defaultdict(list)
	if not ordenes:
		return agrupado
	for row in frappe.get_all(
		doctype,
		filters={"parenttype": "Work Order", parent_field: ["in", ordenes]},
		fields=[parent_field, *campos],
		limit_page_length=0,
	):
		agrupado[row.get(parent_field)].append(row)
	return agrupado


def _reales(ordenes: list[str]) -> tuple[dict, dict, dict]:
	"""Detalle de materiales, productos y costes adicionales de las entradas de cada orden."""
	if not ordenes:
		return {}, {}, {}
	entradas = frappe.get_all(
		"Stock Entry",
		filters={"work_order": ["in", ordenes], "docstatus": 1, "purpose": ["in", PROPOSITOS_REALES]},
		fields=["name", "work_order"],
		limit_page_length=0,
	)
	orden_de = {e.name: e.work_order for e in entradas}
	materiales: dict[str, dict[str, dict]] = defaultdict(dict)
	productos: dict[str, dict[str, float]] = defaultdict(
		lambda: {"qty": 0.0, "valor": 0.0, "subproductos": 0.0}
	)
	adicionales: dict[str, list] = defaultdict(list)
	if not orden_de:
		return materiales, productos, adicionales

	campos_detalle = [
		"parent",
		"item_code",
		"item_name",
		"s_warehouse",
		"t_warehouse",
		"transfer_qty",
		"basic_amount",
		"amount",
		"is_finished_item",
	]
	tiene_secundario = frappe.get_meta("Stock Entry Detail").has_field("secondary_item_type")
	tiene_scrap = frappe.get_meta("Stock Entry Detail").has_field("is_scrap_item")
	if tiene_secundario:
		campos_detalle.append("secondary_item_type")
	if tiene_scrap:
		campos_detalle.append("is_scrap_item")
	for row in frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ["in", list(orden_de)], "parenttype": "Stock Entry"},
		fields=campos_detalle,
		limit_page_length=0,
	):
		orden = orden_de[row.parent]
		secundario = (tiene_secundario and row.get("secondary_item_type")) or (
			tiene_scrap and row.get("is_scrap_item")
		)
		if row.t_warehouse and secundario:
			productos[orden]["subproductos"] += flt(row.amount)
		elif row.t_warehouse and row.is_finished_item:
			productos[orden]["qty"] += flt(row.transfer_qty)
			productos[orden]["valor"] += flt(row.amount)
		elif row.s_warehouse:
			material = materiales[orden].setdefault(
				row.item_code,
				{"item_code": row.item_code, "item_name": row.item_name, "qty": 0.0, "importe": 0.0},
			)
			material["qty"] += flt(row.transfer_qty)
			material["importe"] += flt(row.basic_amount)

	campos_coste = ["parent", "base_amount", "description", "expense_account"]
	meta_coste = frappe.get_meta("Landed Cost Taxes and Charges")
	for campo in ("operating_component", "has_operating_cost", "has_corrective_cost"):
		if meta_coste.has_field(campo):
			campos_coste.append(campo)
	for row in frappe.get_all(
		"Landed Cost Taxes and Charges",
		filters={"parent": ["in", list(orden_de)], "parenttype": "Stock Entry"},
		fields=campos_coste,
		limit_page_length=0,
	):
		adicionales[orden_de[row.parent]].append(row)
	return materiales, productos, adicionales


def calcular(company: str, desde, hasta, item_code: str | None = None) -> dict:
	ordenes = _ordenes(company, desde, hasta, item_code)
	nombres = [o.name for o in ordenes]
	items_orden = _por_orden(
		"Work Order Item",
		nombres,
		["item_code", "item_name", "required_qty", "rate", "amount", "consumed_qty"],
	)
	operaciones = _por_orden(
		"Work Order Operation",
		nombres,
		[
			"workstation",
			"planned_operating_cost",
			"actual_operating_cost",
			"time_in_mins",
			"actual_operation_time",
		],
	)
	naturalezas = naturalezas_componentes()
	puestos = {op.workstation for ops in operaciones.values() for op in ops if op.workstation}
	parte_mo = reparto_puestos(puestos, naturalezas)
	materiales, productos, adicionales = _reales(nombres)
	boms = (
		{
			b.name: b
			for b in frappe.get_all(
				"BOM",
				filters={"name": ["in", list({o.bom_no for o in ordenes if o.bom_no})]},
				fields=["name", "quantity", "base_raw_material_cost", "base_operating_cost"],
			)
		}
		if ordenes
		else {}
	)

	avisos: set[str] = set()
	filas = []
	for orden in ordenes:
		qty = flt(orden.qty)
		producido = flt(productos.get(orden.name, {}).get("qty")) or flt(orden.produced_qty)
		base = producido if producido > _EPS else qty
		factor = base / qty if qty > _EPS else 0.0
		bom = boms.get(orden.bom_no)

		# Estándar --------------------------------------------------------------
		estandar = _vacio()
		por_item_std: dict[str, dict] = {}
		for item in items_orden.get(orden.name, []):
			cantidad_std = flt(item.required_qty) * factor
			tarifa = flt(item.rate)
			estandar["mp"] += tarifa * cantidad_std
			por_item_std[item.item_code] = {"qty": cantidad_std, "rate": tarifa, "item_name": item.item_name}
		if estandar["mp"] < _EPS and bom and flt(bom.quantity) > _EPS:
			estandar["mp"] = flt(bom.base_raw_material_cost) / flt(bom.quantity) * base

		ops = operaciones.get(orden.name, [])
		coste_op_plan = sum(flt(op.planned_operating_cost) for op in ops)
		mo_plan = sum(flt(op.planned_operating_cost) * parte_mo.get(op.workstation, 0.0) for op in ops)
		if coste_op_plan < _EPS and bom and flt(bom.quantity) > _EPS:
			coste_op_plan = flt(bom.base_operating_cost) / flt(bom.quantity) * qty
			mo_plan = 0.0
		cuota_mo = mo_plan / coste_op_plan if coste_op_plan > _EPS else 0.0
		estandar["mo"] = mo_plan * factor
		estandar["cif"] = (coste_op_plan - mo_plan) * factor
		for op in ops:
			if op.workstation and op.workstation not in parte_mo and flt(op.planned_operating_cost) > _EPS:
				avisos.add(
					_(
						"El puesto {0} no desglosa su coste por hora en componentes; se presenta como CIF."
					).format(op.workstation)
				)

		# Real ------------------------------------------------------------------------
		real = _vacio()
		consumos = materiales.get(orden.name, {})
		real["mp"] = sum(m["importe"] for m in consumos.values())
		real["subproductos"] = flt(productos.get(orden.name, {}).get("subproductos"))
		for coste in adicionales.get(orden.name, []):
			importe = flt(coste.base_amount)
			componente = coste.get("operating_component")
			if componente:
				clave = (
					"mo"
					if naturalezas.get(componente, naturaleza_por_nombre(componente)) == NATURALEZA_MO
					else "cif"
				)
				real[clave] += importe
			elif coste.get("has_operating_cost") or coste.get("has_corrective_cost"):
				real["mo"] += importe * cuota_mo
				real["cif"] += importe * (1 - cuota_mo)
			else:
				real["cif"] += importe
		tiene_real = producido > _EPS and bool(consumos or adicionales.get(orden.name))

		# Desviaciones de materiales: cantidad a precio estándar y precio sobre cantidad real.
		detalle = []
		desv_cantidad = desv_precio = 0.0
		for code in sorted(set(por_item_std) | set(consumos)):
			std = por_item_std.get(code, {"qty": 0.0, "rate": 0.0})
			consumo = consumos.get(code, {"qty": 0.0, "importe": 0.0})
			qty_real = flt(consumo["qty"])
			precio_real = consumo["importe"] / qty_real if qty_real > _EPS else std["rate"]
			cantidad = (qty_real - std["qty"]) * std["rate"] if tiene_real else 0.0
			precio = (precio_real - std["rate"]) * qty_real if tiene_real else 0.0
			desv_cantidad += cantidad
			desv_precio += precio
			detalle.append(
				{
					"item_code": code,
					"item_name": std.get("item_name") or consumo.get("item_name") or code,
					"qty_std": round(std["qty"], 4),
					"precio_std": round(std["rate"], 4),
					"importe_std": round(std["qty"] * std["rate"], 2),
					"qty_real": round(qty_real, 4),
					"precio_real": round(precio_real, 4),
					"importe_real": round(flt(consumo["importe"]), 2),
					"desv_cantidad": round(cantidad, 2),
					"desv_precio": round(precio, 2),
				}
			)

		estandar = _cerrar(estandar, base)
		real = _cerrar(real, producido)
		desviacion = None
		if tiene_real:
			desviacion = {
				k: round(real[k] - estandar[k], 2) for k in ("mp", "mo", "cif", "subproductos", "total")
			}
			desviacion["mp_cantidad"] = round(desv_cantidad, 2)
			desviacion["mp_precio"] = round(desv_precio, 2)
			desviacion["pct"] = (
				round(desviacion["total"] / estandar["total"], 4) if abs(estandar["total"]) > _EPS else None
			)
		filas.append(
			{
				"name": orden.name,
				"item_code": orden.production_item,
				"item_name": orden.item_name,
				"bom": orden.bom_no,
				"status": orden.status,
				"project": orden.project,
				"uom": orden.stock_uom,
				"qty": qty,
				"producido": round(producido, 4),
				"fecha": str(getdate(orden.actual_end_date or orden.planned_start_date))
				if (orden.actual_end_date or orden.planned_start_date)
				else "",
				"valor_producto": round(flt(productos.get(orden.name, {}).get("valor")), 2),
				"estandar": estandar,
				"real": real if tiene_real else None,
				"desviacion": desviacion,
				"materiales": detalle,
			}
		)

	return {
		"ordenes": filas,
		"productos": resumen_por_producto(filas),
		"resumen": resumen(filas),
		"avisos": sorted(avisos),
		"limite": len(ordenes) >= _MAX_ORDENES,
	}


def resumen(filas: list[dict]) -> dict:
	cerradas = [f for f in filas if f["real"]]
	total = {"ordenes": len(filas), "con_real": len(cerradas), "en_curso": len(filas) - len(cerradas)}
	for clave in ("estandar", "real"):
		total[clave] = {
			k: round(sum(f[clave][k] for f in cerradas), 2)
			for k in ("mp", "mo", "cif", "subproductos", "total")
		}
	total["desviacion"] = {k: round(total["real"][k] - total["estandar"][k], 2) for k in total["real"]}
	total["desviacion"]["mp_cantidad"] = round(sum(f["desviacion"]["mp_cantidad"] for f in cerradas), 2)
	total["desviacion"]["mp_precio"] = round(sum(f["desviacion"]["mp_precio"] for f in cerradas), 2)
	estandar = total["estandar"]["total"]
	total["desviacion"]["pct"] = (
		round(total["desviacion"]["total"] / estandar, 4) if abs(estandar) > _EPS else None
	)
	total["planificado_en_curso"] = round(sum(f["estandar"]["total"] for f in filas if not f["real"]), 2)
	return total


def resumen_por_producto(filas: list[dict]) -> list[dict]:
	"""Coste unitario estándar y real de cada producto, ponderado por la cantidad producida."""
	productos: dict[str, dict] = {}
	for fila in filas:
		if not fila["real"]:
			continue
		producto = productos.setdefault(
			fila["item_code"],
			{
				"item_code": fila["item_code"],
				"item_name": fila["item_name"],
				"uom": fila["uom"],
				"ordenes": 0,
				"producido": 0.0,
				"estandar": _vacio(),
				"real": _vacio(),
			},
		)
		producto["ordenes"] += 1
		producto["producido"] += fila["producido"]
		for clave in ("estandar", "real"):
			for k in ("mp", "mo", "cif", "subproductos"):
				producto[clave][k] += fila[clave][k]

	salida = []
	for producto in productos.values():
		cantidad = producto["producido"]
		producto["estandar"] = _cerrar(producto["estandar"], cantidad)
		producto["real"] = _cerrar(producto["real"], cantidad)
		total_std = producto["estandar"]["total"]
		producto["desviacion"] = round(producto["real"]["total"] - total_std, 2)
		producto["desviacion_pct"] = (
			round(producto["desviacion"] / total_std, 4) if abs(total_std) > _EPS else None
		)
		producto["producido"] = round(cantidad, 4)
		salida.append(producto)
	return sorted(salida, key=lambda p: -abs(p["desviacion"]))
