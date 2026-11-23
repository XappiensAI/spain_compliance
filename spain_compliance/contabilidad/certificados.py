# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Certificados digitales (PKCS#12) para SII, Veri*factu y firma.

El fichero ``.p12`` vive como adjunto privado del DocType *Certificado Digital*
y su contraseña en un campo Password (cifrado con el ``encryption_key`` del
sitio). Las integraciones no leen ni el fichero ni la contraseña directamente,
sino que piden el certificado con :func:`get_certificado` o
:func:`archivos_pem`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

DOCTYPE = "Certificado Digital"

USOS = {
	"sii": "usar_sii",
	"verifactu": "usar_verifactu",
	"firma": "usar_firma",
}

ESTADO_VIGENTE = "Vigente"
ESTADO_PROXIMO = "Próximo a caducar"
ESTADO_CADUCADO = "Caducado"

# Días antes de la caducidad a partir de los cuales el certificado se marca
# como "Próximo a caducar".
DIAS_PROXIMO = 60

# Días restantes en los que se avisa a los administradores (0 = el día que caduca).
DIAS_AVISO = (60, 30, 15, 7, 1, 0)

ROLES_AVISO = ("System Manager", "Accounts Manager")

# OID 2.5.4.97 (organizationIdentifier), p. ej. "VATES-B00000000"
_OID_ORGANIZATION_IDENTIFIER = "2.5.4.97"


class CertificadoInvalido(ValueError):
	"""El fichero no es un PKCS#12 válido o la contraseña no lo abre."""


def _limpiar_identificador(valor: str | None) -> str | None:
	"""``IDCES-00000000T`` → ``00000000T``; ``VATES-B00000000`` → ``B00000000``."""
	if not valor:
		return None
	valor = valor.strip()
	if len(valor) > 6 and valor[5] == "-" and valor[:5].isalpha():
		return valor[6:]
	return valor


def _atributo(nombre, oid) -> str | None:
	attrs = nombre.get_attributes_for_oid(oid)
	return attrs[0].value if attrs else None


def leer_pkcs12(contenido: bytes, password: str | None):
	"""Abre el PKCS#12 y devuelve ``(clave, certificado, cadena)``.

	Lanza :class:`CertificadoInvalido` si la contraseña no es correcta, el
	fichero no es un PKCS#12 o no contiene clave privada y certificado.
	"""
	from cryptography.hazmat.primitives.serialization import pkcs12

	try:
		clave, cert, cadena = pkcs12.load_key_and_certificates(
			contenido, (password or "").encode() or None
		)
	except (ValueError, TypeError) as e:
		raise CertificadoInvalido(str(e)) from e

	if clave is None or cert is None:
		raise CertificadoInvalido("El PKCS#12 no contiene clave privada y certificado")
	return clave, cert, list(cadena or [])


def metadatos(cert) -> dict:
	"""Datos del certificado que se muestran en el DocType."""
	from cryptography.hazmat.primitives import hashes
	from cryptography.x509 import ObjectIdentifier
	from cryptography.x509.oid import NameOID

	sujeto, emisor = cert.subject, cert.issuer
	emisor_cn = _atributo(emisor, NameOID.COMMON_NAME)
	emisor_o = _atributo(emisor, NameOID.ORGANIZATION_NAME)

	return {
		"titular": _atributo(sujeto, NameOID.COMMON_NAME),
		"entidad": _atributo(sujeto, NameOID.ORGANIZATION_NAME),
		"nif_titular": _limpiar_identificador(_atributo(sujeto, NameOID.SERIAL_NUMBER)),
		"nif_entidad": _limpiar_identificador(
			_atributo(sujeto, ObjectIdentifier(_OID_ORGANIZATION_IDENTIFIER))
		),
		"emisor": " — ".join(x for x in (emisor_o, emisor_cn) if x) or None,
		"numero_serie": format(cert.serial_number, "X"),
		"valido_desde": cert.not_valid_before_utc.date(),
		"valido_hasta": cert.not_valid_after_utc.date(),
		"huella_sha256": cert.fingerprint(hashes.SHA256()).hex(":").upper(),
	}


def estado_por_fecha(valido_hasta, hoy=None) -> str:
	"""Vigente / Próximo a caducar / Caducado según los días que faltan."""
	if not valido_hasta:
		return ESTADO_VIGENTE
	dias = date_diff(getdate(valido_hasta), getdate(hoy or today()))
	if dias < 0:
		return ESTADO_CADUCADO
	if dias <= DIAS_PROXIMO:
		return ESTADO_PROXIMO
	return ESTADO_VIGENTE


def normalizar_nif(nif: str | None) -> str:
	"""Quita espacios, guiones y el prefijo de país ``ES``."""
	nif = "".join(c for c in (nif or "").upper() if c.isalnum())
	return nif[2:] if nif.startswith("ES") and len(nif) > 9 else nif


# ---------------------------------------------------------------------------
# Acceso para integraciones (no exponer por API: nunca @frappe.whitelist)
# ---------------------------------------------------------------------------


def contenido_adjunto(file_url: str) -> bytes:
	"""Bytes del fichero adjunto, sin decodificar."""
	if not file_url:
		raise CertificadoInvalido("Sin fichero adjunto")
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	with open(file_doc.get_full_path(), "rb") as f:
		return f.read()


