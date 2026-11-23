# Copyright (c) 2026, Xappiens and contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class SIIConfiguracion(Document):
	def validate(self):
		self.tamano_lote = max(1, min(cint(self.tamano_lote) or 200, 10000))
		if self.certificado:
			cert_company = frappe.db.get_value("Certificado Digital", self.certificado, "company")
			if cert_company != self.company:
				frappe.throw(_("El certificado {0} es de otra compañía.").format(self.certificado))
		if not frappe.db.get_value("Company", self.company, "tax_id") and not self.nif_titular:
			frappe.throw(_("La compañía no tiene NIF. Indique el NIF del titular."))
		if cint(self.activo) and self.entorno == "Producción" and self.has_value_changed("entorno"):
			frappe.msgprint(
				_("A partir de ahora las facturas se comunican a la AEAT con efectos fiscales."),
				title=_("SII en producción"),
				indicator="orange",
			)

	def on_update(self):
		from spain_compliance.contabilidad.sii import registro

		anterior = self.get_doc_before_save()
		if anterior and anterior.entorno != self.entorno:
			n = registro.reiniciar_por_cambio_de_entorno(self.company, anterior.entorno, self.entorno)
			if n:
				frappe.msgprint(_("{0} registros vuelven a Pendiente para enviarse a Producción.").format(n))
		if cint(self.activo):
			frappe.enqueue(
				"spain_compliance.contabilidad.sii.registro.generar_registros",
				queue="long",
				job_id=f"sii-generar-{frappe.scrub(self.company)}",
				deduplicate=True,
				enqueue_after_commit=True,
				company=self.company,
			)
