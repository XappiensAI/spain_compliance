# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Libro de IVA calculado sobre el mayor (sin registro aparte).

Cada línea del libro es un apunte (agrupado por documento y cuenta) en una cuenta
de impuestos (``account_type = Tax``). El mayor da la cuota; la fila de impuestos
del documento con esa cuenta aporta la clasificación fiscal (tipo, clave,
deducibilidad, retención) y la base (``base_net_amount``); la cabecera aporta
tercero, NIF y referencias.

Por construcción, la suma de las cuotas de un periodo es el movimiento de las
cuentas de impuestos en el mayor. Los apuntes de asientos sin fila de impuestos
(asientos manuales) salen *sin clasificar*.

Las operaciones sin cuota (exentas, no sujetas, al 0 %) no generan apunte. Para
que el libro las recoja, se añaden las filas de impuestos con cuota 0 de las
facturas validadas del periodo (y una línea *sin clasificar* por factura sin
ninguna fila de impuestos).

Es la fuente única del libro de IVA, la liquidación y el SII.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt, getdate

from spain_compliance.contabilidad.clasificacion import (
	DEDUCIBLE_NO,
	LIBRO_EXPEDIDAS,
	LIBRO_RECIBIDAS,
	TIPO_RETENCION,
	TIPOS_CON_CLAVE,
)
from spain_compliance.contabilidad.identificacion import nif_espanol_valido, normalizar_identificador

# Documento → (tabla de impuestos, libro, campo tercero, campo nombre tercero, tipo tercero)
DOCUMENTOS = {
	"Sales Invoice": ("Sales Taxes and Charges", LIBRO_EXPEDIDAS, "customer", "customer_name", "Customer"),
	"POS Invoice": ("Sales Taxes and Charges", LIBRO_EXPEDIDAS, "customer", "customer_name", "Customer"),
	"Purchase Invoice": (
		"Purchase Taxes and Charges",
		LIBRO_RECIBIDAS,
		"supplier",
		"supplier_name",
		"Supplier",
	),
}

CAMPOS_FILA = (
	"parent",
	"account_head",
	"charge_type",
	"rate",
	"base_net_amount",
	"base_tax_amount_after_discount_amount",
	"tipo_impuesto",
	"clave_iva",
	"deducible_iva",
	"clave_retencion",
)


def _libro_por_cuenta(numero: str | None) -> str | None:
	"""Asientos sin documento: 477 repercutido → expedidas, 472 soportado → recibidas (PGC)."""
	numero = numero or ""
	if numero.startswith("477"):
		return LIBRO_EXPEDIDAS
	if numero.startswith("472"):
		return LIBRO_RECIBIDAS
	return None


def _apuntes(company: str, inicio, fin) -> list[dict]:
	return frappe.db.sql(
		"""
		SELECT g.voucher_type, g.voucher_no, g.posting_date, g.account,
			a.account_number, SUM(g.debit) AS debe, SUM(g.credit) AS haber
		FROM `tabGL Entry` g
		JOIN `tabAccount` a ON a.name = g.account
		WHERE g.company = %(company)s AND g.is_cancelled = 0
			AND g.posting_date BETWEEN %(inicio)s AND %(fin)s
			AND a.account_type = 'Tax'
		GROUP BY g.voucher_type, g.voucher_no, g.posting_date, g.account, a.account_number
		ORDER BY g.posting_date, g.voucher_no
		""",
		{"company": company, "inicio": inicio, "fin": fin},
		as_dict=True,
	)


