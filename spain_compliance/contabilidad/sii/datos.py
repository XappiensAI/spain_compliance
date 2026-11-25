# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Factura → datos del SII.

Los importes salen del libro de IVA sobre el mayor
(:func:`spain_compliance.contabilidad.libro_iva.movimientos_iva`), así que el SII
cuadra con el libro y con la liquidación. Este módulo solo agrupa las líneas de
cada factura en los bloques del SII y comprueba que no falte nada.

La parte de agrupación (:func:`desglose_emitida`, :func:`desglose_recibida`,
:func:`contraparte`) es pura y se prueba sin base de datos.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from spain_compliance.contabilidad.clasificacion import (
	DEDUCIBLE_BIEN,
	LIBRO_EXPEDIDAS,
	LIBRO_RECIBIDAS,
	TIPO_IGIC,
	TIPO_IPSI,
	TIPO_IVA,
	TIPO_RE,
	codigo,
)
from spain_compliance.contabilidad.identificacion import nif_espanol_valido, normalizar_identificador
from spain_compliance.contabilidad.sii.constantes import (
	ID_TYPE,
	PAISES_UE,
	TIPO_OP_ENTREGA,
	TIPO_OP_SERVICIOS,
)

DOCTYPE_LIBRO = {"Sales Invoice": LIBRO_EXPEDIDAS, "Purchase Invoice": LIBRO_RECIBIDAS}

# Claves de IVA del libro → bloque del SII en emitidas
_EXENTAS = {"E1": "E1", "E2": "E2", "E3": "E3", "E4": "E4", "E5": "E5", "E6": "E6", "EIB": "E5", "EXP": "E2"}
_NO_SUJETA_7_14 = {"N1"}
_NO_SUJETA_LOCALIZACION = {"N2", "SEU"}
# Claves que fijan el tipo de operación con contraparte extranjera
_CLAVE_ENTREGA = {"E2", "E3", "E4", "E5", "EIB", "EXP"}
_CLAVE_SERVICIOS = {"N2", "SEU"}


# Tipos que admite la AEAT (incluye los históricos para rectificativas antiguas).
TIPOS_IVA_LEGALES = (0.0, 2.0, 4.0, 5.0, 7.5, 8.0, 10.0, 12.0, 16.0, 18.0, 21.0)
TIPOS_RE_LEGALES = (0.0, 0.5, 0.62, 1.0, 1.4, 1.75, 2.6, 4.0, 5.2)


def tipo_legal(tasa: float, base: float, cuota: float, recargo: bool = False) -> float:
	"""Tipo del SII para una línea.

	Con impuestos de importe fijo el tipo sale de cuota / base y puede quedar en
	20,99 %. Se toma el tipo legal cuya cuota teórica más se acerca a la real,
	si la diferencia es de redondeo (2 céntimos o el 1 % de la cuota).
	"""
	legales = TIPOS_RE_LEGALES if recargo else TIPOS_IVA_LEGALES
	tasa = flt(tasa, 2)
	if any(abs(tasa - t) < 0.001 for t in legales) or not flt(base):
		return tasa
	mejor = min(legales, key=lambda t: abs(abs(base) * t / 100 - abs(cuota)))
	if abs(abs(base) * mejor / 100 - abs(cuota)) <= max(0.02, abs(cuota) * 0.01):
		return mejor
	return tasa


class DatosIncompletos(frappe.ValidationError):
	pass


def importe(valor) -> float:
	return flt(valor, 2)


# ---------------------------------------------------------------------------
# Contraparte
# ---------------------------------------------------------------------------


def _pais_iso(pais: str | None) -> str | None:
	if not pais:
		return None
	pais = pais.strip().upper()
	return "GR" if pais == "EL" else pais


