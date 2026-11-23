# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Series de facturación por compañía.

Cada compañía puede fijar su serie de emitidas, rectificativas emitidas,
recibidas y rectificativas recibidas. El ``name`` de una factura es único en todo
el sitio, así que dos compañías no pueden compartir serie (la segunda consumiría
números de la primera).

Para que ``YY`` tome el año de la **fecha de la factura** (y no el de hoy) hay que
activar en *Global Defaults* la opción de ERPNext
``use_posting_datetime_for_naming_documents``. Sin ella, una factura del 31/12
creada el 2/1 saldría con el año siguiente y rompería la correlatividad.
"""

from __future__ import annotations

import frappe
from frappe import _

from spain_compliance.setup.custom_fields import (
	COMPANY_PURCHASE_RETURN_SERIES_FIELDNAME,
	COMPANY_PURCHASE_SERIES_FIELDNAME,
	COMPANY_RETURN_SERIES_FIELDNAME,
	COMPANY_SALES_SERIES_FIELDNAME,
)

# DocType → (campo serie ordinaria, campo serie rectificativa) en Company.
CAMPOS_SERIE: dict[str, tuple[str, str]] = {
	"Sales Invoice": (COMPANY_SALES_SERIES_FIELDNAME, COMPANY_RETURN_SERIES_FIELDNAME),
	"Purchase Invoice": (COMPANY_PURCHASE_SERIES_FIELDNAME, COMPANY_PURCHASE_RETURN_SERIES_FIELDNAME),
}

# Serie por compañía ---------------------------------------------------------------


def _limpia(valor: str | None) -> str:
	return (valor or "").strip()


def serie_compania(doctype: str, company: str | None, es_rectificativa: bool) -> str | None:
	"""Serie configurada en la compañía para ese tipo de factura (o None)."""
	campos = CAMPOS_SERIE.get(doctype)
	if not campos or not company:
		return None
	campo = campos[1] if es_rectificativa else campos[0]
	try:
		return _limpia(frappe.get_cached_value("Company", company, campo)) or None
	except Exception:
		return None


def series_de_otras_companias(doctype: str, company: str | None) -> dict[str, str]:
	"""``{serie: compañía}`` de las series configuradas en el resto de compañías."""
	campos = CAMPOS_SERIE.get(doctype)
	if not campos:
		return {}
	filas = frappe.get_all("Company", filters={"name": ("!=", company or "")}, fields=["name", *campos])
	out: dict[str, str] = {}
	for fila in filas:
		for campo in campos:
			serie = _limpia(fila.get(campo))
			if serie:
				out.setdefault(serie, fila.name)
	return out


def serie_por_defecto(doctype: str) -> str | None:
	df = frappe.get_meta(doctype).get_field("naming_series")
	if not df:
		return None
	if df.default:
		return df.default
	opciones = [o for o in (df.options or "").split("\n") if o]
	return opciones[0] if opciones else None


def aplicar_serie(doc) -> None:
	"""Antes de numerar, pone la serie de la compañía si la elegida no es deliberada.

	Se respeta una serie distinta elegida a mano (p. ej. una serie histórica), salvo
	que pertenezca a otra compañía. Se sustituye si está vacía, es la serie por
	defecto del DocType, la de otra compañía o (en rectificativas) la copiada de la
	factura original.
	"""
	es_rect = bool(doc.get("is_return"))
	objetivo = serie_compania(doc.doctype, doc.company, es_rect)
	if not objetivo:
		return

	actual = _limpia(doc.get("naming_series"))
	if actual == objetivo:
		return

	sustituir = not actual or actual == serie_por_defecto(doc.doctype)
	if not sustituir and actual in series_de_otras_companias(doc.doctype, doc.company):
		sustituir = True
	if not sustituir and es_rect:
		ordinaria = serie_compania(doc.doctype, doc.company, False)
		original = None
		if doc.get("return_against"):
			original = frappe.db.get_value(doc.doctype, doc.return_against, "naming_series")
		sustituir = actual in {ordinaria, original}

	if sustituir:
		doc.naming_series = objetivo


def validar_serie(doc) -> None:
	"""Impide usar en una compañía la serie configurada para otra."""
	actual = _limpia(doc.get("naming_series"))
	if not actual or not doc.get("company"):
		return
	propias = {
		serie_compania(doc.doctype, doc.company, False),
		serie_compania(doc.doctype, doc.company, True),
	}
	if actual in propias:
		return
	otra = series_de_otras_companias(doc.doctype, doc.company).get(actual)
	if otra:
		frappe.throw(
			_("La serie {0} pertenece a la compañía {1}. Una factura de {2} no puede usarla.").format(
				frappe.bold(actual), frappe.bold(otra), frappe.bold(doc.company)
			),
			title=_("Serie de otra compañía"),
		)


# doc_events -----------------------------------------------------------------------


def on_before_naming(doc, method=None):
	aplicar_serie(doc)


def on_validate(doc, method=None):
	validar_serie(doc)
