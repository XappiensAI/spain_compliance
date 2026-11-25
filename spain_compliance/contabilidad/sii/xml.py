# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Mensajes SOAP del SII y lectura de las respuestas de la AEAT.

Se construyen con ``lxml`` siguiendo el orden de elementos de los XSD de la
versión 1.1 (SuministroLR, SuministroInformacion y ConsultaLR). No hace falta
firma XML: el SII autentica con el certificado en la conexión TLS.
"""

from __future__ import annotations

from datetime import date

from frappe.utils import flt, getdate
from lxml import etree

from spain_compliance.contabilidad.sii.constantes import NS_LR, NS_LRC, NS_SII, NS_SOAP, VERSION_SII

NSMAP = {"soapenv": NS_SOAP, "siiLR": NS_LR, "sii": NS_SII, "siiLRC": NS_LRC}


class RespuestaInvalida(Exception):
	"""La AEAT devolvió algo que no es una respuesta SII (HTML, SOAP Fault...)."""

	def __init__(self, mensaje: str, codigo: str | None = None):
		super().__init__(mensaje)
		self.codigo = codigo


def _sub(padre, ns: str, tag: str, texto=None):
	el = etree.SubElement(padre, f"{{{ns}}}{tag}")
	if texto is not None:
		el.text = str(texto)
	return el


def _s(padre, tag, texto=None):
	return _sub(padre, NS_SII, tag, texto)


def fecha_sii(valor) -> str:
	d = getdate(valor) if not isinstance(valor, date) else valor
	return d.strftime("%d-%m-%Y")


def num(valor) -> str:
	return f"{flt(valor, 2):.2f}"


def tasa(valor) -> str:
	v = flt(valor, 2)
	return f"{v:.2f}"


def _sobre(cuerpo_tag_ns: str, cuerpo_tag: str):
	env = etree.Element(f"{{{NS_SOAP}}}Envelope", nsmap=NSMAP)
	etree.SubElement(env, f"{{{NS_SOAP}}}Header")
	body = etree.SubElement(env, f"{{{NS_SOAP}}}Body")
	return env, _sub(body, cuerpo_tag_ns, cuerpo_tag)


def _cabecera(padre, titular: dict, tipo_comunicacion: str | None = None):
	cab = _s(padre, "Cabecera")
	_s(cab, "IDVersionSii", VERSION_SII)
	t = _s(cab, "Titular")
	_s(t, "NombreRazon", titular["nombre"])
	_s(t, "NIF", titular["nif"])
	if tipo_comunicacion:
		_s(cab, "TipoComunicacion", tipo_comunicacion)


def _periodo(padre, f: dict):
	p = _s(padre, "PeriodoLiquidacion")
	_s(p, "Ejercicio", f["ejercicio"])
	_s(p, "Periodo", f["periodo"])


def _identificacion(padre, cp: dict, con_nombre: bool = True):
	if con_nombre:
		_s(padre, "NombreRazon", cp.get("nombre") or "-")
	if cp.get("nif"):
		_s(padre, "NIF", cp["nif"])
	else:
		otro = _s(padre, "IDOtro")
		if cp["id_otro"].get("pais"):
			_s(otro, "CodigoPais", cp["id_otro"]["pais"])
		_s(otro, "IDType", cp["id_otro"]["tipo"])
		_s(otro, "ID", cp["id_otro"]["id"])


def _emisor(f: dict, titular: dict) -> dict:
	"""Quién expide la factura: el titular en emitidas y en DUA (F5), el proveedor en recibidas."""
	if f["libro"] == "Expedidas" or f.get("tipo_factura") == "F5":
		return {"nombre": titular["nombre"], "nif": titular["nif"]}
	return f["contraparte"]


def _id_factura(padre, ns: str, f: dict, titular: dict):
	idf = _sub(padre, ns, "IDFactura")
	em = _s(idf, "IDEmisorFactura")
	emisor = _emisor(f, titular)
	if f["libro"] == "Recibidas" and not emisor.get("nif"):
		_identificacion(em, emisor, con_nombre=False)
	else:
		_s(em, "NIF", emisor["nif"])
	_s(idf, "NumSerieFacturaEmisor", f["numero"])
	_s(idf, "FechaExpedicionFacturaEmisor", fecha_sii(f["fecha_expedicion"]))
	return idf


def _rectificativa(padre, f: dict):
	if not f["tipo_factura"].startswith("R"):
		return
	_s(padre, "TipoRectificativa", "I")
	if f.get("rectificada") and f["rectificada"].get("numero"):
		frs = _s(padre, "FacturasRectificadas")
		fr = _s(frs, "IDFacturaRectificada")
		_s(fr, "NumSerieFacturaEmisor", f["rectificada"]["numero"])
		_s(fr, "FechaExpedicionFacturaEmisor", fecha_sii(f["rectificada"]["fecha"]))


def _detalle_iva(padre, d: dict, campo_cuota: str, recibida: bool = False):
	det = _s(padre, "DetalleIVA")
	if d.get("exenta"):
		_s(det, "BaseImponible", num(d["base"]))
		return
	_s(det, "TipoImpositivo", tasa(d["tipo"]))
	_s(det, "BaseImponible", num(d["base"]))
	_s(det, campo_cuota, num(d["cuota"]))
	if d.get("tipo_re") is not None:
		_s(det, "TipoRecargoEquivalencia", tasa(d["tipo_re"]))
		_s(det, "CuotaRecargoEquivalencia", num(d.get("cuota_re")))
	if recibida and d.get("bien_inversion"):
		_s(det, "BienInversion", "S")


def _bloque_emitida(padre, b: dict):
	"""Sujeta (Exenta / NoExenta) y NoSujeta de un bloque del TipoDesglose."""
	if b["exentas"] or b["no_exentas"]:
		suj = _s(padre, "Sujeta")
		if b["exentas"]:
			ex = _s(suj, "Exenta")
			for causa, base in sorted(b["exentas"].items()):
				de = _s(ex, "DetalleExenta")
				_s(de, "CausaExencion", causa)
				_s(de, "BaseImponible", num(base))
		# El esquema solo admite un NoExenta: con S1 y S2 a la vez se informa S3.
		tipos = [t for t in ("S1", "S2") if b["no_exentas"].get(t)]
		if tipos:
			ne = _s(suj, "NoExenta")
			_s(ne, "TipoNoExenta", tipos[0] if len(tipos) == 1 else "S3")
			desg = _s(ne, "DesgloseIVA")
			for t in tipos:
				for d in b["no_exentas"][t]:
					_detalle_iva(desg, d, "CuotaRepercutida")
	if b["no_sujeta_7_14"] or b["no_sujeta_localizacion"]:
		ns = _s(padre, "NoSujeta")
		if b["no_sujeta_7_14"]:
			_s(ns, "ImportePorArticulos7_14_Otros", num(b["no_sujeta_7_14"]))
		if b["no_sujeta_localizacion"]:
			_s(ns, "ImporteTAIReglasLocalizacion", num(b["no_sujeta_localizacion"]))


def _factura_expedida(registro, f: dict):
	fe = _sub(registro, NS_LR, "FacturaExpedida")
	_s(fe, "TipoFactura", f["tipo_factura"])
	_rectificativa(fe, f)
	_s(fe, "ClaveRegimenEspecialOTrascendencia", f["clave_regimen"])
	_s(fe, "ImporteTotal", num(f["importe_total"]))
	_s(fe, "DescripcionOperacion", f["descripcion"])
	cp = _s(fe, "Contraparte")
	_identificacion(cp, f["contraparte"])
	td = _s(fe, "TipoDesglose")
	desglose = f["desglose"]
	if "DesgloseFactura" in desglose:
		_bloque_emitida(_s(td, "DesgloseFactura"), desglose["DesgloseFactura"])
	else:
		dto = _s(td, "DesgloseTipoOperacion")
		for tipo_op in ("PrestacionServicios", "Entrega"):
			if tipo_op in desglose:
				_bloque_emitida(_s(dto, tipo_op), desglose[tipo_op])


def _factura_recibida(registro, f: dict, titular: dict):
	fr = _sub(registro, NS_LR, "FacturaRecibida")
	_s(fr, "TipoFactura", f["tipo_factura"])
	_rectificativa(fr, f)
	_s(fr, "ClaveRegimenEspecialOTrascendencia", f["clave_regimen"])
	_s(fr, "ImporteTotal", num(f["importe_total"]))
	_s(fr, "DescripcionOperacion", f["descripcion"])
	df = _s(fr, "DesgloseFactura")
	if f.get("desglose_isp"):
		isp = _s(df, "InversionSujetoPasivo")
		for d in f["desglose_isp"]:
			_detalle_iva(isp, d, "CuotaSoportada")
	if f.get("desglose_iva"):
		di = _s(df, "DesgloseIVA")
		for d in f["desglose_iva"]:
			_detalle_iva(di, d, "CuotaSoportada", recibida=True)
	cp = _s(fr, "Contraparte")
	_identificacion(cp, _emisor(f, titular))
	_s(fr, "FechaRegContable", fecha_sii(f["fecha_contable"]))
	_s(fr, "CuotaDeducible", num(f.get("cuota_deducible")))


def mensaje_alta(libro: str, titular: dict, facturas: list[dict], tipo_comunicacion: str = "A0") -> bytes:
	"""SuministroLRFacturasEmitidas / SuministroLRFacturasRecibidas."""
	emitidas = libro == "Expedidas"
	env, cuerpo = _sobre(
		NS_LR, "SuministroLRFacturasEmitidas" if emitidas else "SuministroLRFacturasRecibidas"
	)
	_cabecera(cuerpo, titular, tipo_comunicacion)
	for f in facturas:
		reg = _sub(cuerpo, NS_LR, "RegistroLRFacturasEmitidas" if emitidas else "RegistroLRFacturasRecibidas")
		_periodo(reg, f)
		_id_factura(reg, NS_LR, f, titular)
		if emitidas:
			_factura_expedida(reg, f)
		else:
			_factura_recibida(reg, f, titular)
	return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def mensaje_baja(libro: str, titular: dict, facturas: list[dict]) -> bytes:
	"""BajaLRFacturasEmitidas / BajaLRFacturasRecibidas."""
	emitidas = libro == "Expedidas"
	env, cuerpo = _sobre(NS_LR, "BajaLRFacturasEmitidas" if emitidas else "BajaLRFacturasRecibidas")
	_cabecera(cuerpo, titular)
	for f in facturas:
		reg = _sub(cuerpo, NS_LR, "RegistroLRBajaExpedidas" if emitidas else "RegistroLRBajaRecibidas")
		_periodo(reg, f)
		_id_factura(reg, NS_LR, f, titular)
	return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def mensaje_consulta(
	libro: str,
	titular: dict,
	ejercicio: str,
	periodo: str,
	factura: dict | None = None,
	paginacion: dict | None = None,
) -> bytes:
	"""ConsultaLRFacturasEmitidas / ConsultaLRFacturasRecibidas de un periodo o de una factura."""
	emitidas = libro == "Expedidas"
	env, cuerpo = _sobre(NS_LRC, "ConsultaLRFacturasEmitidas" if emitidas else "ConsultaLRFacturasRecibidas")
	_cabecera(cuerpo, titular)
	filtro = _sub(cuerpo, NS_LRC, "FiltroConsulta")
	_periodo(filtro, {"ejercicio": ejercicio, "periodo": periodo})
	if factura:
		idf = _sub(filtro, NS_LRC, "IDFactura")
		if not emitidas:
			em = _s(idf, "IDEmisorFactura")
			_identificacion(em, _emisor(factura, titular))
		_s(idf, "NumSerieFacturaEmisor", factura["numero"])
		_s(idf, "FechaExpedicionFacturaEmisor", fecha_sii(factura["fecha_expedicion"]))
	if paginacion:
		cp = _sub(filtro, NS_LRC, "ClavePaginacion")
		em = _s(cp, "IDEmisorFactura")
		if paginacion.get("nif"):
			_s(em, "NIF", paginacion["nif"])
		elif paginacion.get("id_otro"):
			_identificacion(em, {"id_otro": paginacion["id_otro"]}, con_nombre=False)
		_s(cp, "NumSerieFacturaEmisor", paginacion["numero"])
		_s(cp, "FechaExpedicionFacturaEmisor", paginacion["fecha"])
	return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------


def _hijos(el, nombre: str) -> list:
	return [c for c in el.iter() if isinstance(c.tag, str) and etree.QName(c).localname == nombre]


def _texto(el, nombre: str) -> str | None:
	if el is None:
		return None
	for c in el.iter():
		if isinstance(c.tag, str) and etree.QName(c).localname == nombre:
			return (c.text or "").strip() or None
	return None


def _hijo_directo(el, nombre: str):
	for c in el:
		if isinstance(c.tag, str) and etree.QName(c).localname == nombre:
			return c
	return None


def _primero_con_prefijo(raiz, prefijo: str):
	"""Primer elemento cuyo nombre empieza por ``prefijo`` (la AEAT usa
	``RespuestaLRFacturasEmitidas``, ``RespuestaLRBajaFacturasRecibidas``...)."""
	for c in raiz.iter():
		if isinstance(c.tag, str) and etree.QName(c).localname.startswith(prefijo):
			return c
	return None


def _texto_directo(el, nombre: str) -> str | None:
	hijo = _hijo_directo(el, nombre)
	return (hijo.text or "").strip() or None if hijo is not None else None


def leer_xml(contenido: bytes | str):
	if isinstance(contenido, str):
		contenido = contenido.encode()
	try:
		raiz = etree.fromstring(contenido, parser=etree.XMLParser(resolve_entities=False, no_network=True))
	except etree.XMLSyntaxError:
		texto = contenido[:300].decode(errors="replace")
		raise RespuestaInvalida(f"La AEAT no devolvió XML: {texto}")
	falta = _hijos(raiz, "Fault")
	if falta:
		raise RespuestaInvalida(
			_texto(falta[0], "faultstring") or "SOAP Fault", _texto(falta[0], "faultcode")
		)
	return raiz


def _id_respuesta(el) -> dict:
	idf = _hijo_directo(el, "IDFactura")
	if idf is None:
		return {}
	em = _hijo_directo(idf, "IDEmisorFactura")
	otro = _hijo_directo(em, "IDOtro") if em is not None else None
	return {
		"nif_emisor": _texto(em, "NIF") or _texto(em, "ID"),
		# Para la ClavePaginacion: el emisor tal como lo devuelve la AEAT.
		"emisor": (
			{
				"id_otro": {
					"pais": _texto(otro, "CodigoPais"),
					"tipo": _texto(otro, "IDType"),
					"id": _texto(otro, "ID"),
				}
			}
			if otro is not None
			else {"nif": _texto(em, "NIF")}
		),
		"numero": _texto(idf, "NumSerieFacturaEmisor"),
		"fecha": _texto(idf, "FechaExpedicionFacturaEmisor"),
	}


def leer_respuesta_envio(contenido: bytes | str) -> dict:
	"""``{"csv", "estado_envio", "lineas": [{numero, nif_emisor, fecha, estado, codigo, descripcion, duplicado}]}``."""
	raiz = leer_xml(contenido)
	resp = _primero_con_prefijo(raiz, "RespuestaLR")
	if resp is None:
		raise RespuestaInvalida("Respuesta sin RespuestaLR de la AEAT")
	lineas = []
	for ln in [c for c in resp if isinstance(c.tag, str) and etree.QName(c).localname == "RespuestaLinea"]:
		dup = _hijo_directo(ln, "RegistroDuplicado")
		lineas.append(
			{
				**_id_respuesta(ln),
				"estado": _texto_directo(ln, "EstadoRegistro"),
				"codigo": _texto_directo(ln, "CodigoErrorRegistro"),
				"descripcion": _texto_directo(ln, "DescripcionErrorRegistro"),
				"csv": _texto_directo(ln, "CSV"),
				"xml": etree.tostring(ln, encoding="unicode", pretty_print=True),
				"duplicado": (
					{
						"estado": _texto(dup, "EstadoRegistroDuplicado") or _texto(dup, "EstadoRegistro"),
						"codigo": _texto(dup, "CodigoErrorRegistro"),
						"descripcion": _texto(dup, "DescripcionErrorRegistro"),
					}
					if dup is not None
					else None
				),
			}
		)
	return {
		"csv": _texto_directo(resp, "CSV"),
		"estado_envio": _texto_directo(resp, "EstadoEnvio"),
		"lineas": lineas,
	}


def leer_respuesta_consulta(contenido: bytes | str) -> dict:
	"""``{"paginacion": bool, "registros": [{numero, nif_emisor, fecha, estado, codigo, descripcion, csv, cuadre, ...}]}``."""
	raiz = leer_xml(contenido)
	resp = _primero_con_prefijo(raiz, "RespuestaConsultaLR")
	if resp is None:
		raise RespuestaInvalida("Respuesta sin RespuestaConsultaLR de la AEAT")
	registros = []
	for r in resp:
		if not isinstance(r.tag, str) or not etree.QName(r).localname.startswith("RegistroRespuestaConsulta"):
			continue
		estado = _hijo_directo(r, "EstadoFactura")
		pres = _hijo_directo(r, "DatosPresentacion")
		datos = _hijo_directo(r, "DatosFacturaEmitida")
		if datos is None:
			datos = _hijo_directo(r, "DatosFacturaRecibida")
		registros.append(
			{
				**_id_respuesta(r),
				"estado": _texto(estado, "EstadoRegistro"),
				"cuadre": _texto(estado, "EstadoCuadre"),
				"codigo": _texto(estado, "CodigoErrorRegistro"),
				"descripcion": _texto(estado, "DescripcionErrorRegistro"),
				"modificado": _texto(estado, "TimestampUltimaModificacion"),
				"csv": _texto(pres, "CSV"),
				"presentado": _texto(pres, "TimestampPresentacion"),
				"importe_total": _texto(datos, "ImporteTotal"),
			}
		)
	return {
		"paginacion": (_texto(resp, "IndicadorPaginacion") or "N") == "S",
		"resultado": _texto(resp, "ResultadoConsulta"),
		"registros": registros,
	}