def buscar_certificado(company: str, uso: str | None = None) -> str | None:
	"""Nombre del certificado no caducado para la compañía (y uso), o ``None``.

	Prioriza el marcado como predeterminado y, después, el que caduca más tarde.
	"""
	filters = {"company": company, "valido_hasta": [">=", today()]}
	if uso:
		if uso not in USOS:
			frappe.throw(_("Uso de certificado desconocido: {0}").format(uso))
		filters[USOS[uso]] = 1
	nombres = frappe.get_all(
		DOCTYPE,
		filters=filters,
		pluck="name",
		order_by="predeterminado desc, valido_hasta desc",
		limit=1,
	)
	return nombres[0] if nombres else None


def get_certificado(company: str, uso: str | None = None, nombre: str | None = None) -> frappe._dict:
	"""Certificado listo para usar por una integración.

	Devuelve ``frappe._dict`` con ``name``, ``clave`` (objeto de
	``cryptography``), ``certificado``, ``cadena``, ``cert_pem``, ``key_pem``
	(PEM sin cifrar, en memoria) y los metadatos. Lanza ``frappe.ValidationError``
	si no hay certificado vigente.
	"""
	from cryptography.hazmat.primitives import serialization

	nombre = nombre or buscar_certificado(company, uso)
	if not nombre:
		frappe.throw(
			_("No hay un certificado digital vigente para {0}{1}.").format(
				company, f" ({uso})" if uso else ""
			),
			title=_("Certificado digital"),
		)

	doc = frappe.get_doc(DOCTYPE, nombre)
	clave, cert, cadena = leer_pkcs12(
		contenido_adjunto(doc.certificado), doc.get_password("password")
	)
	cert_pem = cert.public_bytes(serialization.Encoding.PEM) + b"".join(
		c.public_bytes(serialization.Encoding.PEM) for c in cadena
	)
	key_pem = clave.private_bytes(
		serialization.Encoding.PEM,
		serialization.PrivateFormat.PKCS8,
		serialization.NoEncryption(),
	)
	return frappe._dict(
		name=doc.name,
		clave=clave,
		certificado=cert,
		cadena=cadena,
		cert_pem=cert_pem,
		key_pem=key_pem,
		**metadatos(cert),
	)


@contextmanager
def archivos_pem(company: str, uso: str | None = None, nombre: str | None = None):
	"""Escribe certificado y clave en PEM temporales y los borra al salir.

	Pensado para clientes HTTP que piden rutas (``requests``, ``zeep``)::

		with archivos_pem("Mi Empresa", "sii") as (cert, key):
			requests.post(url, data=xml, cert=(cert, key))
	"""
	datos = get_certificado(company, uso, nombre)
	carpeta = tempfile.mkdtemp(prefix="sc-cert-")
	try:
		os.chmod(carpeta, 0o700)
		rutas = []
		for nombre_fichero, contenido in (("cert.pem", datos.cert_pem), ("key.pem", datos.key_pem)):
			ruta = os.path.join(carpeta, nombre_fichero)
			fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
			with os.fdopen(fd, "wb") as f:
				f.write(contenido)
			rutas.append(ruta)
		yield tuple(rutas)
	finally:
		shutil.rmtree(carpeta, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tarea diaria
# ---------------------------------------------------------------------------


def destinatarios_aviso() -> list[str]:
	from frappe.utils.user import get_users_with_role

	usuarios: set[str] = set()
	for rol in ROLES_AVISO:
		usuarios.update(get_users_with_role(rol))
	usuarios.discard("Administrator")
	return sorted(usuarios)


def debe_avisar(valido_hasta, hoy=None) -> bool:
	if not valido_hasta:
		return False
	return date_diff(getdate(valido_hasta), getdate(hoy or today())) in DIAS_AVISO


def revisar_caducidad() -> dict:
	"""Actualiza el estado de los certificados y avisa de los que caducan pronto."""
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	hoy: date = getdate(today())
	avisados, actualizados = [], []
	destinatarios = None

	for cert in frappe.get_all(
		DOCTYPE, fields=["name", "company", "titular", "valido_hasta", "estado"]
	):
		estado = estado_por_fecha(cert.valido_hasta, hoy)
		if estado != cert.estado:
			frappe.db.set_value(DOCTYPE, cert.name, "estado", estado, update_modified=False)
			actualizados.append(cert.name)

		if not debe_avisar(cert.valido_hasta, hoy):
			continue
		if destinatarios is None:
			destinatarios = destinatarios_aviso()
		if not destinatarios:
			continue

		dias = date_diff(getdate(cert.valido_hasta), hoy)
		cuando = _("hoy") if dias == 0 else _("en {0} días").format(dias)
		enqueue_create_notification(
			destinatarios,
			{
				"type": "Alert",
				"document_type": DOCTYPE,
				"document_name": cert.name,
				"subject": _("El certificado digital de {0} ({1}) caduca {2}").format(
					cert.company, cert.titular or cert.name, cuando
				),
				"email_content": _(
					"Renueva el certificado antes del {0} para que SII, Veri*factu y la firma sigan funcionando."
				).format(frappe.format(cert.valido_hasta, {"fieldtype": "Date"})),
			},
		)
		avisados.append(cert.name)

	return {"actualizados": actualizados, "avisados": avisados}
