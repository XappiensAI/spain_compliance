# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""*SII Registro*: un registro por factura con su estado en la AEAT.

Flujo:

1. Al validar una factura de una compañía con *SII Configuracion* activa (y fecha
   contable desde la fecha de inicio) se crea su registro en *Pendiente*.
2. :func:`enviar` agrupa por compañía, libro y tipo de comunicación, construye el
   XML desde el libro de IVA y lo manda. La respuesta de cada línea fija el estado.
   Lo que ya consta en la AEAT (aceptado o duplicado) se reenvía como modificación
   (``A1``).
3. Al cancelar una factura comunicada, el registro pasa a *Baja pendiente*; la baja
   se envía a mano.
4. :func:`consultar` y :func:`sincronizar_periodo` leen lo que tiene la AEAT, por
   factura o por periodo, y sirven para recoger lo comunicado por otro programa.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today
from frappe.utils.synchronization import filelock

from spain_compliance.contabilidad.identificacion import normalizar_identificador
from spain_compliance.contabilidad.sii import xml as sii_xml
from spain_compliance.contabilidad.sii.constantes import (
	ACEPTADO,
	ACEPTADO_ERRORES,
	BAJA_PENDIENTE,
	CODIGO_DUPLICADO,
	DADO_DE_BAJA,
	ENTORNO_PRODUCCION,
	ENTORNO_PRUEBAS,
	ERROR_COMUNICACION,
	ERROR_DATOS,
	ESTADO_CONSULTA,
	ESTADO_LINEA,
	ESTADOS_COMUNICADOS,
	ESTADOS_ENVIABLES,
	MAX_INTENTOS_AUTO,
	NO_APLICA,
	PENDIENTE,
	RECHAZADO,
)
from spain_compliance.contabilidad.sii.datos import DOCTYPE_LIBRO, datos_factura, titular
from spain_compliance.contabilidad.sii.fechas import fecha_limite
from spain_compliance.contabilidad.sii.transporte import ErrorComunicacion, llamar

DOCTYPE = "SII Registro"
CONFIG = "SII Configuracion"
DOCTYPES = tuple(DOCTYPE_LIBRO)


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


def get_config(company: str | None):
	if not company or not frappe.db.exists(CONFIG, company):
		return None
	return frappe.get_cached_doc(CONFIG, company)


def config_activa(company: str | None):
	cfg = get_config(company)
	return cfg if cfg and cint(cfg.activo) else None


def aplica(doctype: str, company: str, posting_date) -> bool:
	"""La factura entra en el SII de Frappe (configuración activa y fecha desde el inicio)."""
	cfg = config_activa(company)
	if not cfg or doctype not in DOCTYPE_LIBRO:
		return False
	if doctype == "Purchase Invoice" and not cint(cfg.incluir_recibidas):
		return False
	return bool(cfg.fecha_inicio) and getdate(posting_date) >= getdate(cfg.fecha_inicio)


def _sello(cfg) -> bool:
	return bool(cint(cfg.get("certificado_sello")))


# ---------------------------------------------------------------------------
# Registros
# ---------------------------------------------------------------------------


def buscar_registro(doctype: str, name: str) -> str | None:
	return frappe.db.get_value(DOCTYPE, {"documento_tipo": doctype, "documento": name}, "name")


def _evento(reg, accion: str, resultado: str, entorno: str | None = None, **kw):
	reg.append(
		"eventos",
		{
			"fecha": now_datetime(),
			"accion": accion,
			"entorno": entorno or reg.entorno,
			"resultado": resultado,
			"csv": kw.get("csv"),
			"codigo": kw.get("codigo"),
			"mensaje": (kw.get("mensaje") or "")[:1000] or None,
			"usuario": frappe.session.user,
		},
	)


def _rellenar_cabecera(reg, f: dict):
	reg.update(
		{
			"company": f["company"],
			"libro": f["libro"],
			"numero_factura": f["numero"],
			"tercero": (f.get("tercero") or "")[:140],
			"nif": (f["contraparte"].get("nif") or (f["contraparte"].get("id_otro") or {}).get("id")),
			"fecha_expedicion": f["fecha_expedicion"],
			"fecha_contable": f["fecha_contable"],
			"ejercicio": f["ejercicio"],
			"periodo": f["periodo"],
			"importe_total": f["importe_total"],
			"fecha_limite": fecha_limite(
				f["fecha_expedicion"] if f["libro"] == "Expedidas" else f["fecha_contable"],
				f["fecha_contable"],
			),
		}
	)


