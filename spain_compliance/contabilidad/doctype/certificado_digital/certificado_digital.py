# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Certificado digital PKCS#12 de una compañía (SII, Veri*factu, firma)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate

from spain_compliance.contabilidad import certificados


def _es_mascara(valor: str | None) -> bool:
	return bool(valor) and set(valor) == {"*"}


class CertificadoDigital(Document):
	def validate(self):
		self._validar_adjunto_privado()
		self._leer_certificado()
		self._validar_duplicado()
		self._avisar_nif_compania()
		if not self.titulo:
			self.titulo = _("{0} — vence {1}").format(
				self.titular or self.company, formatdate(self.valido_hasta)
			)

	def on_update(self):
		if self.predeterminado:
			frappe.db.set_value(
				self.doctype,
				{"company": self.company, "predeterminado": 1, "name": ["!=", self.name]},
				"predeterminado",
				0,
			)

	# ------------------------------------------------------------------

	def _password_en_claro(self) -> str | None:
		if self.password and not _es_mascara(self.password):
			return self.password
		if self.is_new():
			return None
		return self.get_password("password", raise_exception=False)

	def _validar_adjunto_privado(self):
		if self.certificado and not self.certificado.startswith("/private/files/"):
			frappe.throw(
				_("El certificado debe subirse como fichero privado. Bórralo y vuelve a adjuntarlo marcando «Privado»."),
				title=_("Adjunto público"),
			)

	def _leer_certificado(self):
		try:
			contenido = certificados.contenido_adjunto(self.certificado)
		except frappe.DoesNotExistError:
			frappe.throw(_("No se encuentra el fichero adjunto {0}.").format(self.certificado))
		except OSError:
			frappe.throw(_("No se puede leer el fichero adjunto {0}.").format(self.certificado))

		try:
			_clave, cert, _cadena = certificados.leer_pkcs12(contenido, self._password_en_claro())
		except certificados.CertificadoInvalido:
			frappe.throw(
				_("No se puede abrir el certificado. Revisa la contraseña y que el fichero sea un .p12 / .pfx con clave privada."),
				title=_("Certificado no válido"),
			)

		self.update(certificados.metadatos(cert))
		self.estado = certificados.estado_por_fecha(self.valido_hasta)
		if self.estado == certificados.ESTADO_CADUCADO:
			frappe.msgprint(
				_("Este certificado caducó el {0}. Las integraciones no lo usarán.").format(
					formatdate(self.valido_hasta)
				),
				indicator="red",
				alert=True,
			)

	def _validar_duplicado(self):
		otro = frappe.db.exists(
			self.doctype,
			{"company": self.company, "huella_sha256": self.huella_sha256, "name": ["!=", self.name]},
		)
		if otro:
			frappe.throw(_("Este certificado ya está registrado en {0}.").format(otro))

	def _avisar_nif_compania(self):
		tax_id = certificados.normalizar_nif(frappe.db.get_value("Company", self.company, "tax_id"))
		if not tax_id:
			return
		nifs = {certificados.normalizar_nif(self.nif_entidad), certificados.normalizar_nif(self.nif_titular)}
		if tax_id not in nifs:
			frappe.msgprint(
				_("El NIF del certificado ({0}) no coincide con el de la compañía ({1}).").format(
					self.nif_entidad or self.nif_titular or "—", tax_id
				),
				indicator="orange",
				title=_("Revisa el certificado"),
			)
