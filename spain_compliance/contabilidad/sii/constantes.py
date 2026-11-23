# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Constantes del SII (versión 1.1 del esquema)."""

from __future__ import annotations

VERSION_SII = "1.1"

ENTORNO_PRUEBAS = "Pruebas"
ENTORNO_PRODUCCION = "Producción"

_BASE_XSD = (
	"https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/"
	"aplicaciones/es/aeat/ssii/fact/ws/"
)
NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
NS_LR = _BASE_XSD + "SuministroLR.xsd"
NS_SII = _BASE_XSD + "SuministroInformacion.xsd"
NS_LRC = _BASE_XSD + "ConsultaLR.xsd"

# Servidores: www1 para certificados de persona física / representante,
# www10 para certificados de sello. En pruebas, prewww1 / prewww10.
_HOSTS = {
	(ENTORNO_PRODUCCION, False): "https://www1.agenciatributaria.gob.es",
	(ENTORNO_PRODUCCION, True): "https://www10.agenciatributaria.gob.es",
	(ENTORNO_PRUEBAS, False): "https://prewww1.aeat.es",
	(ENTORNO_PRUEBAS, True): "https://prewww10.aeat.es",
}
_RUTAS = {
	"Expedidas": "/wlpl/SSII-FACT/ws/fe/SiiFactFEV1SOAP",
	"Recibidas": "/wlpl/SSII-FACT/ws/fr/SiiFactFRV1SOAP",
}


def url_servicio(libro: str, entorno: str, sello: bool = False) -> str:
	return _HOSTS[(entorno, bool(sello))] + _RUTAS[libro]


# Estados de SII Registro
PENDIENTE = "Pendiente"
ACEPTADO = "Aceptado"
ACEPTADO_ERRORES = "Aceptado con errores"
RECHAZADO = "Rechazado"
ERROR_COMUNICACION = "Error de comunicación"
ERROR_DATOS = "Error de datos"
BAJA_PENDIENTE = "Baja pendiente"
DADO_DE_BAJA = "Dado de baja"
# Recibida solo con operaciones no sujetas: no se comunica.
NO_APLICA = "No aplica"

ESTADOS = (
	PENDIENTE,
	ACEPTADO,
	ACEPTADO_ERRORES,
	RECHAZADO,
	ERROR_COMUNICACION,
	ERROR_DATOS,
	BAJA_PENDIENTE,
	DADO_DE_BAJA,
	NO_APLICA,
)
# La AEAT ya tiene la factura: el siguiente envío es una modificación (A1).
ESTADOS_COMUNICADOS = (ACEPTADO, ACEPTADO_ERRORES)
# Se pueden (re)enviar como alta o modificación.
ESTADOS_ENVIABLES = (PENDIENTE, RECHAZADO, ERROR_COMUNICACION, ERROR_DATOS, ACEPTADO_ERRORES)

# Reintentos automáticos de errores de comunicación.
MAX_INTENTOS_AUTO = 10

# Código de la AEAT para «factura ya registrada».
CODIGO_DUPLICADO = "3000"

# EstadoRegistro de la AEAT → estado del registro
ESTADO_LINEA = {
	"Correcto": ACEPTADO,
	"AceptadoConErrores": ACEPTADO_ERRORES,
	"Incorrecto": RECHAZADO,
}
# EstadoRegistro de una consulta / de un registro duplicado → estado del registro
ESTADO_CONSULTA = {
	"Correcta": ACEPTADO,
	"AceptadaConErrores": ACEPTADO_ERRORES,
	"Anulada": DADO_DE_BAJA,
}

# Tipo de identificación del tercero → IDType del bloque IDOtro
ID_TYPE = {
	"NIF-IVA": "02",
	"Pasaporte": "03",
	"Documento oficial": "04",
	"Certificado de residencia": "05",
	"Otro": "06",
}

PAISES_UE = frozenset(
	"AT BE BG CY CZ DE DK EE EL ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK XI".split()
)

TIPO_OP_ENTREGA = "Entrega"
TIPO_OP_SERVICIOS = "PrestacionServicios"