def crear_registro(
	doctype: str, name: str, origen: str = "Frappe", estado: str = PENDIENTE, lineas: list | None = None
):
	"""Crea el registro de la factura (o devuelve el que ya hay).

	``lineas`` son las de la factura en el libro de IVA; si no se pasan se calculan,
	para que importe, NIF y plazo salgan igual que en el envío.
	"""
	existente = buscar_registro(doctype, name)
	if existente:
		return frappe.get_doc(DOCTYPE, existente)
	company = frappe.db.get_value(doctype, name, "company")
	cfg = get_config(company)
	f = datos_factura(doctype, name, cfg, lineas=lineas)
	reg = frappe.new_doc(DOCTYPE)
	reg.documento_tipo = doctype
	reg.documento = name
	reg.estado = estado
	reg.origen = origen
	reg.tipo_comunicacion = "A0"
	_rellenar_cabecera(reg, f)
	reg.flags.ignore_permissions = True
	try:
		reg.insert()
	except frappe.DuplicateEntryError:
		# Otro proceso lo acaba de crear.
		frappe.clear_last_message()
		return frappe.get_doc(DOCTYPE, buscar_registro(doctype, name))
	return reg


def on_submit(doc, method=None):
	"""Hook de Sales/Purchase Invoice: crea el registro pendiente si aplica el SII."""
	try:
		if not aplica(doc.doctype, doc.company, doc.posting_date):
			return
		reg = buscar_registro(doc.doctype, doc.name)
		if reg:
			r = frappe.get_doc(DOCTYPE, reg)
			if r.estado == DADO_DE_BAJA:
				r.estado = PENDIENTE
				_evento(r, _("Validada de nuevo"), PENDIENTE)
				r.save(ignore_permissions=True)
			return
		crear_registro(doc.doctype, doc.name)
	except Exception:
		# El SII nunca bloquea la validación de la factura.
		frappe.log_error(title=f"SII: registro de {doc.name}")


def on_cancel(doc, method=None):
	"""Comunicada → *Baja pendiente*. Sin comunicar → se borra el registro."""
	reg = buscar_registro(doc.doctype, doc.name)
	if not reg:
		return
	r = frappe.get_doc(DOCTYPE, reg)
	# Con un error de comunicación la AEAT puede haberla registrado (respuesta
	# ilegible): se pide la baja en vez de perder el rastro.
	quiza_comunicada = r.estado == ERROR_COMUNICACION and cint(r.intentos) > 0
	if r.estado in ESTADOS_COMUNICADOS or r.tipo_comunicacion == "A1" or quiza_comunicada:
		if r.estado in (BAJA_PENDIENTE, DADO_DE_BAJA):
			return
		r.estado = BAJA_PENDIENTE
		_evento(r, _("Factura cancelada"), BAJA_PENDIENTE, mensaje=_("Hay que enviar la baja a la AEAT."))
		r.save(ignore_permissions=True)
	elif r.estado not in (BAJA_PENDIENTE, DADO_DE_BAJA):
		frappe.delete_doc(DOCTYPE, r.name, ignore_permissions=True, force=True)


def generar_registros(company: str) -> int:
	"""Registros pendientes para las facturas validadas desde la fecha de inicio que no tienen."""
	cfg = config_activa(company)
	if not cfg or not cfg.fecha_inicio:
		return 0
	creados = 0
	with filelock(f"sii_generar_{frappe.scrub(company)}", timeout=600):
		creados = _generar(company, cfg)
	return creados


