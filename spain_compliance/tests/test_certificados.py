# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Certificados digitales PKCS#12 (sin escrituras en BD)."""

import datetime
import os
import stat
import unittest
from unittest.mock import patch

import frappe
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from spain_compliance.contabilidad import certificados

MOD = "spain_compliance.contabilidad.certificados"
PASSWORD = "secreto-de-prueba"
CADUCA = datetime.datetime(2028, 5, 6, 10, 56, tzinfo=datetime.timezone.utc)


def _p12(password=PASSWORD):
	clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	sujeto = x509.Name(
		[
			x509.NameAttribute(NameOID.COUNTRY_NAME, "ES"),
			x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EMPRESA DE PRUEBA SL"),
			x509.NameAttribute(NameOID.SERIAL_NUMBER, "IDCES-00000000T"),
			x509.NameAttribute(NameOID.COMMON_NAME, "00000000T NOMBRE APELLIDO (R: B00000000)"),
			x509.NameAttribute(x509.ObjectIdentifier("2.5.4.97"), "VATES-B00000000"),
		]
	)
	emisor = x509.Name(
		[
			x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CA DE PRUEBA"),
			x509.NameAttribute(NameOID.COMMON_NAME, "CA PRUEBA 2026"),
		]
	)
	cert = (
		x509.CertificateBuilder()
		.subject_name(sujeto)
		.issuer_name(emisor)
		.public_key(clave.public_key())
		.serial_number(0xABC123)
		.not_valid_before(datetime.datetime(2026, 5, 6, tzinfo=datetime.timezone.utc))
		.not_valid_after(CADUCA)
		.sign(clave, hashes.SHA256())
	)
	return pkcs12.serialize_key_and_certificates(
		b"prueba", clave, cert, None, BestAvailableEncryption(password.encode())
	)


class TestLeerPkcs12(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.contenido = _p12()

	def test_abre_con_password_correcta(self):
		clave, cert, cadena = certificados.leer_pkcs12(self.contenido, PASSWORD)
		self.assertIsNotNone(clave)
		self.assertEqual(cert.serial_number, 0xABC123)
		self.assertEqual(cadena, [])

	def test_password_incorrecta(self):
		with self.assertRaises(certificados.CertificadoInvalido):
			certificados.leer_pkcs12(self.contenido, "otra")

	def test_fichero_no_pkcs12(self):
		with self.assertRaises(certificados.CertificadoInvalido):
			certificados.leer_pkcs12(b"no es un certificado", PASSWORD)

	def test_metadatos(self):
		_clave, cert, _cadena = certificados.leer_pkcs12(self.contenido, PASSWORD)
		datos = certificados.metadatos(cert)
		self.assertEqual(datos["nif_titular"], "00000000T")
		self.assertEqual(datos["nif_entidad"], "B00000000")
		self.assertEqual(datos["entidad"], "EMPRESA DE PRUEBA SL")
		self.assertEqual(datos["emisor"], "CA DE PRUEBA — CA PRUEBA 2026")
		self.assertEqual(datos["numero_serie"], "ABC123")
		self.assertEqual(datos["valido_desde"], datetime.date(2026, 5, 6))
		self.assertEqual(datos["valido_hasta"], datetime.date(2028, 5, 6))
		self.assertEqual(len(datos["huella_sha256"].split(":")), 32)


class TestEstado(unittest.TestCase):
	def test_estado_por_fecha(self):
		self.assertEqual(certificados.estado_por_fecha("2028-05-06", "2026-11-12"), "Vigente")
		self.assertEqual(certificados.estado_por_fecha("2028-05-06", "2028-03-07"), "Próximo a caducar")
		self.assertEqual(certificados.estado_por_fecha("2028-05-06", "2028-05-06"), "Próximo a caducar")
		self.assertEqual(certificados.estado_por_fecha("2028-05-06", "2028-05-07"), "Caducado")

	def test_debe_avisar(self):
		self.assertTrue(certificados.debe_avisar("2028-05-06", "2028-04-06"))  # 30 días
		self.assertTrue(certificados.debe_avisar("2028-05-06", "2028-05-06"))  # hoy
		self.assertFalse(certificados.debe_avisar("2028-05-06", "2028-04-07"))
		self.assertFalse(certificados.debe_avisar(None, "2028-05-06"))

	def test_normalizar_nif(self):
		self.assertEqual(certificados.normalizar_nif("ESB00000000"), "B00000000")
		self.assertEqual(certificados.normalizar_nif("es-b00000000"), "B00000000")
		self.assertEqual(certificados.normalizar_nif("B00000000"), "B00000000")
		self.assertEqual(certificados.normalizar_nif(None), "")


class TestArchivosPem(unittest.TestCase):
	def test_crea_y_borra_pem_privados(self):
		datos = frappe._dict(cert_pem=b"CERT", key_pem=b"KEY")
		with patch(f"{MOD}.get_certificado", return_value=datos):
			with certificados.archivos_pem("Empresa", "sii") as (cert, key):
				with open(cert, "rb") as f:
					self.assertEqual(f.read(), b"CERT")
				with open(key, "rb") as f:
					self.assertEqual(f.read(), b"KEY")
				self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
				self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(key)).st_mode), 0o700)
		self.assertFalse(os.path.exists(os.path.dirname(key)))