def _filas_impuesto(tabla: str, padres: list[str]) -> dict[tuple, dict]:
	"""``(documento, cuenta)`` → clasificación y base de su fila (o filas) de impuestos."""
	out: dict[tuple, dict] = {}
	if not padres:
		return out
	campos = (
		", ".join(f"`{c}`" for c in CAMPOS_FILA) + ", `add_deduct_tax`"
		if tabla.startswith("Purchase")
		else ", ".join(f"`{c}`" for c in CAMPOS_FILA)
	)
	for i in range(0, len(padres), 1000):
		lote = padres[i : i + 1000]
		for fila in frappe.db.sql(
			f"SELECT {campos} FROM `tab{tabla}` WHERE parent IN %s ORDER BY idx",
			(tuple(lote),),
			as_dict=True,
		):
			clave = (fila.parent, fila.account_head)
			if clave in out:
				out[clave]["base"] += flt(fila.base_net_amount)
				continue
			out[clave] = {**fila, "base": flt(fila.base_net_amount)}
	# Filas de IVA que suman (sin autorrepercusión ni retenciones) por documento.
	n_iva: dict[str, int] = defaultdict(int)
	for (padre, _cuenta), fila in out.items():
		if fila.get("tipo_impuesto") in TIPOS_CON_CLAVE and fila.get("add_deduct_tax") != "Deduct":
			n_iva[padre] += 1
	for (padre, _cuenta), fila in out.items():
		fila["n_iva_documento"] = n_iva.get(padre, 0)
	return out


def _cabeceras(doctype: str, nombres: list[str]) -> dict[str, dict]:
	_tabla, _libro, campo_tercero, campo_nombre, _tipo = DOCUMENTOS[doctype]
	campos = [
		"name",
		campo_tercero,
		campo_nombre,
		"is_return",
		"return_against",
		"base_grand_total",
		"base_net_total",
	]
	if doctype == "Purchase Invoice":
		campos += ["bill_no", "bill_date"]
	out: dict[str, dict] = {}
	for i in range(0, len(nombres), 1000):
		for fila in frappe.get_all(doctype, filters={"name": ("in", nombres[i : i + 1000])}, fields=campos):
			out[fila.name] = fila
	return out


def _pais(party_type: str | None, party: str | None, tipo_id: str | None, nif: str | None) -> str | None:
	"""``ES`` para NIF español, prefijo del NIF-IVA o país de la dirección del tercero."""
	nif = nif or ""
	if tipo_id == "NIF" or (nif and nif_espanol_valido(nif)):
		return "ES"
	if tipo_id == "NIF-IVA" and len(nif) >= 2 and nif[:2].isalpha():
		return nif[:2]
	if not party:
		return None
	direccion = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": party_type, "link_name": party, "parenttype": "Address"},
		"parent",
	)
	pais = frappe.db.get_value("Address", direccion, "country") if direccion else None
	return frappe.db.get_value("Country", pais, "code") if pais else None


def _claves_articulo(doctype: str, nombres: list[str]) -> dict[str, str]:
	"""Documento → clave de IVA de la plantilla de impuestos de sus artículos (si es única)."""
	tabla_items = {"Sales Invoice": "Sales Invoice Item", "POS Invoice": "POS Invoice Item"}.get(
		doctype, "Purchase Invoice Item"
	)
	claves: dict[str, set] = defaultdict(set)
	for i in range(0, len(nombres), 1000):
		for fila in frappe.db.sql(
			f"""
			SELECT it.parent, itt.clave_iva
			FROM `tab{tabla_items}` it
			JOIN `tabItem Tax Template` itt ON itt.name = it.item_tax_template
			WHERE it.parent IN %s AND IFNULL(itt.clave_iva, '') != ''
			""",
			(tuple(nombres[i : i + 1000]),),
			as_dict=True,
		):
			claves[fila.parent].add(fila.clave_iva)
	return {doc: c.pop() for doc, c in claves.items() if len(c) == 1}


def _nifs(party_type: str, parties: set[str]) -> dict[str, tuple]:
	if not parties:
		return {}
	filas = frappe.get_all(
		party_type,
		filters={"name": ("in", list(parties))},
		fields=["name", "tax_id", "tipo_identificacion_fiscal"],
	)
	return {f.name: (normalizar_identificador(f.tax_id), f.tipo_identificacion_fiscal) for f in filas}