def _generar(company: str, cfg) -> int:
	creados = 0
	for doctype in DOCTYPES:
		if doctype == "Purchase Invoice" and not cint(cfg.incluir_recibidas):
			continue
		filas = frappe.db.sql(
			f"""
			SELECT d.name, d.posting_date FROM `tab{doctype}` d
			LEFT JOIN `tab{DOCTYPE}` r ON r.documento_tipo = %(dt)s AND r.documento = d.name
			WHERE d.company = %(company)s AND d.docstatus = 1 AND d.posting_date >= %(inicio)s
				AND r.name IS NULL
			ORDER BY d.posting_date, d.name
			""",
			{"dt": doctype, "company": company, "inicio": cfg.fecha_inicio},
			as_dict=True,
		)
		if not filas:
			continue
		# Una sola lectura del libro de IVA para todas las facturas nuevas.
		lineas = _lineas_por_documento(
			company, DOCTYPE_LIBRO[doctype], [frappe._dict(fecha_contable=f.posting_date) for f in filas]
		)
		for name in (f.name for f in filas):
			try:
				crear_registro(doctype, name, lineas=lineas.get((doctype, name), []))
				creados += 1
			except Exception:
				frappe.log_error(title=f"SII: registro de {name}")
	return creados


def reiniciar_por_cambio_de_entorno(company: str, anterior: str, nuevo: str) -> int:
	"""Al pasar de Pruebas a Producción lo comunicado en Pruebas vuelve a Pendiente."""
	if anterior != ENTORNO_PRUEBAS or nuevo != ENTORNO_PRODUCCION:
		return 0
	nombres = frappe.get_all(
		DOCTYPE,
		filters={
			"company": company,
			"entorno": ENTORNO_PRUEBAS,
			"estado": ("not in", [BAJA_PENDIENTE, DADO_DE_BAJA, NO_APLICA]),
		},
		pluck="name",
	)
	for name in nombres:
		r = frappe.get_doc(DOCTYPE, name)
		r.update(
			{
				"estado": PENDIENTE,
				"tipo_comunicacion": "A0",
				"csv": None,
				"codigo_error": None,
				"descripcion_error": None,
				"estado_aeat": None,
				"estado_cuadre": None,
				"intentos": 0,
			}
		)
		_evento(
			r,
			_("Cambio a Producción"),
			PENDIENTE,
			entorno=nuevo,
			mensaje=_("Lo enviado a Pruebas no cuenta."),
		)
		r.save(ignore_permissions=True)
	return len(nombres)


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------


def _lineas_por_documento(company: str, libro: str, regs: list) -> dict[tuple, list]:
	from spain_compliance.contabilidad.libro_iva import movimientos_iva

	fechas = [getdate(r.fecha_contable) for r in regs if r.fecha_contable]
	if not fechas:
		return {}
	out: dict[tuple, list] = defaultdict(list)
	for ln in movimientos_iva(company, min(fechas), max(fechas), libro):
		out[(ln["voucher_type"], ln["voucher_no"])].append(ln)
	return out


def _tipo_comunicacion(reg) -> str:
	"""A1 si la AEAT ya tiene la factura: aceptada ahora o comunicada antes.

	No basta con el estado: un A1 rechazado deja el registro en *Rechazado* y el
	reenvío tiene que seguir siendo A1.
	"""
	return "A1" if reg.estado in ESTADOS_COMUNICADOS or reg.tipo_comunicacion == "A1" else "A0"


def _marcar(reg, estado: str, accion: str, entorno: str, **kw):
	reg.estado = estado
	reg.entorno = entorno
	reg.codigo_error = kw.get("codigo")
	reg.descripcion_error = kw.get("mensaje")
	if kw.get("csv"):
		reg.csv = kw["csv"]
	if "xml" in kw:
		reg.xml_enviado = kw["xml"]
	if "respuesta" in kw:
		reg.respuesta = kw["respuesta"]
	_evento(
		reg, accion, estado, entorno, csv=kw.get("csv"), codigo=kw.get("codigo"), mensaje=kw.get("mensaje")
	)
	reg.save(ignore_permissions=True)


def _clave_linea(numero: str | None, nif: str | None, libro: str) -> tuple:
	numero = (numero or "").strip().upper()
	return (numero, normalizar_identificador(nif)) if libro == "Recibidas" else (numero,)


