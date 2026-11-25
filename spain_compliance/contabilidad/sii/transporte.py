# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Llamada HTTPS a los servicios SOAP del SII con el certificado de la compañía."""

from __future__ import annotations

import requests

from spain_compliance.contabilidad.certificados import archivos_pem
from spain_compliance.contabilidad.sii.constantes import url_servicio

TIMEOUT = (15, 120)


class ErrorComunicacion(Exception):
	"""No se pudo hablar con la AEAT (red, TLS, HTTP distinto de 200 sin SOAP)."""


def llamar(
	company: str,
	libro: str,
	mensaje: bytes,
	entorno: str,
	sello: bool = False,
	certificado: str | None = None,
) -> bytes:
	"""POST del mensaje SOAP y devuelve el cuerpo de la respuesta.

	La AEAT responde 200 con la respuesta SII y 500 con un SOAP Fault; los dos se
	devuelven para que los lea :mod:`.xml`. Cualquier otra cosa es un
	:class:`ErrorComunicacion`.
	"""
	url = url_servicio(libro, entorno, sello)
	try:
		with archivos_pem(company, "sii", certificado) as (cert, key):
			r = requests.post(
				url,
				data=mensaje,
				headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": '""'},
				cert=(cert, key),
				timeout=TIMEOUT,
			)
	except requests.RequestException as e:
		raise ErrorComunicacion(f"{type(e).__name__}: {e}")
	if r.status_code not in (200, 500) or b"Envelope" not in r.content[:2000]:
		raise ErrorComunicacion(f"HTTP {r.status_code}: {r.text[:300]}")
	return r.content