def contraparte(nombre: str | None, nif: str | None, tipo_id: str | None, pais: str | None) -> dict:
	"""``{"nombre", "nif"}`` para un NIF español o ``{"nombre", "id_otro": {...}}`` si no.

	Sin tipo de identificación: NIF si es un NIF español válido; NIF-IVA (``02``) si
	empieza por el prefijo de un país de la UE; documento oficial del país (``04``)
	en el resto.
	"""
	nif = normalizar_identificador(nif)
	nombre = (nombre or "").strip()[:120]
	if nif.startswith("ES") and nif_espanol_valido(nif[2:]) and tipo_id in (None, "", "NIF", "NIF-IVA"):
		nif = nif[2:]
	if tipo_id in (None, "", "NIF") and nif and nif_espanol_valido(nif):
		return {"nombre": nombre, "nif": nif}
	if tipo_id == "NIF" and nif:
		# Marcado como NIF pero no valida: se envía igual y la AEAT dirá si existe.
		return {"nombre": nombre, "nif": nif}

	prefijo = nif[:2] if len(nif) > 2 and nif[:2].isalpha() else None
	codigo_pais = _pais_iso(pais) or _pais_iso(prefijo)
	id_type = ID_TYPE.get(tipo_id or "")
	if not id_type:
		id_type = "02" if prefijo and prefijo in PAISES_UE and prefijo != "ES" else "04"
	if id_type == "02" and not prefijo and codigo_pais in PAISES_UE:
		# El NIF-IVA lleva el prefijo del país.
		nif = ("EL" if codigo_pais == "GR" else codigo_pais) + nif
	return {"nombre": nombre, "id_otro": {"pais": codigo_pais, "tipo": id_type, "id": nif}}


def es_extranjera(cp: dict) -> bool:
	"""Con contraparte extranjera el SII exige el desglose por tipo de operación."""
	return bool(cp.get("id_otro")) or (cp.get("nif") or "").startswith("N")


# ---------------------------------------------------------------------------
# Desglose
# ---------------------------------------------------------------------------


def _lineas_iva(lineas: list[dict]) -> list[dict]:
	return [ln for ln in lineas if ln.get("tipo_impuesto") in (TIPO_IVA, TIPO_RE, TIPO_IGIC, TIPO_IPSI)]


def _errores_lineas(lineas: list[dict]) -> list[str]:
	errores = []
	for ln in lineas:
		if ln.get("tipo_impuesto") in (TIPO_IGIC, TIPO_IPSI):
			errores.append(
				_("IGIC e IPSI no se comunican al SII de la AEAT (cuenta {0}).").format(ln.get("cuenta"))
			)
		elif ln.get("tipo_impuesto") in (TIPO_IVA, TIPO_RE) and not ln.get("clave_iva"):
			errores.append(_("Falta la clave de IVA en la fila de impuestos {0}.").format(ln.get("cuenta")))
		elif not ln.get("tipo_impuesto") and (flt(ln.get("cuota")) or ln.get("cuenta") is None):
			errores.append(
				_("Hay impuestos sin clasificar ({0}). Clasifique la fila de impuestos.").format(
					ln.get("cuenta") or _("factura sin filas de impuestos")
				)
			)
	return errores


def _sumar_detalle(destino: list[dict], tasa: float, base: float, cuota: float, **extra):
	for d in destino:
		if abs(d["tipo"] - tasa) < 0.001 and all(d.get(k) == v for k, v in extra.items()):
			d["base"] = importe(d["base"] + base)
			d["cuota"] = importe(d["cuota"] + cuota)
			return d
	d = {"tipo": tasa, "base": importe(base), "cuota": importe(cuota), **extra}
	destino.append(d)
	return d


def _aplicar_recargo(detalles: list[dict], recargos: list[dict]):
	"""El recargo de equivalencia va en el mismo DetalleIVA que el IVA de su base."""
	for re_ in recargos:
		if not detalles:
			return
		d = min(detalles, key=lambda d: abs(abs(d["base"]) - abs(re_["base"])))
		d["tipo_re"] = re_["tipo"]
		d["cuota_re"] = importe(d.get("cuota_re", 0) + re_["cuota"])


def _vacio_sujeta() -> dict:
	return {"exentas": {}, "no_exentas": {}, "no_sujeta_7_14": 0.0, "no_sujeta_localizacion": 0.0}