def _procesar_respuesta(
	regs_datos: list[tuple],
	resp: dict,
	libro: str,
	entorno: str,
	accion: str,
	baja: bool,
	accion_tipo: str | None,
) -> list[tuple]:
	"""Fija el estado de cada registro. Devuelve los que hay que reenviar como A1."""
	por_clave = {}
	for reg, f in regs_datos:
		nif = None
		if libro == "Recibidas" and f.get("tipo_factura") != "F5":
			cp = f["contraparte"]
			nif = cp.get("nif") or (cp.get("id_otro") or {}).get("id")
		por_clave[_clave_linea(f["numero"], nif, libro)] = (reg, f)
	vistos = set()
	reintentar: list[tuple] = []
	for ln in resp["lineas"]:
		clave = _clave_linea(ln.get("numero"), ln.get("nif_emisor"), libro)
		par = por_clave.get(clave)
		if not par and libro == "Recibidas":
			# DUA (F5) o identificador escrito distinto: basta el número.
			par = next((v for k, v in por_clave.items() if k[0] == clave[0]), None)
		if not par:
			continue
		reg, _f = par
		vistos.add(reg.name)
		estado = ESTADO_LINEA.get(ln.get("estado") or "", RECHAZADO)
		mensaje = ln.get("descripcion")
		codigo = ln.get("codigo")
		dup = ln.get("duplicado")
		if estado == RECHAZADO and not baja and (codigo == CODIGO_DUPLICADO or dup):
			previo = ESTADO_CONSULTA.get((dup or {}).get("estado") or "Correcta")
			if accion_tipo == "A0" and previo in (*ESTADOS_COMUNICADOS, DADO_DE_BAJA):
				# Ya la tiene la AEAT (quizá con otros datos, p. ej. de otro programa) o
				# la tiene anulada: se reenvía como modificación para que quede lo de Frappe.
				vistos.add(reg.name)
				_evento(
					reg,
					accion,
					_("Ya constaba"),
					entorno,
					csv=ln.get("csv"),
					codigo=codigo,
					mensaje=_("La AEAT ya la tenía ({0}). Se reenvía como modificación (A1).").format(
						(dup or {}).get("estado") or "Correcta"
					),
				)
				reintentar.append(par)
				continue
		if baja:
			if estado in ESTADOS_COMUNICADOS:
				estado = DADO_DE_BAJA
			else:
				# La baja sigue pendiente: se ve el error y se puede reintentar.
				estado = BAJA_PENDIENTE
		if estado in ESTADOS_COMUNICADOS:
			reg.tipo_comunicacion = "A1" if not baja else reg.tipo_comunicacion
		_marcar(
			reg,
			estado,
			accion,
			entorno,
			csv=(ln.get("csv") or resp.get("csv"))
			if estado in (ACEPTADO, ACEPTADO_ERRORES, DADO_DE_BAJA)
			else None,
			codigo=codigo,
			mensaje=mensaje,
			respuesta=ln.get("xml"),
		)
	for reg, _f in regs_datos:
		if reg.name not in vistos:
			_marcar(
				reg,
				BAJA_PENDIENTE if baja else ERROR_COMUNICACION,
				accion,
				entorno,
				mensaje=_("La respuesta de la AEAT no trae esta factura (estado del envío: {0}).").format(
					resp.get("estado_envio") or "?"
				),
			)
	return reintentar


