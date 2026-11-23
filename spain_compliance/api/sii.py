# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""API del SII para las interfaces (portal /contabilidad, portales de cliente, Desk).

Leer: Accounts User, Accounts Manager y System Manager.
Enviar, consultar en la AEAT y generar registros: Accounts Manager y System Manager.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from spain_compliance.contabilidad.sii import registro as sii
from spain_compliance.contabilidad.sii.constantes import (
	BAJA_PENDIENTE,
	ERROR_COMUNICACION,
	ERROR_DATOS,
	ESTADOS,
	PENDIENTE,
	RECHAZADO,
)

ROLES_LECTURA = {"System Manager", "Accounts Manager", "Accounts User"}
ROLES_ENVIO = {"System Manager", "Accounts Manager"}
_SINCRONO_MAX = 50
_ABIERTOS = (PENDIENTE, ERROR_COMUNICACION, ERROR_DATOS, RECHAZADO)


def _roles() -> set:
	return set(frappe.get_roles())


def puede_leer() -> bool:
	return frappe.session.user == "Administrator" or bool(_roles() & ROLES_LECTURA)


def puede_enviar() -> bool:
	return frappe.session.user == "Administrator" or bool(_roles() & ROLES_ENVIO)


def _exigir_lectura():
	if not puede_leer():
		frappe.throw(_("No tiene permiso para ver el SII."), frappe.PermissionError)


def _exigir_envio():
	if not puede_enviar():
		frappe.throw(_("Solo Accounts Manager o System Manager pueden comunicar con la AEAT."), frappe.PermissionError)


def _lista(valor) -> list:
	if not valor:
		return []
	if isinstance(valor, str):
		try:
			valor = json.loads(valor)
		except ValueError:
			valor = [valor]
	return list(valor)


def _companias() -> list[str]:
	return frappe.get_all("Company", pluck="name", order_by="name")


@frappe.whitelist()
def resumen(company: str | None = None) -> dict:
	"""Configuración, contadores por libro/estado y permisos del usuario."""
	_exigir_lectura()
	companias = _companias()
	company = company or frappe.defaults.get_user_default("Company") or (companias[0] if companias else None)
	cfg = sii.get_config(company)
	certificado = None
	if cfg:
		from spain_compliance.contabilidad.certificados import buscar_certificado

		nombre = cfg.certificado or buscar_certificado(company, "sii")
		if nombre:
			certificado = frappe.db.get_value(
				"Certificado Digital", nombre, ["name", "titulo", "estado", "valido_hasta"], as_dict=True
			)
	return {
		"company": company,
		"companias": companias,
		"configurada": bool(cfg),
		"config": (
			{
				"activo": cint(cfg.activo),
				"entorno": cfg.entorno,
				"fecha_inicio": cfg.fecha_inicio,
				"envio_automatico": cint(cfg.envio_automatico),
				"incluir_recibidas": cint(cfg.incluir_recibidas),
				"certificado_sello": cint(cfg.certificado_sello),
			}
			if cfg
			else None
		),
		"certificado": certificado,
		"contadores": sii.resumen(company) if company else {},
		"estados": list(ESTADOS),
		"puede_enviar": puede_enviar(),
		"hoy": today(),
	}