def desglose_emitida(lineas: list[dict], extranjera: bool, tipo_op_defecto: str) -> dict:
	"""Agrupa las líneas del libro en el TipoDesglose de una factura emitida.

	Devuelve ``{"desglose": {"DesgloseFactura"|"Entrega"|"PrestacionServicios": bloque},
	"errores": [...], "exportacion": bool}``. Cada bloque tiene ``exentas`` (causa →
	base), ``no_exentas`` (``S1``/``S2`` → [detalle]) y los importes no sujetos.
	"""
	errores = _errores_lineas(lineas)
	bloques: dict[str, dict] = {}
	recargos: dict[str, list] = defaultdict(list)
	exportacion = False

	for ln in _lineas_iva(lineas):
		clave = codigo(ln.get("clave_iva"))
		if not clave:
			continue
		if extranjera:
			if clave in _CLAVE_ENTREGA:
				tipo_op = TIPO_OP_ENTREGA
			elif clave in _CLAVE_SERVICIOS:
				tipo_op = TIPO_OP_SERVICIOS
			else:
				tipo_op = tipo_op_defecto
		else:
			tipo_op = "DesgloseFactura"
		b = bloques.setdefault(tipo_op, _vacio_sujeta())
		base, cuota = importe(ln.get("base_imponible")), importe(ln.get("cuota"))
		tasa = tipo_legal(ln.get("tipo_impositivo"), base, cuota, ln.get("tipo_impuesto") == TIPO_RE)

		if ln.get("tipo_impuesto") == TIPO_RE:
			recargos[tipo_op].append({"tipo": tasa, "base": base, "cuota": cuota})
		elif clave == "S1":
			_sumar_detalle(b["no_exentas"].setdefault("S1", []), tasa, base, cuota)
		elif clave == "ISP":
			_sumar_detalle(b["no_exentas"].setdefault("S2", []), 0.0, base, 0.0)
		elif clave in _EXENTAS:
			causa = _EXENTAS[clave]
			b["exentas"][causa] = importe(b["exentas"].get(causa, 0) + base)
			exportacion = exportacion or causa == "E2"
		elif clave in _NO_SUJETA_7_14:
			b["no_sujeta_7_14"] = importe(b["no_sujeta_7_14"] + base)
		elif clave in _NO_SUJETA_LOCALIZACION:
			b["no_sujeta_localizacion"] = importe(b["no_sujeta_localizacion"] + base)
		else:
			errores.append(
				_("La clave {0} es de compras y no vale en una factura emitida ({1}).").format(
					clave, ln.get("cuenta")
				)
			)

	for tipo_op, res in recargos.items():
		_aplicar_recargo(bloques.get(tipo_op, _vacio_sujeta())["no_exentas"].get("S1", []), res)

	if not bloques and not errores:
		errores.append(_("La factura no tiene ninguna línea de IVA que comunicar."))
	return {"desglose": bloques, "errores": errores, "exportacion": exportacion}


def desglose_recibida(lineas: list[dict]) -> dict:
	"""Agrupa las líneas del libro en el DesgloseFactura de una factura recibida.

	Devuelve ``{"iva": [detalle], "isp": [detalle], "errores", "intracomunitaria",
	"importacion", "cuota_deducible", "solo_no_sujeta"}``. La autorrepercusión no se
	comunica (es la contrapartida de la cuota soportada); las líneas no sujetas
	tampoco.
	"""
	errores = _errores_lineas(lineas)
	iva: list[dict] = []
	isp: list[dict] = []
	recargos: list[dict] = []
	intracomunitaria = importacion = False
	deducible = 0.0
	no_sujetas = 0

	for ln in _lineas_iva(lineas):
		if ln.get("autorrepercusion"):
			continue
		clave = codigo(ln.get("clave_iva"))
		if not clave:
			continue
		base, cuota = importe(ln.get("base_imponible")), importe(ln.get("cuota"))
		tasa = tipo_legal(ln.get("tipo_impositivo"), base, cuota, ln.get("tipo_impuesto") == TIPO_RE)
		bien = ln.get("deducible_iva") == DEDUCIBLE_BIEN
		deducible += flt(ln.get("cuota_deducible"))
		if ln.get("tipo_impuesto") == TIPO_RE:
			recargos.append({"tipo": tasa, "base": base, "cuota": cuota})
		elif clave in ("S1", "AIB", "IMP"):
			_sumar_detalle(iva, tasa, base, cuota, bien_inversion=bien)
			intracomunitaria = intracomunitaria or clave == "AIB"
			importacion = importacion or clave == "IMP"
		elif clave in ("ISP", "AIS"):
			_sumar_detalle(isp, tasa, base, cuota)
			intracomunitaria = intracomunitaria or clave == "AIS"
		elif clave.startswith("E"):
			_sumar_detalle(iva, 0.0, base, 0.0, exenta=True)
		elif clave in ("N1", "N2", "SEU"):
			no_sujetas += 1
		else:
			errores.append(
				_("La clave {0} es de ventas y no vale en una factura recibida ({1}).").format(
					clave, ln.get("cuenta")
				)
			)
	_aplicar_recargo(iva, recargos)
	solo_no_sujeta = not iva and not isp and no_sujetas > 0
	if not iva and not isp and not solo_no_sujeta and not errores:
		errores.append(_("La factura no tiene ninguna línea de IVA que comunicar."))
	return {
		"iva": iva,
		"isp": isp,
		"errores": errores,
		"intracomunitaria": intracomunitaria,
		"importacion": importacion,
		"cuota_deducible": importe(deducible),
		"solo_no_sujeta": solo_no_sujeta,
	}