def _enviar_grupo(
	company: str,
	libro: str,
	regs_datos: list[tuple],
	cfg,
	tipo: str | None,
	baja: bool = False,
	reintento: bool = False,
):
	"""Envía un lote. Si la AEAT rechaza el mensaje entero, reintenta factura a factura.

	``reintento`` = reenvío del mismo intento (por factura tras un Fault, o A1 tras
	un duplicado): no suma intentos.
	"""
	tit = titular(company, cfg)
	entorno = cfg.entorno
	facturas = [f for _r, f in regs_datos]
	if baja:
		mensaje = sii_xml.mensaje_baja(libro, tit, facturas)
		accion = _("Baja")
	else:
		mensaje = sii_xml.mensaje_alta(libro, tit, facturas, tipo)
		accion = _("Alta (A0)") if tipo == "A0" else _("Modificación (A1)")

	def xml_de(f):
		if len(facturas) == 1:
			return mensaje.decode()
		if baja:
			return sii_xml.mensaje_baja(libro, tit, [f]).decode()
		return sii_xml.mensaje_alta(libro, tit, [f], tipo).decode()

	for reg, f in regs_datos:
		if not reintento:
			reg.intentos = cint(reg.intentos) + 1
		reg.fecha_envio = now_datetime()
		reg.tipo_comunicacion = tipo or reg.tipo_comunicacion
		reg.xml_enviado = xml_de(f)

	try:
		contenido = llamar(company, libro, mensaje, entorno, _sello(cfg), cfg.get("certificado") or None)
		resp = sii_xml.leer_respuesta_envio(contenido)
	except ErrorComunicacion as e:
		for reg, _f in regs_datos:
			_marcar(reg, BAJA_PENDIENTE if baja else ERROR_COMUNICACION, accion, entorno, mensaje=str(e))
		return
	except sii_xml.RespuestaInvalida as e:
		if e.codigo and len(regs_datos) > 1:
			# SOAP Fault: la AEAT no ha procesado el lote. Se reintenta por factura
			# para que solo falle la que tiene el problema.
			for par in regs_datos:
				_enviar_grupo(company, libro, [par], cfg, tipo, baja, reintento=True)
			return
		# Fault → rechazado. Respuesta ilegible → la AEAT puede haberlo registrado:
		# error de comunicación, y el reintento saldrá como duplicado (aceptado).
		estado = RECHAZADO if e.codigo else ERROR_COMUNICACION
		if baja:
			estado = BAJA_PENDIENTE
		for reg, _f in regs_datos:
			_marcar(reg, estado, accion, entorno, codigo=e.codigo, mensaje=str(e))
		return
	except frappe.ValidationError as e:
		# Sin certificado vigente, etc.
		for reg, _f in regs_datos:
			_marcar(reg, BAJA_PENDIENTE if baja else ERROR_COMUNICACION, accion, entorno, mensaje=str(e))
		return
	reintentar = _procesar_respuesta(regs_datos, resp, libro, entorno, accion, baja, tipo)
	if reintentar:
		_enviar_grupo(company, libro, reintentar, cfg, "A1", reintento=True)


def enviar(nombres: list[str], modificar: bool = False) -> dict:
	"""Envía los registros indicados. ``modificar`` reenvía también los aceptados (A1).

	Devuelve el número de registros por estado final.
	"""
	regs = [frappe.get_doc(DOCTYPE, n) for n in dict.fromkeys(nombres)]
	grupos: dict[tuple, list] = defaultdict(list)
	omitidos = 0
	for r in regs:
		cancelada = frappe.db.get_value(r.documento_tipo, r.documento, "docstatus") == 2
		if r.estado == BAJA_PENDIENTE or (cancelada and r.estado in ESTADOS_ENVIABLES):
			# Una factura cancelada solo puede darse de baja, nunca de alta.
			grupos[(r.company, r.libro, "baja")].append(r)
		elif r.estado in ESTADOS_ENVIABLES or (modificar and r.estado == ACEPTADO):
			grupos[(r.company, r.libro, "alta")].append(r)
		else:
			omitidos += 1

	for (company, libro, operacion), lista in grupos.items():
		cfg = get_config(company)
		if not cfg:
			frappe.throw(_("La compañía {0} no tiene configuración SII.").format(company))
		with filelock(f"sii_{frappe.scrub(company)}_{libro}", timeout=300):
			lineas = _lineas_por_documento(company, libro, lista) if operacion == "alta" else {}
			por_tipo: dict[str | None, list] = defaultdict(list)
			for r in lista:
				r.reload()
				f = datos_factura(
					r.documento_tipo, r.documento, cfg, lineas=lineas.get((r.documento_tipo, r.documento), [])
				)
				if operacion == "baja":
					por_tipo[None].append((r, f))
					continue
				_rellenar_cabecera(r, f)
				if f["no_aplica"]:
					_marcar(
						r,
						DADO_DE_BAJA if r.estado in ESTADOS_COMUNICADOS else NO_APLICA,
						_("Comprobación"),
						cfg.entorno,
						mensaje=_("Solo tiene operaciones no sujetas: no se comunica al SII."),
					)
					continue
				if f["errores"]:
					_marcar(r, ERROR_DATOS, _("Comprobación"), cfg.entorno, mensaje="\n".join(f["errores"]))
					continue
				por_tipo[_tipo_comunicacion(r)].append((r, f))
			lote = max(1, min(cint(cfg.tamano_lote) or 200, 10000))
			for tipo, pares in por_tipo.items():
				for i in range(0, len(pares), lote):
					_enviar_grupo(company, libro, pares[i : i + lote], cfg, tipo, baja=operacion == "baja")
					frappe.db.commit()

	resumen: dict[str, int] = defaultdict(int)
	for r in regs:
		resumen[frappe.db.get_value(DOCTYPE, r.name, "estado")] += 1
	return {"estados": dict(resumen), "omitidos": omitidos}


