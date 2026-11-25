# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Descarga en PDF de las facturas desde /contabilidad.

``frappe.utils.print_format.download_pdf`` sin ``format`` ni ``pdf_generator`` usa el
motor de Print Settings (``wkhtmltopdf`` por defecto), no el del formato de impresión
predeterminado del DocType, y falla si ``wkhtmltopdf`` no está en el servidor. Aquí se
pasan los dos de forma explícita y el PDF se sirve como descarga.

Permisos: los de impresión del DocType, que comprueba ``download_pdf``.
"""

from __future__ import annotations

import importlib.util
import shutil

import frappe
from frappe.utils.print_format import download_pdf
from frappe.utils.print_utils import resolve_pdf_generator

from spain_compliance.api.facturas import _exigir_doctype


def _formato(doctype: str) -> str:
	"""Formato predeterminado del DocType, el mismo que abre la vista de impresión."""
	formato = frappe.get_meta(doctype).default_print_format
	if formato and frappe.db.exists("Print Format", {"name": formato, "disabled": 0}):
		return formato
	return "Standard"


def _motor(formato: str) -> str:
	"""Motor PDF del formato, o uno instalado si el suyo es wkhtmltopdf y no está."""
	pf = None if formato == "Standard" else frappe.get_cached_doc("Print Format", formato)
	motor = resolve_pdf_generator(pf)
	if motor == "wkhtmltopdf" and not shutil.which("wkhtmltopdf"):
		# PlutoPrint pasa él mismo a Chrome cuando no puede con la plantilla.
		return "PlutoPrint" if importlib.util.find_spec("plutoprint") else "chrome"
	return motor


@frappe.whitelist(methods=["GET"])
def descargar_pdf(doctype: str, name: str) -> None:
	doctype = _exigir_doctype(doctype)
	formato = _formato(doctype)
	download_pdf(doctype, name, format=formato, pdf_generator=_motor(formato))
	# ``download_pdf`` responde en línea; aquí se quiere el fichero.
	frappe.local.response.type = "download"
	frappe.local.response.content_type = "application/pdf"