@frappe.whitelist()
def registros(
	company: str,
	libro: str | None = None,
	estado: str | None = None,
	desde: str | None = None,
	hasta: str | None = None,
	search: str | None = None,
	vencidos: int | None = None,
	start: int = 0,
	limit: int = 200,
) -> dict:
	_exigir_lectura()
	filtros: dict = {"company": company}
	if libro:
		filtros["libro"] = libro
	if estado == "abiertos":
		filtros["estado"] = ("in", _ABIERTOS)
	elif estado:
		filtros["estado"] = estado
	if desde and hasta:
		filtros["fecha_contable"] = ("between", [getdate(desde), getdate(hasta)])
	elif desde:
		filtros["fecha_contable"] = (">=", getdate(desde))
	elif hasta:
		filtros["fecha_contable"] = ("<=", getdate(hasta))
	if cint(vencidos):
		filtros["estado"] = ("in", _ABIERTOS)
		filtros["fecha_limite"] = ("<", today())
	or_filtros = None
	if search:
		like = f"%{search.strip()}%"
		or_filtros = {"documento": ("like", like), "numero_factura": ("like", like), "tercero": ("like", like), "nif": ("like", like)}
	campos = [
		"name",
		"libro",
		"documento_tipo",
		"documento",
		"numero_factura",
		"tercero",
		"nif",
		"fecha_expedicion",
		"fecha_contable",
		"ejercicio",
		"periodo",
		"importe_total",
		"estado",
		"tipo_comunicacion",
		"entorno",
		"origen",
		"fecha_limite",
		"csv",
		"codigo_error",
		"descripcion_error",
		"fecha_envio",
		"intentos",
		"estado_aeat",
		"estado_cuadre",
		"fecha_consulta",
	]
	limit = max(1, min(cint(limit) or 200, 1000))
	filas = frappe.get_all(
		"SII Registro",
		filters=filtros,
		or_filters=or_filtros,
		fields=campos,
		order_by="fecha_contable desc, documento desc",
		start=cint(start),
		limit=limit,
		ignore_permissions=True,
	)
	total = len(
		frappe.get_all("SII Registro", filters=filtros, or_filters=or_filtros, pluck="name", ignore_permissions=True)
	) if or_filtros else frappe.db.count("SII Registro", filtros)
	hoy = getdate(today())
	for f in filas:
		f["vencido"] = bool(f.estado in _ABIERTOS and f.fecha_limite and getdate(f.fecha_limite) < hoy)
	return {"registros": filas, "total": total}


@frappe.whitelist()
def registro(name: str) -> dict:
	_exigir_lectura()
	doc = frappe.get_doc("SII Registro", name)
	d = doc.as_dict()
	d["eventos"] = sorted(d.get("eventos") or [], key=lambda e: e.get("fecha") or "", reverse=True)
	return d


def _registros_de_documentos(documentos: list, crear: bool) -> tuple[list[str], list[str]]:
	"""``[{"doctype", "name"}]`` → nombres de registro. Crea los que falten si aplica el SII."""
	nombres, avisos = [], []
	for d in documentos:
		if isinstance(d, str):
			d = {"doctype": "Sales Invoice", "name": d}
		doctype, name = d.get("doctype") or "Sales Invoice", d.get("name")
		if doctype not in sii.DOCTYPES:
			continue
		reg = sii.buscar_registro(doctype, name)
		if not reg and crear:
			company, posting_date, docstatus = frappe.db.get_value(
				doctype, name, ["company", "posting_date", "docstatus"]
			) or (None, None, None)
			if docstatus != 1:
				avisos.append(_("{0}: no está validada.").format(name))
				continue
			if not sii.aplica(doctype, company, posting_date):
				cfg = sii.get_config(company)
				if not cfg or not cint(cfg.activo):
					avisos.append(_("{0}: la compañía no tiene el SII activo.").format(name))
				else:
					avisos.append(
						_("{0}: es anterior a la fecha de inicio del SII ({1}). Use «Consultar».").format(
							name, frappe.format(cfg.fecha_inicio, "Date")
						)
					)
				continue
			reg = sii.crear_registro(doctype, name).name
		if reg:
			nombres.append(reg)
	return nombres, avisos


def _ejecutar(funcion: str, nombres: list[str], **kw) -> dict:
	if len(nombres) > _SINCRONO_MAX:
		frappe.enqueue(
			f"spain_compliance.contabilidad.sii.registro.{funcion}",
			queue="long",
			timeout=3600,
			nombres=nombres,
			**kw,
		)
		return {"encolado": True, "n": len(nombres)}
	return {"encolado": False, "n": len(nombres), **getattr(sii, funcion)(nombres, **kw)}


@frappe.whitelist(methods=["POST"])
def enviar(registros=None, documentos=None, modificar: int = 0) -> dict:
	"""Envía registros (por nombre) o facturas (``[{"doctype", "name"}]``) a la AEAT."""
	_exigir_envio()
	nombres = _lista(registros)
	avisos: list[str] = []
	if documentos:
		extra, avisos = _registros_de_documentos(_lista(documentos), crear=True)
		nombres += extra
	if not nombres:
		return {"encolado": False, "n": 0, "estados": {}, "avisos": avisos}
	out = _ejecutar("enviar", list(dict.fromkeys(nombres)), modificar=bool(cint(modificar)))
	out["avisos"] = avisos
	return out