def vista_previa(doctype: str, name: str) -> dict:
	"""XML que se enviaría y los errores de datos, sin enviar nada."""
	company = frappe.db.get_value(doctype, name, "company")
	cfg = get_config(company)
	f = datos_factura(doctype, name, cfg)
	reg = buscar_registro(doctype, name)
	tipo = _tipo_comunicacion(frappe.get_doc(DOCTYPE, reg)) if reg else "A0"
	xml = None
	if not f["errores"] and not f["no_aplica"]:
		xml = sii_xml.mensaje_alta(f["libro"], titular(company, cfg), [f], tipo).decode()
	return {"errores": f["errores"], "no_aplica": f["no_aplica"], "tipo_comunicacion": tipo, "xml": xml}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------


def _consultar_factura(f: dict, cfg, entorno: str) -> dict | None:
	tit = titular(f["company"], cfg)
	msg = sii_xml.mensaje_consulta(f["libro"], tit, f["ejercicio"], f["periodo"], factura=f)
	contenido = llamar(f["company"], f["libro"], msg, entorno, _sello(cfg), cfg.get("certificado") or None)
	resp = sii_xml.leer_respuesta_consulta(contenido)
	numero = (f["numero"] or "").strip().upper()
	for r in resp["registros"]:
		if (r.get("numero") or "").strip().upper() == numero:
			return r
	return None


def _aplicar_consulta(reg, encontrado: dict | None, entorno: str):
	reg.fecha_consulta = now_datetime()
	if not encontrado:
		reg.estado_aeat = _("No consta")
		reg.estado_cuadre = None
		mensaje = None
		if reg.estado == BAJA_PENDIENTE and entorno == reg.entorno:
			# Nada que anular en la AEAT.
			reg.estado = DADO_DE_BAJA
			mensaje = _("La AEAT no la tiene: no hace falta la baja.")
		_evento(reg, _("Consulta"), _("No consta en la AEAT"), entorno, mensaje=mensaje)
		reg.save(ignore_permissions=True)
		return
	reg.estado_aeat = encontrado.get("estado")
	reg.estado_cuadre = encontrado.get("cuadre")
	if encontrado.get("csv") and not reg.csv:
		reg.csv = encontrado["csv"]
	nuevo = ESTADO_CONSULTA.get(encontrado.get("estado") or "")
	if nuevo and reg.estado not in (BAJA_PENDIENTE,):
		reg.estado = nuevo
		reg.entorno = entorno
		if nuevo in ESTADOS_COMUNICADOS:
			reg.tipo_comunicacion = "A1"
		reg.codigo_error = encontrado.get("codigo")
		reg.descripcion_error = encontrado.get("descripcion")
	_evento(
		reg,
		_("Consulta"),
		encontrado.get("estado") or "?",
		entorno,
		csv=encontrado.get("csv"),
		codigo=encontrado.get("codigo"),
		mensaje=" · ".join(
			x
			for x in (
				encontrado.get("descripcion"),
				_("Cuadre: {0}").format(encontrado["cuadre"]) if encontrado.get("cuadre") else None,
			)
			if x
		),
	)
	reg.save(ignore_permissions=True)


