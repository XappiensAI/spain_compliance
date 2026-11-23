# Copyright (c) 2026, Xappiens and contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document


class SIIRegistro(Document):
	def autoname(self):
		# Nombre fijo por factura: la clave primaria impide registros duplicados
		# aunque dos procesos lo creen a la vez.
		libro = "E" if self.documento_tipo == "Sales Invoice" else "R"
		self.name = f"SII-{libro}-{self.documento}"

	def validate(self):
		otro = frappe.db.get_value(
			"SII Registro",
			{"documento_tipo": self.documento_tipo, "documento": self.documento, "name": ("!=", self.name)},
		)
		if otro:
			frappe.throw(_("La factura {0} ya tiene el registro SII {1}.").format(self.documento, otro))