@frappe.whitelist(methods=["POST"])
def enviar_pendientes(company: str) -> dict:
	"""Genera los registros que falten y envía todo lo pendiente de la compañía."""
	_exigir_envio()
	creados = sii.generar_registros(company)
	nombres = sii.pendientes(company)
	out = _ejecutar("enviar", nombres) if nombres else {"encolado": False, "n": 0, "estados": {}}
	out["creados"] = creados
	return out


@frappe.whitelist(methods=["POST"])
def consultar(registros=None, documentos=None, entorno: str | None = None) -> dict:
	"""Consulta el estado en la AEAT de registros o de facturas (tengan o no registro)."""
	_exigir_envio()
	nombres = _lista(registros)
	resultados = []
	for d in _lista(documentos):
		if isinstance(d, str):
			d = {"doctype": "Sales Invoice", "name": d}
		r = sii.consultar_documento(d.get("doctype") or "Sales Invoice", d["name"], entorno=entorno)
		resultados.append({"documento": d["name"], **r})
		frappe.db.commit()
	out = {"resultados": resultados}
	if nombres:
		out.update(_ejecutar("consultar", nombres))
	return out


@frappe.whitelist(methods=["POST"])
def generar(company: str) -> dict:
	_exigir_envio()
	return {"creados": sii.generar_registros(company)}


@frappe.whitelist(methods=["POST"])
def sincronizar(company: str, libro: str, ejercicio: str, periodo: str, entorno: str | None = None) -> dict:
	"""Cruza un periodo completo con la AEAT (ConsultaLR paginada)."""
	_exigir_envio()
	periodo = f"{cint(periodo):02d}"
	return sii.sincronizar_periodo(company, libro, str(ejercicio), periodo, entorno=entorno)


@frappe.whitelist()
def vista_previa(doctype: str, name: str) -> dict:
	"""XML que se enviaría para una factura y los datos que faltan, sin enviar nada."""
	_exigir_lectura()
	return sii.vista_previa(doctype, name)


@frappe.whitelist()
def estado_documentos(doctype: str, names) -> dict:
	"""Estado SII de cada factura para pintarlo en listados.

	``{"estados": {factura: {name, estado, csv, ..., aplica}}, "puede_enviar"}``.
	Las facturas sin registro llevan ``estado`` vacío y ``aplica`` (entra en el SII
	de Frappe por compañía activa y fecha de inicio).
	"""
	_exigir_lectura()
	nombres = _lista(names)[:500]
	out: dict = {}
	if nombres and doctype in sii.DOCTYPES:
		for f in frappe.get_all(
			"SII Registro",
			filters={"documento_tipo": doctype, "documento": ("in", nombres)},
			fields=[
				"name",
				"documento",
				"estado",
				"csv",
				"entorno",
				"fecha_envio",
				"fecha_limite",
				"codigo_error",
				"descripcion_error",
				"estado_aeat",
			],
			ignore_permissions=True,
		):
			out[f.documento] = {**f, "aplica": True}
		for d in frappe.get_all(
			doctype,
			filters={"name": ("in", [n for n in nombres if n not in out])},
			fields=["name", "company", "posting_date", "docstatus"],
		):
			out[d.name] = {
				"name": None,
				"estado": None,
				"aplica": d.docstatus == 1 and sii.aplica(doctype, d.company, d.posting_date),
			}
	return {"estados": out, "puede_enviar": puede_enviar()}


@frappe.whitelist(methods=["POST"])
def marcar_baja_pendiente(registro: str) -> dict:
	"""Pide la baja de una factura comunicada aunque siga validada (error de envío)."""
	_exigir_envio()
	doc = frappe.get_doc("SII Registro", registro)
	if doc.estado not in ("Aceptado", "Aceptado con errores"):
		frappe.throw(_("Solo se puede dar de baja lo que la AEAT ya tiene."))
	doc.estado = BAJA_PENDIENTE
	sii._evento(doc, _("Baja solicitada"), BAJA_PENDIENTE)
	doc.save(ignore_permissions=True)
	return {"estado": doc.estado}