def consultar_documento(doctype: str, name: str, entorno: str | None = None) -> dict:
	"""Consulta una factura en la AEAT y actualiza (o crea) su registro.

	Si ``entorno`` no es el de la configuración, solo se devuelve el resultado.
	"""
	company = frappe.db.get_value(doctype, name, "company")
	cfg = get_config(company)
	if not cfg:
		frappe.throw(_("La compañía {0} no tiene configuración SII.").format(company))
	entorno = entorno or cfg.entorno
	f = datos_factura(doctype, name, cfg, lineas=[])
	if not f["numero"]:
		frappe.throw(_("La factura no tiene número para consultar."))
	try:
		encontrado = _consultar_factura(f, cfg, entorno)
	except (ErrorComunicacion, sii_xml.RespuestaInvalida) as e:
		return {"ok": False, "error": str(e), "entorno": entorno}
	reg_name = buscar_registro(doctype, name)
	if entorno == cfg.entorno:
		if reg_name:
			_aplicar_consulta(frappe.get_doc(DOCTYPE, reg_name), encontrado, entorno)
		elif encontrado and ESTADO_CONSULTA.get(encontrado.get("estado") or ""):
			reg = crear_registro(doctype, name, origen="Consulta AEAT")
			_aplicar_consulta(reg, encontrado, entorno)
			reg_name = reg.name
	return {"ok": True, "entorno": entorno, "encontrado": encontrado, "registro": reg_name}


def consultar(nombres: list[str]) -> dict:
	resumen: dict[str, int] = defaultdict(int)
	errores = []
	for n in dict.fromkeys(nombres):
		dt, doc = frappe.db.get_value(DOCTYPE, n, ["documento_tipo", "documento"])
		r = consultar_documento(dt, doc)
		if not r["ok"]:
			errores.append(f"{doc}: {r['error']}")
			continue
		resumen[frappe.db.get_value(DOCTYPE, n, "estado")] += 1
		frappe.db.commit()
	return {"estados": dict(resumen), "errores": errores}


def _factura_local(company: str, libro: str, numero: str, nif_emisor: str | None) -> tuple | None:
	if libro == "Expedidas":
		name = frappe.db.get_value(
			"Sales Invoice", {"name": numero, "company": company, "docstatus": ("!=", 0)}
		)
		return ("Sales Invoice", name) if name else None
	candidatos = frappe.db.sql(
		"""
		SELECT pi.name, s.tax_id FROM `tabPurchase Invoice` pi
		JOIN `tabSupplier` s ON s.name = pi.supplier
		WHERE pi.company = %s AND pi.docstatus != 0 AND UPPER(TRIM(pi.bill_no)) = %s
		""",
		(company, numero.strip().upper()),
		as_dict=True,
	)
	nif = normalizar_identificador(nif_emisor)
	for c in candidatos:
		t = normalizar_identificador(c.tax_id)
		if t == nif or t.endswith(nif) or nif.endswith(t):
			return ("Purchase Invoice", c.name)
	return ("Purchase Invoice", candidatos[0].name) if len(candidatos) == 1 else None


def sincronizar_periodo(
	company: str, libro: str, ejercicio: str, periodo: str, entorno: str | None = None
) -> dict:
	"""Lee de la AEAT todo lo registrado en un periodo y lo cruza con las facturas de Frappe.

	Con el entorno de la configuración actualiza los registros (y crea los de las
	facturas que la AEAT ya tiene). Con otro entorno solo informa.
	"""
	cfg = get_config(company)
	if not cfg:
		frappe.throw(_("La compañía {0} no tiene configuración SII.").format(company))
	entorno = entorno or cfg.entorno
	tit = titular(company, cfg)
	en_aeat: list[dict] = []
	paginacion = None
	for _pagina in range(200):
		msg = sii_xml.mensaje_consulta(libro, tit, ejercicio, periodo, paginacion=paginacion)
		try:
			resp = sii_xml.leer_respuesta_consulta(
				llamar(company, libro, msg, entorno, _sello(cfg), cfg.get("certificado") or None)
			)
		except (ErrorComunicacion, sii_xml.RespuestaInvalida) as e:
			return {"ok": False, "error": str(e), "entorno": entorno, "leidas": len(en_aeat)}
		en_aeat += resp["registros"]
		if not resp["paginacion"] or not resp["registros"]:
			break
		ult = resp["registros"][-1]
		paginacion = {**(ult.get("emisor") or {}), "numero": ult.get("numero"), "fecha": ult.get("fecha")}

	persistir = entorno == cfg.entorno
	sin_factura, coinciden, actualizados = [], 0, 0
	vistos = set()
	for r in en_aeat:
		local = _factura_local(company, libro, r.get("numero") or "", r.get("nif_emisor"))
		if not local or not local[1]:
			sin_factura.append(
				{"numero": r.get("numero"), "nif": r.get("nif_emisor"), "estado": r.get("estado")}
			)
			continue
		coinciden += 1
		vistos.add(local)
		if not persistir:
			continue
		reg_name = buscar_registro(*local)
		if reg_name:
			_aplicar_consulta(frappe.get_doc(DOCTYPE, reg_name), r, entorno)
		elif ESTADO_CONSULTA.get(r.get("estado") or ""):
			_aplicar_consulta(crear_registro(*local, origen="Consulta AEAT"), r, entorno)
		actualizados += 1

	doctype = "Sales Invoice" if libro == "Expedidas" else "Purchase Invoice"
	desde = getdate(f"{ejercicio}-{periodo}-01")
	hasta = frappe.utils.get_last_day(desde)
	locales = frappe.get_all(
		doctype,
		filters={"company": company, "docstatus": 1, "posting_date": ("between", [desde, hasta])},
		pluck="name",
	)
	no_en_aeat = [n for n in locales if (doctype, n) not in vistos]
	if persistir:
		for n in no_en_aeat:
			reg_name = buscar_registro(doctype, n)
			if reg_name:
				reg = frappe.get_doc(DOCTYPE, reg_name)
				_aplicar_consulta(reg, None, entorno)
	frappe.db.commit()
	return {
		"ok": True,
		"entorno": entorno,
		"en_aeat": len(en_aeat),
		"coinciden": coinciden,
		"actualizados": actualizados,
		"sin_factura_local": sin_factura[:200],
		"no_en_aeat": no_en_aeat[:500],
		"total_no_en_aeat": len(no_en_aeat),
	}


