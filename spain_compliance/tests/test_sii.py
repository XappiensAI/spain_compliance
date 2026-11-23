# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""SII: agrupación de líneas, contraparte, plazos, XML y lectura de respuestas.

Sin base de datos ni llamadas a la AEAT: se prueban las funciones puras.
"""

from datetime import date

from frappe.tests.utils import FrappeTestCase
from lxml import etree

from spain_compliance.contabilidad.sii import xml as X
from spain_compliance.contabilidad.sii.constantes import NS_SII
from spain_compliance.contabilidad.sii.datos import (
	contraparte,
	desglose_emitida,
	desglose_recibida,
	es_extranjera,
	tipo_legal,
)
from spain_compliance.contabilidad.sii.fechas import fecha_limite, sumar_habiles

TIT = {"nombre": "EMPRESA DE PRUEBA SL", "nif": "B12345674"}


def linea(clave, base, cuota=0.0, tipo=21.0, impuesto="IVA", **kw):
	return {
		"tipo_impuesto": impuesto,
		"clave_iva": clave,
		"base_imponible": base,
		"cuota": cuota,
		"tipo_impositivo": tipo if cuota else 0.0,
		"cuenta": "477",
		**kw,
	}


def factura(libro="Expedidas", **kw):
	f = {
		"libro": libro,
		"numero": "FV2700001",
		"fecha_expedicion": date(2027, 1, 4),
		"fecha_contable": date(2027, 1, 4),
		"ejercicio": "2027",
		"periodo": "01",
		"tipo_factura": "F1",
		"rectificada": None,
		"clave_regimen": "01",
		"importe_total": 121.0,
		"descripcion": "Moldes",
		"contraparte": {"nombre": "CLIENTE SA", "nif": "A58818501"},
	}
	f.update(kw)
	return f


def texto(xml: bytes, tag: str) -> list[str]:
	raiz = etree.fromstring(xml)
	return [e.text for e in raiz.iter(f"{{{NS_SII}}}{tag}")]


class TestContraparte(FrappeTestCase):
	def test_nif_espanol(self):
		self.assertEqual(contraparte("X", "B12345674", None, "ES"), {"nombre": "X", "nif": "B12345674"})
		# Con prefijo ES se quita el prefijo.
		self.assertEqual(contraparte("X", "ESB12345674", None, None)["nif"], "B12345674")

	def test_nif_iva_ue(self):
		cp = contraparte("CLIENTE FR", "FR12345678901", None, "fr")
		self.assertEqual(cp["id_otro"], {"pais": "FR", "tipo": "02", "id": "FR12345678901"})
		self.assertTrue(es_extranjera(cp))

	def test_extracomunitario(self):
		cp = contraparte("ACME", "123456789", None, "us")
		self.assertEqual(cp["id_otro"]["tipo"], "04")
		self.assertEqual(cp["id_otro"]["pais"], "US")

	def test_grecia(self):
		cp = contraparte("G", "EL123456789", None, None)
		self.assertEqual(cp["id_otro"]["pais"], "GR")
		self.assertEqual(cp["id_otro"]["tipo"], "02")


class TestDesglose(FrappeTestCase):
	def test_nacional_varios_tipos(self):
		d = desglose_emitida(
			[linea("S1 - Sujeta", 100, 21), linea("S1 - Sujeta", 50, 5, 10), linea("S1 - Sujeta", 10, 2.1)],
			False,
			"PrestacionServicios",
		)
		self.assertEqual(d["errores"], [])
		s1 = d["desglose"]["DesgloseFactura"]["no_exentas"]["S1"]
		self.assertEqual(sorted((x["tipo"], x["base"], x["cuota"]) for x in s1), [(10.0, 50, 5), (21.0, 110, 23.1)])

	def test_intracomunitaria_y_exportacion(self):
		d = desglose_emitida([linea("E5 - Exenta art. 25", 500), linea("N2 - No sujeta", 80)], True, "PrestacionServicios")
		self.assertEqual(d["desglose"]["Entrega"]["exentas"], {"E5": 500})
		self.assertEqual(d["desglose"]["PrestacionServicios"]["no_sujeta_localizacion"], 80)
		self.assertFalse(d["exportacion"])
		self.assertTrue(desglose_emitida([linea("E2 - Exenta art. 21", 10)], True, "Entrega")["exportacion"])

	def test_recargo_en_el_mismo_detalle(self):
		d = desglose_emitida(
			[linea("S1 - Sujeta", 100, 21), linea("S1 - Sujeta", 100, 5.2, 5.2, impuesto="Recargo de equivalencia")],
			False,
			"Entrega",
		)
		det = d["desglose"]["DesgloseFactura"]["no_exentas"]["S1"]
		self.assertEqual(len(det), 1)
		self.assertEqual((det[0]["tipo_re"], det[0]["cuota_re"]), (5.2, 5.2))

	def test_sin_clave_es_error(self):
		d = desglose_emitida([linea("", 100, 21)], False, "Entrega")
		self.assertTrue(d["errores"])

	def test_recibida_aib_isp_y_retencion(self):
		d = desglose_recibida(
			[
				linea("AIB - Adquisición", 100, 21, cuota_deducible=21),
				linea("", 100, 21, impuesto="Otro", autorrepercusion=True),
				linea("ISP - Inversión", 200, 42, cuota_deducible=42),
				linea("", 100, 15, 15, impuesto="Retención IRPF"),
			]
		)
		self.assertEqual(d["errores"], [])
		self.assertTrue(d["intracomunitaria"])
		self.assertEqual(len(d["iva"]), 1)
		self.assertEqual(len(d["isp"]), 1)
		self.assertEqual(d["cuota_deducible"], 63)

	def test_recibida_solo_no_sujeta(self):
		d = desglose_recibida([linea("N1 - No sujeta", 100)])
		self.assertTrue(d["solo_no_sujeta"])
		self.assertEqual(d["errores"], [])

	def test_tipo_legal(self):
		self.assertEqual(tipo_legal(20.99, 38.69, 8.12), 21.0)
		self.assertEqual(tipo_legal(10, 100, 10), 10)
		self.assertEqual(tipo_legal(13.0, 100, 13), 13.0)


class TestPlazo(FrappeTestCase):
	def test_cuatro_habiles(self):
		# Jueves 7/1/2027 + 4 hábiles = miércoles 13/1
		self.assertEqual(sumar_habiles(date(2027, 1, 7), 4), date(2027, 1, 13))
		# 6 de enero es festivo nacional
		self.assertEqual(sumar_habiles(date(2027, 1, 4), 4), date(2027, 1, 11))

	def test_tope_dia_15(self):
		self.assertEqual(fecha_limite(date(2027, 1, 31), date(2027, 1, 31)), date(2027, 2, 4))
		self.assertEqual(fecha_limite(date(2027, 1, 13), date(2026, 12, 28)), date(2027, 1, 15))


class TestXML(FrappeTestCase):
	def test_alta_emitida_nacional(self):
		f = factura(
			desglose={
				"DesgloseFactura": {
					"exentas": {},
					"no_exentas": {"S1": [{"tipo": 21.0, "base": 100.0, "cuota": 21.0}]},
					"no_sujeta_7_14": 0,
					"no_sujeta_localizacion": 0,
				}
			}
		)
		xml = X.mensaje_alta("Expedidas", TIT, [f], "A0")
		self.assertEqual(texto(xml, "TipoComunicacion"), ["A0"])
		self.assertEqual(texto(xml, "FechaExpedicionFacturaEmisor"), ["04-01-2027"])
		self.assertEqual(texto(xml, "TipoNoExenta"), ["S1"])
		self.assertEqual(texto(xml, "CuotaRepercutida"), ["21.00"])

	def test_rectificativa_y_extranjera(self):
		f = factura(
			tipo_factura="R1",
			rectificada={"numero": "FV2600001", "fecha": date(2026, 12, 1)},
			contraparte={"nombre": "CLIENTE FR", "id_otro": {"pais": "FR", "tipo": "02", "id": "FR12345678901"}},
			desglose={"Entrega": {"exentas": {"E5": -50.0}, "no_exentas": {}, "no_sujeta_7_14": 0, "no_sujeta_localizacion": 0}},
		)
		xml = X.mensaje_alta("Expedidas", TIT, [f], "A0")
		self.assertEqual(texto(xml, "TipoRectificativa"), ["I"])
		self.assertEqual(texto(xml, "IDType"), ["02"])
		self.assertEqual(texto(xml, "CausaExencion"), ["E5"])

	def test_recibida_identifica_al_proveedor(self):
		f = factura(
			"Recibidas",
			numero="A-77",
			contraparte={"nombre": "PROV", "nif": "A58818501"},
			desglose_iva=[{"tipo": 21.0, "base": 100.0, "cuota": 21.0, "bien_inversion": True}],
			desglose_isp=[],
			cuota_deducible=21.0,
		)
		xml = X.mensaje_alta("Recibidas", TIT, [f], "A0")
		self.assertEqual(texto(xml, "NIF"), ["B12345674", "A58818501", "A58818501"])
		self.assertEqual(texto(xml, "BienInversion"), ["S"])
		self.assertEqual(texto(xml, "CuotaDeducible"), ["21.00"])

	def test_lee_respuesta_con_duplicado(self):
		resp = b"""<?xml version="1.0" encoding="UTF-8"?><env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body>
		<siiR:RespuestaLRFacturasEmitidas xmlns:sii="%s" xmlns:siiR="urn:r">
		<siiR:CSV>ABC</siiR:CSV><siiR:EstadoEnvio>ParcialmenteCorrecto</siiR:EstadoEnvio>
		<siiR:RespuestaLinea><siiR:IDFactura><sii:IDEmisorFactura><sii:NIF>B12345674</sii:NIF></sii:IDEmisorFactura>
		<sii:NumSerieFacturaEmisor>FV1</sii:NumSerieFacturaEmisor></siiR:IDFactura><siiR:EstadoRegistro>Correcto</siiR:EstadoRegistro></siiR:RespuestaLinea>
		<siiR:RespuestaLinea><siiR:IDFactura><sii:IDEmisorFactura><sii:NIF>B12345674</sii:NIF></sii:IDEmisorFactura>
		<sii:NumSerieFacturaEmisor>FV2</sii:NumSerieFacturaEmisor></siiR:IDFactura><siiR:EstadoRegistro>Incorrecto</siiR:EstadoRegistro>
		<siiR:CodigoErrorRegistro>3000</siiR:CodigoErrorRegistro><siiR:RegistroDuplicado><sii:EstadoRegistro>Anulada</sii:EstadoRegistro></siiR:RegistroDuplicado></siiR:RespuestaLinea>
		</siiR:RespuestaLRFacturasEmitidas></env:Body></env:Envelope>""" % NS_SII.encode()
		r = X.leer_respuesta_envio(resp)
		self.assertEqual(r["csv"], "ABC")
		self.assertEqual([ln["estado"] for ln in r["lineas"]], ["Correcto", "Incorrecto"])
		self.assertEqual(r["lineas"][1]["duplicado"]["estado"], "Anulada")

	def test_soap_fault(self):
		resp = b"""<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body><env:Fault>
		<faultcode>env:Client</faultcode><faultstring>Codigo[4102].El XML no cumple el esquema</faultstring></env:Fault></env:Body></env:Envelope>"""
		with self.assertRaises(X.RespuestaInvalida) as cm:
			X.leer_respuesta_envio(resp)
		self.assertEqual(cm.exception.codigo, "env:Client")


class RegistroFalso(dict):
	"""Lo justo de un SII Registro para probar la máquina de estados sin BD."""

	def __init__(self, **kw):
		super().__init__({"estado": "Pendiente", "tipo_comunicacion": "A0", "entorno": None, "intentos": 0, **kw})
		self.eventos = []
		self.guardado = 0

	__getattr__ = dict.get

	def __setattr__(self, k, v):
		if k in ("eventos", "guardado"):
			return super().__setattr__(k, v)
		self[k] = v

	def append(self, _tabla, fila):
		self.eventos.append(fila)

	def save(self, **_kw):
		self.guardado += 1


def respuesta(*lineas, csv="CSV1"):
	return {"csv": csv, "estado_envio": "ParcialmenteCorrecto", "lineas": list(lineas)}


def linea_resp(numero, estado, codigo=None, dup=None):
	return {"numero": numero, "nif_emisor": TIT["nif"], "estado": estado, "codigo": codigo, "descripcion": None, "csv": None, "xml": "<x/>", "duplicado": dup}


class TestEstados(FrappeTestCase):
	def setUp(self):
		from spain_compliance.contabilidad.sii import registro

		self.R = registro

	def par(self, numero="FV1", **kw):
		reg = RegistroFalso(name=f"SII-E-{numero}", **kw)
		return reg, factura(numero=numero)

	def test_tipo_comunicacion(self):
		t = self.R._tipo_comunicacion
		self.assertEqual(t(RegistroFalso()), "A0")
		self.assertEqual(t(RegistroFalso(estado="Aceptado")), "A1")
		# Un A1 rechazado se reenvía como A1, no como alta.
		self.assertEqual(t(RegistroFalso(estado="Rechazado", tipo_comunicacion="A1")), "A1")

	def test_alta_correcta(self):
		reg, f = self.par()
		out = self.R._procesar_respuesta([(reg, f)], respuesta(linea_resp("FV1", "Correcto")), "Expedidas", "Pruebas", "Alta", False, "A0")
		self.assertEqual(out, [])
		self.assertEqual((reg.estado, reg.tipo_comunicacion, reg.csv), ("Aceptado", "A1", "CSV1"))

	def test_duplicado_se_reenvia_como_a1(self):
		for previo in ("Correcta", "AceptadaConErrores", "Anulada"):
			reg, f = self.par()
			linea = linea_resp("FV1", "Incorrecto", "3000", {"estado": previo})
			out = self.R._procesar_respuesta([(reg, f)], respuesta(linea), "Expedidas", "Pruebas", "Alta", False, "A0")
			self.assertEqual(len(out), 1, previo)
			# No se da por aceptada hasta que la AEAT acepte el A1.
			self.assertEqual(reg.estado, "Pendiente")

	def test_baja_rechazada_sigue_pendiente(self):
		reg, f = self.par(estado="Baja pendiente")
		linea = linea_resp("FV1", "Incorrecto", "3001")
		self.R._procesar_respuesta([(reg, f)], respuesta(linea), "Expedidas", "Pruebas", "Baja", True, None)
		self.assertEqual((reg.estado, reg.codigo_error), ("Baja pendiente", "3001"))

	def test_baja_correcta(self):
		reg, f = self.par(estado="Baja pendiente")
		self.R._procesar_respuesta([(reg, f)], respuesta(linea_resp("FV1", "Correcto")), "Expedidas", "Pruebas", "Baja", True, None)
		self.assertEqual(reg.estado, "Dado de baja")

	def test_factura_ausente_en_la_respuesta(self):
		reg, f = self.par()
		self.R._procesar_respuesta([(reg, f)], respuesta(), "Expedidas", "Pruebas", "Alta", False, "A0")
		self.assertEqual(reg.estado, "Error de comunicación")
		reg, f = self.par(estado="Baja pendiente")
		self.R._procesar_respuesta([(reg, f)], respuesta(), "Expedidas", "Pruebas", "Baja", True, None)
		self.assertEqual(reg.estado, "Baja pendiente")

	def test_paginacion_con_emisor_extranjero(self):
		xml = X.mensaje_consulta(
			"Recibidas",
			TIT,
			"2027",
			"01",
			paginacion={"id_otro": {"pais": "IT", "tipo": "02", "id": "IT12345678901"}, "numero": "A1", "fecha": "02-01-2027"},
		)
		self.assertEqual(texto(xml, "IDType"), ["02"])
		self.assertNotIn("IT12345678901", texto(xml, "NIF"))
