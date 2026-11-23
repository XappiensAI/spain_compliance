# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Retira el DocType ``Registro Fiscal IVA``.

El libro de IVA, la liquidación y el SII se calculan ahora sobre el mayor
(``spain_compliance.contabilidad.libro_iva``). Guardar un registro aparte
duplicaba información. La clasificación fiscal sigue en las filas de impuestos.
"""

import frappe

DOCTYPE = "Registro Fiscal IVA"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	frappe.db.delete(DOCTYPE)
	frappe.delete_doc("DocType", DOCTYPE, ignore_missing=True, force=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{DOCTYPE}`")
