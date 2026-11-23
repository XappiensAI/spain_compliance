# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Clasificación fiscal de las filas de impuestos de facturas españolas.

La clasificación (tipo, clave, deducibilidad, retención) vive en la fila de
impuestos y en la plantilla. Al guardar, una fila vacía la copia de su
plantilla. Con *Exigir clasificación fiscal* en la compañía no se puede validar
una factura con filas sin clasificar.

No se guarda ningún registro aparte: el libro de IVA, la liquidación y el SII se
calculan sobre el mayor (``spain_compliance.contabilidad.libro_iva``).
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from spain_compliance.contabilidad.clasificacion import TIPO_RETENCION, TIPOS_CON_CLAVE
from spain_compliance.setup.custom_fields import (
	COMPANY_PGC_FIELDNAME,
	TAX_CLASSIFICATION_FIELDS,
)

DOCTYPES_FACTURA = ("Sales Invoice", "Purchase Invoice")
_PLANTILLA = {
	"Sales Invoice": "Sales Taxes and Charges Template",
	"Purchase Invoice": "Purchase Taxes and Charges Template",
}


def aplica_registro_fiscal(company: str | None) -> bool:
	"""Compañía de España o con el árbol PGC. El resto del sitio no se toca."""
	if not company or not frappe.db.exists("Company", company):
		return False
	if not frappe.db.has_column("Company", COMPANY_PGC_FIELDNAME):
		return False
	country, pgc = frappe.db.get_value("Company", company, ["country", COMPANY_PGC_FIELDNAME])
	return country == "Spain" or bool(pgc)


def validar_factura(doc, method=None):
	"""Al guardar, también en borrador: copia la clasificación de la plantilla."""
	if not aplica_registro_fiscal(doc.company) or doc.docstatus == 2:
		return
	copiar_clasificacion(doc)


def before_submit(doc, method=None):
	"""La exigencia bloquea la validación, no el borrador."""
	if not aplica_registro_fiscal(doc.company):
		return
	copiar_clasificacion(doc)
	if not cint(frappe.db.get_value("Company", doc.company, "exigir_clasificacion_fiscal")):
		return
	for tax in doc.get("taxes") or []:
		if not _es_fila_fiscal(tax):
			continue
		for parte in _desglose(doc, tax):
			if _incompleta(doc, tax, parte):
				frappe.throw(
					_(
						"El impuesto {0} de la factura no tiene clasificación fiscal completa "
						"(tipo, clave y, en compras, deducibilidad). Complétala en la factura o "
						"en su plantilla, o desactiva «Exigir clasificación fiscal» en la compañía {1}."
					).format(
						frappe.bold(tax.get("description") or tax.get("account_head")),
						frappe.bold(doc.company),
					)
				)


def copiar_clasificacion(doc):
	"""Rellena las filas vacías con la plantilla de impuestos. No pisa lo ya informado."""
	plantilla = doc.get("taxes_and_charges")
	if not plantilla:
		return
	doctype = _PLANTILLA.get(doc.doctype)
	if not doctype or not frappe.db.exists(doctype, plantilla):
		return

	usadas: set[int] = set()
	origen = frappe.get_cached_doc(doctype, plantilla).taxes
	for tax in doc.get("taxes") or []:
		for indice, fila in enumerate(origen):
			if indice in usadas:
				continue
			if fila.account_head != tax.account_head or flt(fila.rate) != flt(tax.rate):
				continue
			for campo in TAX_CLASSIFICATION_FIELDS:
				if not tax.get(campo) and fila.get(campo):
					tax.set(campo, fila.get(campo))
			usadas.add(indice)
			break


def _es_fila_fiscal(tax) -> bool:
	if tax.get("tipo_impuesto"):
		return True
	if (tax.get("charge_type") or "") == "Actual":
		return False
	cuenta = tax.get("account_head")
	if not cuenta:
		return False
	return frappe.get_cached_value("Account", cuenta, "account_type") == "Tax"


def _desglose(doc, tax) -> list[dict]:
	"""Una entrada por clave y tipo. La clave del ítem, si la tiene, manda sobre la de la fila."""
	detalle = _detalle(tax)
	items: dict[str, list] = {}
	for item in doc.get("items") or []:
		items.setdefault(item.item_code or item.item_name, []).append(item)

	if not detalle:
		cuota = flt(tax.base_tax_amount if tax.get("base_tax_amount") is not None else tax.tax_amount)
		tasa = flt(tax.rate)
		neto = flt(doc.base_net_total)
		return [
			{
				"rate": tasa,
				"cuota": flt(cuota, 2),
				"base": _base(tasa, cuota, neto),
				"clave": tax.get("clave_iva"),
			}
		]

	grupos: dict[tuple, dict] = {}
	for clave_item, valor in detalle.items():
		if isinstance(valor, (list, tuple)) and len(valor) >= 2:
			tasa, cuota = flt(valor[0]), flt(valor[1])
		else:
			tasa, cuota = flt(tax.rate), flt(valor)
		filas_item = items.get(clave_item) or []
		neto = sum(flt(fila.get("base_net_amount") or fila.get("net_amount")) for fila in filas_item)
		clave = _clave_items(filas_item) or tax.get("clave_iva")
		grupo = grupos.setdefault(
			(clave or "", tasa),
			{"rate": tasa, "cuota": 0.0, "base": 0.0, "clave": clave},
		)
		grupo["cuota"] += cuota
		grupo["base"] += _base(tasa, cuota, neto)

	for grupo in grupos.values():
		grupo["cuota"] = flt(grupo["cuota"], 2)
		grupo["base"] = flt(grupo["base"], 2)
	return list(grupos.values())


def _detalle(tax) -> dict:
	detalle = tax.get("item_wise_tax_detail")
	if isinstance(detalle, str):
		if not detalle:
			return {}
		try:
			detalle = json.loads(detalle)
		except ValueError:
			return {}
	return detalle if isinstance(detalle, dict) else {}


def _clave_items(filas_item) -> str | None:
	claves = set()
	for item in filas_item:
		plantilla = item.get("item_tax_template")
		if not plantilla:
			continue
		clave = frappe.db.get_value("Item Tax Template", plantilla, "clave_iva")
		if clave:
			claves.add(clave)
	if len(claves) == 1:
		return claves.pop()
	return None


def _base(tasa: float, cuota: float, neto: float) -> float:
	if tasa:
		return flt(cuota * 100.0 / tasa, 2)
	return flt(neto, 2)


def _incompleta(doc, tax, parte) -> bool:
	tipo = tax.get("tipo_impuesto")
	if not tipo:
		return True
	if tipo in TIPOS_CON_CLAVE and not parte.get("clave"):
		return True
	if tipo == TIPO_RETENCION and not tax.get("clave_retencion"):
		return True
	return doc.doctype == "Purchase Invoice" and tipo in TIPOS_CON_CLAVE and not tax.get("deducible_iva")