# ---------------------------------------------------------------------------
# Tareas programadas
# ---------------------------------------------------------------------------


def pendientes(company: str, automatico: bool = False) -> list[str]:
	filtros = {"company": company, "estado": ("in", [PENDIENTE, ERROR_COMUNICACION])}
	nombres = frappe.get_all(
		DOCTYPE, filters=filtros, fields=["name", "estado", "intentos"], order_by="fecha_contable"
	)
	return [
		n.name
		for n in nombres
		if not (automatico and n.estado == ERROR_COMUNICACION and cint(n.intentos) >= MAX_INTENTOS_AUTO)
	]


def enviar_pendientes(company: str, automatico: bool = False) -> dict:
	generar_registros(company)
	frappe.db.commit()
	nombres = pendientes(company, automatico)
	if not nombres:
		return {"estados": {}, "omitidos": 0}
	return enviar(nombres)


def tarea_envio_automatico():
	"""Cada 15 minutos: compañías con SII activo y envío automático."""
	for cfg in frappe.get_all(CONFIG, filters={"activo": 1, "envio_automatico": 1}, pluck="name"):
		frappe.enqueue(
			"spain_compliance.contabilidad.sii.registro.enviar_pendientes",
			queue="long",
			job_id=f"sii-envio-{frappe.scrub(cfg)}",
			deduplicate=True,
			company=cfg,
			automatico=True,
		)


def resumen(company: str) -> dict:
	"""Contadores por libro y estado, y registros fuera de plazo."""
	filas = frappe.db.sql(
		f"""
		SELECT libro, estado, COUNT(*) AS n,
			SUM(CASE WHEN estado IN %(abiertos)s AND fecha_limite < %(hoy)s THEN 1 ELSE 0 END) AS vencidos,
			SUM(CASE WHEN estado IN %(abiertos)s AND fecha_limite = %(hoy)s THEN 1 ELSE 0 END) AS vencen_hoy
		FROM `tab{DOCTYPE}` WHERE company = %(company)s
		GROUP BY libro, estado
		""",
		{
			"company": company,
			"hoy": today(),
			"abiertos": (PENDIENTE, ERROR_COMUNICACION, ERROR_DATOS, RECHAZADO),
		},
		as_dict=True,
	)
	out: dict = {"Expedidas": {}, "Recibidas": {}, "vencidos": 0, "vencen_hoy": 0}
	for f in filas:
		out[f.libro][f.estado] = cint(f.n)
		out["vencidos"] += cint(f.vencidos)
		out["vencen_hoy"] += cint(f.vencen_hoy)
	return out