def _cuotas(lineas: list[dict]) -> float:
	return sum(
		flt(ln.get("cuota"))
		for ln in _lineas_iva(lineas)
		if not ln.get("autorrepercusion") and ln.get("tipo_impuesto") in (TIPO_IVA, TIPO_RE)
	)


# ---------------------------------------------------------------------------
# Factura completa
# ---------------------------------------------------------------------------


def titular(company: str, config=None) -> dict:
	nombre = (config and config.get("nombre_titular")) or frappe.db.get_value(
		"Company", company, "company_name"
	)
	nif = (config and config.get("nif_titular")) or frappe.db.get_value("Company", company, "tax_id")
	nif = normalizar_identificador(nif)
	if nif.startswith("ES") and nif_espanol_valido(nif[2:]):
		nif = nif[2:]
	if not nif:
		frappe.throw(_("La compañía {0} no tiene NIF (tax_id).").format(company), DatosIncompletos)
	return {"nombre": (nombre or company)[:120], "nif": nif}


def _descripcion(doctype: str, name: str, defecto: str | None) -> str:
	tabla = "Sales Invoice Item" if doctype == "Sales Invoice" else "Purchase Invoice Item"
	nombres = frappe.get_all(tabla, filters={"parent": name}, pluck="item_name", order_by="idx", limit=20)
	vistos: list[str] = []
	for n in nombres:
		n = (n or "").strip()
		if n and n not in vistos:
			vistos.append(n)
	texto = "; ".join(vistos)
	if not texto:
		texto = defecto or (
			_("Venta de bienes y servicios")
			if doctype == "Sales Invoice"
			else _("Compra de bienes y servicios")
		)
	return texto[:500]


def _tipo_op_por_articulos(doctype: str, name: str) -> str:
	"""Entrega si la mayor parte del neto son artículos de stock o activos fijos."""
	tabla = "Sales Invoice Item" if doctype == "Sales Invoice" else "Purchase Invoice Item"
	filas = frappe.db.sql(
		f"""
		SELECT ABS(it.base_net_amount) AS importe,
			IFNULL(i.is_stock_item, 0) OR IFNULL(i.is_fixed_asset, 0) AS bien
		FROM `tab{tabla}` it LEFT JOIN `tabItem` i ON i.name = it.item_code
		WHERE it.parent = %s
		""",
		name,
		as_dict=True,
	)
	bienes = sum(flt(f.importe) for f in filas if f.bien)
	total = sum(flt(f.importe) for f in filas)
	return TIPO_OP_ENTREGA if total and bienes * 2 >= total else TIPO_OP_SERVICIOS


def _cabecera(doctype: str, name: str) -> frappe._dict:
	campos = ["name", "company", "posting_date", "is_return", "return_against", "base_net_total", "docstatus"]
	if doctype == "Sales Invoice":
		campos += ["customer AS party", "customer_name AS party_name"]
	else:
		campos += ["supplier AS party", "supplier_name AS party_name", "bill_no", "bill_date"]
	cab = frappe.db.get_value(doctype, name, campos, as_dict=True)
	if not cab:
		frappe.throw(_("No existe {0} {1}.").format(_(doctype), name), DatosIncompletos)
	return cab


def numero_y_fecha(doctype: str, cab) -> tuple[str | None, object]:
	"""Número y fecha de expedición que identifican la factura en el SII."""
	if doctype == "Purchase Invoice":
		return (cab.get("bill_no") or "").strip() or None, cab.get("bill_date") or cab.posting_date
	return cab.name, cab.posting_date