def _sin_cuota(company: str, inicio, fin, ya: set[tuple]) -> list[dict]:
	"""Pseudo-apuntes de cuota 0 para facturas exentas / sin impuestos del periodo."""
	out: list[dict] = []
	for doctype, (tabla, _l, _t, _n, _p) in DOCUMENTOS.items():
		filas = frappe.db.sql(
			f"""
			SELECT d.name AS voucher_no, d.posting_date, t.account_head AS account,
				a.account_number, t.base_tax_amount_after_discount_amount AS cuota
			FROM `tab{doctype}` d
			LEFT JOIN `tab{tabla}` t ON t.parent = d.name AND t.parenttype = %(dt)s
			LEFT JOIN `tabAccount` a ON a.name = t.account_head
			WHERE d.company = %(company)s AND d.docstatus = 1
				AND d.posting_date BETWEEN %(inicio)s AND %(fin)s
				AND (
					t.name IS NULL
					OR (a.account_type = 'Tax' AND ABS(IFNULL(t.base_tax_amount_after_discount_amount, 0)) < 0.005)
				)
			""",
			{"dt": doctype, "company": company, "inicio": inicio, "fin": fin},
			as_dict=True,
		)
		con_impuesto = {f.voucher_no for f in filas if f.account}
		for f in filas:
			if f.account is None and f.voucher_no in con_impuesto:
				continue
			clave = (doctype, f.voucher_no, f.account)
			if clave in ya:
				continue
			ya.add(clave)
			out.append(
				frappe._dict(
					voucher_type=doctype,
					voucher_no=f.voucher_no,
					posting_date=f.posting_date,
					account=f.account,
					account_number=f.account_number,
					debe=0.0,
					haber=0.0,
					sin_fila=f.account is None,
				)
			)
	return out