def datos_factura(doctype: str, name: str, config, lineas: list[dict] | None = None) -> dict:
	"""Datos completos de una factura para el SII.

	``lineas`` son sus líneas del libro de IVA; si no se pasan se calculan. El
	resultado lleva ``errores`` (lista vacía si se puede enviar) y
	``no_aplica`` (recibida solo con operaciones no sujetas).
	"""
	from spain_compliance.contabilidad.libro_iva import movimientos_iva

	libro = DOCTYPE_LIBRO[doctype]
	cab = _cabecera(doctype, name)
	if lineas is None:
		lineas = [
			ln
			for ln in movimientos_iva(cab.company, cab.posting_date, cab.posting_date, libro)
			if ln["voucher_type"] == doctype and ln["voucher_no"] == name
		]
	errores: list[str] = []
	if cab.docstatus != 1:
		errores.append(_("La factura no está validada."))

	numero, fecha_exp = numero_y_fecha(doctype, cab)
	if not numero:
		errores.append(_("Falta el número de factura del proveedor (bill_no)."))

	nif, tipo_id, pais = None, None, None
	for ln in lineas:
		if ln.get("nif") or ln.get("pais"):
			nif, tipo_id, pais = ln.get("nif"), ln.get("tipo_identificacion"), ln.get("pais")
			break
	if not nif:
		party_type = "Customer" if doctype == "Sales Invoice" else "Supplier"
		nif, tipo_id = frappe.db.get_value(
			party_type, cab.party, ["tax_id", "tipo_identificacion_fiscal"]
		) or (None, None)
	cp = contraparte(cab.party_name or cab.party, nif, tipo_id, pais)
	if not (cp.get("nif") or (cp.get("id_otro") or {}).get("id")):
		errores.append(_("El tercero {0} no tiene NIF ni identificador fiscal.").format(cab.party))
	if cp.get("id_otro") and not cp["id_otro"].get("pais"):
		errores.append(
			_("No se conoce el país del tercero {0}: indíquelo en su dirección.").format(cab.party)
		)

	fecha_contable = getdate(cab.posting_date)
	tipo_factura = "R1" if cab.is_return else "F1"
	rectificada = None
	if cab.is_return and cab.return_against:
		orig = _cabecera(doctype, cab.return_against)
		num_o, fecha_o = numero_y_fecha(doctype, orig)
		rectificada = {"numero": num_o, "fecha": getdate(fecha_o)}

	out = {
		"libro": libro,
		"documento_tipo": doctype,
		"documento": name,
		"company": cab.company,
		"numero": numero,
		"fecha_expedicion": getdate(fecha_exp),
		"fecha_contable": fecha_contable,
		"ejercicio": str(fecha_contable.year),
		"periodo": f"{fecha_contable.month:02d}",
		"tipo_factura": tipo_factura,
		"rectificada": rectificada,
		"contraparte": cp,
		"tercero": cab.party_name or cab.party,
		"descripcion": _descripcion(doctype, name, (config or {}).get("descripcion_operacion")),
		"importe_total": importe(
			flt(cab.base_net_total) * (-1 if cab.is_return and flt(cab.base_net_total) > 0 else 1)
			+ _cuotas(lineas)
		),
		"no_aplica": False,
	}

	if libro == LIBRO_EXPEDIDAS:
		ajuste = (config or {}).get("tipo_operacion_extranjero") or "Automático"
		extranjera = es_extranjera(cp)
		if ajuste == "Entrega":
			defecto = TIPO_OP_ENTREGA
		elif ajuste == "Prestación de servicios":
			defecto = TIPO_OP_SERVICIOS
		else:
			defecto = _tipo_op_por_articulos(doctype, name) if extranjera else TIPO_OP_SERVICIOS
		d = desglose_emitida(lineas, extranjera, defecto)
		out["desglose"] = d["desglose"]
		out["clave_regimen"] = "02" if d["exportacion"] else "01"
		errores += d["errores"]
	else:
		d = desglose_recibida(lineas)
		out.update(
			desglose_iva=d["iva"],
			desglose_isp=d["isp"],
			cuota_deducible=d["cuota_deducible"],
			clave_regimen="09" if d["intracomunitaria"] else "01",
			no_aplica=d["solo_no_sujeta"],
		)
		if d["importacion"] and not d["isp"]:
			# DUA: la factura la «emite» el propio titular.
			out["tipo_factura"] = "F5"
		errores += d["errores"]

	out["errores"] = list(dict.fromkeys(errores))
	return out