def movimientos_iva(company: str, desde, hasta, libro: str | None = None) -> list[dict]:
	"""Líneas del libro de impuestos de ``company`` entre dos fechas (incluidas)."""
	inicio, fin = getdate(desde), getdate(hasta)
	apuntes = _apuntes(company, inicio, fin)
	vistos = {(a.voucher_type, a.voucher_no, a.account) for a in apuntes}
	apuntes += _sin_cuota(company, inicio, fin, vistos)
	apuntes.sort(key=lambda a: (a.posting_date, a.voucher_no))

	por_tipo: dict[str, list[str]] = defaultdict(list)
	for ap in apuntes:
		if ap.voucher_type in DOCUMENTOS:
			por_tipo[ap.voucher_type].append(ap.voucher_no)

	filas_imp: dict[tuple, dict] = {}
	claves_articulo: dict[tuple, str] = {}
	cabeceras: dict[str, dict] = {}
	nifs: dict[tuple, tuple] = {}
	for doctype, nombres in por_tipo.items():
		nombres = sorted(set(nombres))
		tabla, _l, campo_tercero, _n, party_type = DOCUMENTOS[doctype]
		filas_imp.update({(doctype, *k): v for k, v in _filas_impuesto(tabla, nombres).items()})
		claves_articulo.update({(doctype, k): v for k, v in _claves_articulo(doctype, nombres).items()})
		cab = _cabeceras(doctype, nombres)
		cabeceras.update({(doctype, k): v for k, v in cab.items()})
		terceros = {c.get(campo_tercero) for c in cab.values() if c.get(campo_tercero)}
		nifs.update({(party_type, p): v for p, v in _nifs(party_type, terceros).items()})

	prorrata = frappe.db.get_value("Company", company, "prorrata_general")
	prorrata = 100.0 if prorrata in (None, "") else flt(prorrata)

	out: list[dict] = []
	paises: dict[tuple, str | None] = {}
	for ap in apuntes:
		doc_conf = DOCUMENTOS.get(ap.voucher_type)
		fila = filas_imp.get((ap.voucher_type, ap.voucher_no, ap.account)) if doc_conf else None
		cab = cabeceras.get((ap.voucher_type, ap.voucher_no)) if doc_conf else None
		libro_linea = doc_conf[1] if doc_conf else _libro_por_cuenta(ap.account_number)
		if libro and libro_linea != libro:
			continue

		# Cuota con el signo natural del libro: repercutido al haber, soportado al debe.
		cuota = (
			flt(ap.haber) - flt(ap.debe) if libro_linea == LIBRO_EXPEDIDAS else flt(ap.debe) - flt(ap.haber)
		)
		tipo = (fila or {}).get("tipo_impuesto") or ""
		autorrepercusion = bool(fila and fila.get("add_deduct_tax") == "Deduct" and tipo != TIPO_RETENCION)
		if autorrepercusion or tipo == TIPO_RETENCION:
			# En compras estas filas abonan la cuenta: la cuota es el haber.
			cuota = -cuota

		base = flt((fila or {}).get("base"))
		if ap.get("sin_fila") and cab:
			base = flt(cab.get("base_net_total"))
		elif (
			fila
			and cab
			and not base
			and flt(cuota)
			and fila.get("charge_type") == "Actual"
			and fila.get("n_iva_documento", 0) <= 1
		):
			# Importe fijo: ERPNext no guarda base. Con un solo tipo de IVA en la factura,
			# la base es su neto (también para la autorrepercusión y la retención).
			base = flt(cab.get("base_net_total"))
		if cab and cint(cab.get("is_return")) and base > 0:
			base = -base

		deducible = 0.0
		if libro_linea == LIBRO_RECIBIDAS and tipo in TIPOS_CON_CLAVE and not autorrepercusion:
			if (fila or {}).get("deducible_iva") != DEDUCIBLE_NO:
				deducible = flt(cuota * prorrata / 100.0, 2)

		party_type = doc_conf[4] if doc_conf else None
		party = cab.get(doc_conf[2]) if cab else None
		nif, tipo_id = nifs.get((party_type, party), (None, None)) if party else (None, None)
		if party and (party_type, party) not in paises:
			paises[(party_type, party)] = _pais(party_type, party, tipo_id, nif)
		clave = (fila or {}).get("clave_iva")
		if tipo in TIPOS_CON_CLAVE:
			# La plantilla de impuestos de los artículos manda sobre la fila (p. ej. exenta).
			clave = claves_articulo.get((ap.voucher_type, ap.voucher_no)) or clave
		clasificada = bool(tipo) and (tipo not in TIPOS_CON_CLAVE or bool(clave))
		tasa = flt((fila or {}).get("rate")) if flt(cuota) else 0.0
		if not tasa and flt(cuota) and flt(base):
			# Fila de importe fijo (Actual): el tipo es cuota / base.
			tasa = flt(abs(cuota) * 100.0 / abs(base), 2)
		out.append(
			{
				"voucher_type": ap.voucher_type,
				"voucher_no": ap.voucher_no,
				"fecha": ap.posting_date,
				"libro": libro_linea,
				"cuenta": ap.account,
				"numero": ap.voucher_no,
				"numero_externo": (cab or {}).get("bill_no"),
				"fecha_expedicion": (cab or {}).get("bill_date") or ap.posting_date,
				"factura_rectificada": (cab or {}).get("return_against"),
				"tipo_factura": "R1" if cab and cint(cab.get("is_return")) else ("F1" if cab else None),
				"party_type": party_type,
				"party": party,
				"party_name": (cab or {}).get(doc_conf[3]) if doc_conf and cab else None,
				"nif": nif,
				"tipo_identificacion": tipo_id,
				"pais": paises[(party_type, party)] if party else None,
				"tipo_impuesto": tipo or None,
				"clave_iva": clave,
				"deducible_iva": (fila or {}).get("deducible_iva"),
				"clave_retencion": (fila or {}).get("clave_retencion"),
				"autorrepercusion": autorrepercusion,
				"tipo_impositivo": tasa,
				"base_imponible": flt(base, 2),
				"cuota": flt(cuota, 2),
				"cuota_deducible": deducible,
				"total_factura": flt((cab or {}).get("base_grand_total")),
				"sin_clasificar": not clasificada,
			}
		)
	return out
