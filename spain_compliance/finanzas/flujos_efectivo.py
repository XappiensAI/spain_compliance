# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Estado de flujos de efectivo del modelo normal del PGC (método indirecto).

Se calcula con el balance al día anterior al inicio del periodo, el balance al
final y la cuenta de pérdidas y ganancias del periodo. Cada partida hoja del
balance, salvo el efectivo, se asigna a una sola línea del estado, y cada
partida de la PyG que no mueve caja se quita del resultado y se suma a la línea
de balance con la que se compensa. Así el aumento o disminución neta del
efectivo coincide con la variación de B.VII del balance.

Limitaciones conocidas, propias de calcularlo desde saldos y no desde movimientos:

- Las inversiones y desinversiones de una misma clase se presentan netas: si en
  el periodo se compra y se vende inmovilizado material, se ve la diferencia.
- Los intereses y dividendos se consideran cobrados o pagados en el periodo
  en que se devengan; lo pendiente queda en la deuda o el crédito correspondiente.
- Los dividendos son la variación de reservas, resultados y dividendo a cuenta
  que no explica el resultado del periodo.
"""

from __future__ import annotations

from collections import defaultdict

from frappe import _
from frappe.utils import add_days, getdate

from spain_compliance.contabilidad import cuentas_anuales as ca

_EPS = 0.005

# Partida (o epígrafe) del balance → línea del estado. Cada hoja del balance se
# resuelve por su antecesor más cercano que esté aquí.
MAPA_BALANCE: dict[str, str] = {
	"A.I": "inv.b",
	"A.II": "inv.c",
	"A.III": "inv.d",
	"A.IV": "inv.a",
	"B.IV": "inv.a",
	"A.V": "inv.e",
	"B.V": "inv.e",
	"PN.2": "inv.e",
	"B.I": "inv.f",
	"PC.I": "inv.f",
	"A.VI": "A.4.d",
	"PNC.IV": "A.4.d",
	"B.III.5": "A.4.d",
	"PC.V.5": "A.4.d",
	"A.VII": "A.3.f",
	"PNC.V": "A.3.f",
	"PNC.VI": "A.3.f",
	"B.II": "A.3.a",
	"B.III": "A.3.b",
	"B.VI": "A.3.c",
	"PC.V": "A.3.d",
	"PC.VI": "A.3.e",
	"PNC.I": "A.2.c",
	"PC.II": "A.2.c",
	"B.III.7": "C.9.a",
	"PN.1.I": "C.9.a",
	"PN.1.II": "C.9.a",
	"PN.1.VI": "C.9.a",
	"PN.1.IX": "C.9.a",
	"PN.1.IV": "C.9.c",
	"PN.3": "C.9.e",
	"PN.1.III": "C.11",
	"PN.1.V": "C.11",
	"PN.1.VII": "C.11",
	"PN.1.VIII": "C.11",
	"PNC.II.1": "C.10.a",
	"PC.III.1": "C.10.a",
	"PNC.II.2": "C.10.b",
	"PC.III.2": "C.10.b",
	"PNC.III": "C.10.c",
	"PC.IV": "C.10.c",
	"PNC.II": "C.10.d",
	"PC.III": "C.10.d",
	"PNC.VII": "C.10.d",
	"PC.VII": "C.10.d",
}

EFECTIVO = "B.VII"

# Partidas de la PyG sin efecto en caja que se compensan con una clase de inversión.
_INVERSION_POR_PREFIJO = {
	"680": "inv.b",
	"690": "inv.b",
	"790": "inv.b",
	"670": "inv.b",
	"770": "inv.b",
	"681": "inv.c",
	"691": "inv.c",
	"791": "inv.c",
	"671": "inv.c",
	"771": "inv.c",
	"682": "inv.d",
	"692": "inv.d",
	"792": "inv.d",
	"672": "inv.d",
	"772": "inv.d",
	"673": "inv.a",
	"773": "inv.a",
}
# Partida hoja de la PyG → (línea de ajuste, clase de inversión si el prefijo no la indica).
_AJUSTES_INVERSION = {
	"8": ("A.2.a", "inv.c"),
	"11.a": ("A.2.b", "inv.c"),
	"18.a": ("A.2.b", "inv.e"),
	"11.b": ("A.2.e", "inv.c"),
	"18.b": ("A.2.f", "inv.e"),
	"16": ("A.2.j", "inv.e"),
}

_INVERSIONES = (
	("inv.a", "Empresas del grupo y asociadas"),
	("inv.b", "Inmovilizado intangible"),
	("inv.c", "Inmovilizado material"),
	("inv.d", "Inversiones inmobiliarias"),
	("inv.e", "Otros activos financieros"),
	("inv.f", "Activos no corrientes mantenidos para la venta"),
)


def _nodo(code: str, label: str, tipo: str, hijos: list | None = None) -> dict:
	return {"code": code, "label": label, "tipo": tipo, "hijos": hijos or []}


def estructura() -> list[dict]:
	"""Líneas del modelo normal. Las hojas reciben importes; los padres suman a sus hijos."""
	letras = "abcdef"
	return [
		_nodo(
			"A",
			_("A) Flujos de efectivo de las actividades de explotación"),
			"masa",
			[
				_nodo("A.1", _("1. Resultado del ejercicio antes de impuestos"), "linea"),
				_nodo(
					"A.2",
					_("2. Ajustes del resultado"),
					"linea",
					[
						_nodo("A.2.a", _("a) Amortización del inmovilizado (+)"), "partida"),
						_nodo("A.2.b", _("b) Correcciones valorativas por deterioro (+/-)"), "partida"),
						_nodo("A.2.c", _("c) Variación de provisiones (+/-)"), "partida"),
						_nodo("A.2.d", _("d) Imputación de subvenciones (-)"), "partida"),
						_nodo(
							"A.2.e",
							_("e) Resultados por bajas y enajenaciones del inmovilizado (+/-)"),
							"partida",
						),
						_nodo(
							"A.2.f",
							_("f) Resultados por bajas y enajenaciones de instrumentos financieros (+/-)"),
							"partida",
						),
						_nodo("A.2.g", _("g) Ingresos financieros (-)"), "partida"),
						_nodo("A.2.h", _("h) Gastos financieros (+)"), "partida"),
						_nodo("A.2.i", _("i) Diferencias de cambio (+/-)"), "partida"),
						_nodo(
							"A.2.j",
							_("j) Variación de valor razonable en instrumentos financieros (+/-)"),
							"partida",
						),
					],
				),
				_nodo(
					"A.3",
					_("3. Cambios en el capital corriente"),
					"linea",
					[
						_nodo("A.3.a", _("a) Existencias (+/-)"), "partida"),
						_nodo("A.3.b", _("b) Deudores y otras cuentas a cobrar (+/-)"), "partida"),
						_nodo("A.3.c", _("c) Otros activos corrientes (+/-)"), "partida"),
						_nodo("A.3.d", _("d) Acreedores y otras cuentas a pagar (+/-)"), "partida"),
						_nodo("A.3.e", _("e) Otros pasivos corrientes (+/-)"), "partida"),
						_nodo("A.3.f", _("f) Otros activos y pasivos no corrientes (+/-)"), "partida"),
					],
				),
				_nodo(
					"A.4",
					_("4. Otros flujos de efectivo de las actividades de explotación"),
					"linea",
					[
						_nodo("A.4.a", _("a) Pagos de intereses (-)"), "partida"),
						_nodo("A.4.b", _("b) Cobros de dividendos (+)"), "partida"),
						_nodo("A.4.c", _("c) Cobros de intereses (+)"), "partida"),
						_nodo("A.4.d", _("d) Cobros (pagos) por impuesto sobre beneficios (+/-)"), "partida"),
					],
				),
				_nodo(
					"A.5",
					_("5. Flujos de efectivo de las actividades de explotación (1 + 2 + 3 + 4)"),
					"subtotal",
				),
			],
		),
		_nodo(
			"B",
			_("B) Flujos de efectivo de las actividades de inversión"),
			"masa",
			[
				_nodo(
					"B.6",
					_("6. Pagos por inversiones (-)"),
					"linea",
					[
						_nodo(f"B.6.{letras[i]}", f"{letras[i]}) {_(label)}", "partida")
						for i, (_key, label) in enumerate(_INVERSIONES)
					],
				),
				_nodo(
					"B.7",
					_("7. Cobros por desinversiones (+)"),
					"linea",
					[
						_nodo(f"B.7.{letras[i]}", f"{letras[i]}) {_(label)}", "partida")
						for i, (_key, label) in enumerate(_INVERSIONES)
					],
				),
				_nodo("B.8", _("8. Flujos de efectivo de las actividades de inversión (7 - 6)"), "subtotal"),
			],
		),
		_nodo(
			"C",
			_("C) Flujos de efectivo de las actividades de financiación"),
			"masa",
			[
				_nodo(
					"C.9",
					_("9. Cobros y pagos por instrumentos de patrimonio"),
					"linea",
					[
						_nodo(
							"C.9.a", _("a) Emisión y amortización de instrumentos de patrimonio"), "partida"
						),
						_nodo(
							"C.9.c",
							_("b) Adquisición y enajenación de instrumentos de patrimonio propio"),
							"partida",
						),
						_nodo("C.9.e", _("c) Subvenciones, donaciones y legados recibidos (+)"), "partida"),
					],
				),
				_nodo(
					"C.10",
					_(
						"10. Cobros y pagos por instrumentos de pasivo financiero (emisión neta de devoluciones)"
					),
					"linea",
					[
						_nodo("C.10.a", _("a) Obligaciones y otros valores negociables"), "partida"),
						_nodo("C.10.b", _("b) Deudas con entidades de crédito"), "partida"),
						_nodo("C.10.c", _("c) Deudas con empresas del grupo y asociadas"), "partida"),
						_nodo("C.10.d", _("d) Otras deudas"), "partida"),
					],
				),
				_nodo(
					"C.11",
					_("11. Pagos por dividendos y remuneraciones de otros instrumentos de patrimonio (-)"),
					"linea",
				),
				_nodo(
					"C.12",
					_("12. Flujos de efectivo de las actividades de financiación (9 + 10 - 11)"),
					"subtotal",
				),
			],
		),
		_nodo("D", _("D) Efecto de las variaciones de los tipos de cambio"), "masa"),
		_nodo("E", _("E) Aumento/disminución neta del efectivo o equivalentes (5 + 8 + 12 + D)"), "total"),
	]


def _padres_balance() -> dict[str, str | None]:
	padres: dict[str, str | None] = {}

	def visitar(nodo, padre):
		padres[nodo["code"]] = padre
		for hijo in nodo["hijos"]:
			visitar(hijo, nodo["code"])

	visitar(ca.ACTIVO, None)
	visitar(ca.PATRIMONIO_PASIVO, None)
	return padres


_PADRES = _padres_balance()


def destino_balance(code: str) -> tuple[str | None, str | None]:
	"""Línea del estado y epígrafe del balance que la origina para una partida hoja."""
	actual = code
	while actual:
		if actual == EFECTIVO:
			return None, EFECTIVO
		if actual in MAPA_BALANCE:
			return MAPA_BALANCE[actual], actual
		actual = _PADRES.get(actual)
	return None, None


def _inversion_por_cuenta(numero: str, defecto: str) -> str:
	for largo in (4, 3):
		destino = _INVERSION_POR_PREFIJO.get((numero or "")[:largo])
		if destino:
			return destino
	return defecto


class _Acumulador:
	def __init__(self, n: int):
		self.n = n
		self.valores: dict[str, list[float]] = defaultdict(lambda: [0.0] * n)
		self.origen: dict[str, dict[tuple[str, str], list[float]]] = defaultdict(
			lambda: defaultdict(lambda: [0.0] * n)
		)

	def sumar(self, linea: str, i: int, importe: float, codigo: str, nombre: str):
		if abs(importe) < _EPS:
			return
		self.valores[linea][i] += importe
		self.origen[linea][(codigo, nombre)][i] += importe


def _importes_pyg(periodo: ca.Periodo) -> dict[str, float]:
	"""Importe de cada línea, sublínea y subtotal de la PyG de un periodo."""
	importes: dict[str, float] = {}

	def visitar(nodo):
		importes[nodo["code"]] = nodo["importes"][0]
		for hijo in nodo["hijos"]:
			visitar(hijo)

	for linea in ca.lineas_pyg([periodo]):
		visitar(linea)
	return importes


def acumular_periodo(
	acc: _Acumulador, i: int, inicio: ca.Periodo, fin: ca.Periodo, pyg: ca.Periodo
) -> dict[str, float]:
	"""Suma en ``acc`` las líneas del periodo ``i``. Devuelve el efectivo inicial y final."""
	p = _importes_pyg(pyg)

	def etiqueta_pyg(code):
		return _("PyG {0}").format(ca.NODOS_PYG[code]["label"])

	acc.sumar("A.1", i, p["A.3"], "A.3", _("PyG A.3) Resultado antes de impuestos"))
	acc.sumar("A.2.d", i, -p["9"], "9", etiqueta_pyg("9"))
	acc.sumar("C.9.e", i, p["9"], "9", etiqueta_pyg("9"))
	acc.sumar("A.2.g", i, -p["14"], "14", etiqueta_pyg("14"))
	acc.sumar("A.4.b", i, p["14.a"], "14.a", etiqueta_pyg("14.a"))
	acc.sumar("A.4.c", i, p["14.b"], "14.b", etiqueta_pyg("14.b"))
	acc.sumar("A.2.h", i, -p["15"], "15", etiqueta_pyg("15"))
	acc.sumar("A.4.a", i, p["15"], "15", etiqueta_pyg("15"))
	acc.sumar("A.2.i", i, -p["17"], "17", etiqueta_pyg("17"))
	acc.sumar("D", i, p["17"], "17", etiqueta_pyg("17"))
	acc.sumar("A.4.d", i, p["20"], "20", etiqueta_pyg("20"))
	# El resultado del periodo está dentro de la variación de fondos propios.
	acc.sumar("C.11", i, -p["A.5"], "A.5", _("PyG A.5) Resultado del ejercicio (incluido en fondos propios)"))

	for hoja, (linea_ajuste, defecto) in _AJUSTES_INVERSION.items():
		for account, importe in pyg.lineas.get(hoja, {}).items():
			numero = pyg.cuentas[account]["numero"]
			clase = _inversion_por_cuenta(numero, defecto)
			acc.sumar(linea_ajuste, i, -importe, hoja, etiqueta_pyg(hoja))
			acc.sumar(clase, i, importe, hoja, etiqueta_pyg(hoja))

	efectivo = {"inicio": 0.0, "fin": 0.0}
	for code in ca.HOJAS_BALANCE:
		linea, epigrafe = destino_balance(code)
		saldo_inicio = inicio.total(code)
		saldo_fin = fin.total(code)
		if epigrafe == EFECTIVO:
			efectivo["inicio"] += saldo_inicio
			efectivo["fin"] += saldo_fin
			continue
		if not linea:
			continue
		variacion = saldo_fin - saldo_inicio
		flujo = -variacion if ca.lado(code) == "activo" else variacion
		acc.sumar(linea, i, flujo, epigrafe, _("Balance {0}").format(ca.NODOS_BALANCE[epigrafe]["label"]))
	return efectivo


def _redondear(valores):
	return [round(v, 2) for v in valores]


def construir_estado(acc: _Acumulador) -> list[dict]:
	"""Árbol del estado con los importes de ``acc``. Inversiones netas: negativas a 6, positivas a 7."""
	n = acc.n
	valores = {k: list(v) for k, v in acc.valores.items()}
	origen = {k: dict(v) for k, v in acc.origen.items()}
	for indice, (clave, _label) in enumerate(_INVERSIONES):
		letra = "abcdef"[indice]
		neto = valores.get(clave, [0.0] * n)
		valores[f"B.6.{letra}"] = [min(v, 0.0) for v in neto]
		valores[f"B.7.{letra}"] = [max(v, 0.0) for v in neto]
		if any(v < 0 for v in neto):
			origen[f"B.6.{letra}"] = origen.get(clave, {})
		if any(v > 0 for v in neto):
			origen[f"B.7.{letra}"] = origen.get(clave, {})

	def construir(nodo, nivel):
		hijos = [construir(hijo, nivel + 1) for hijo in nodo["hijos"]]
		if hijos:
			importes = [sum(h["importes"][i] for h in hijos if h["tipo"] != "subtotal") for i in range(n)]
		else:
			importes = valores.get(nodo["code"], [0.0] * n)
		cuentas = []
		if not hijos:
			for (codigo, nombre), importes_origen in sorted(origen.get(nodo["code"], {}).items()):
				cuentas.append(
					{
						"codigo": codigo,
						"nombre": nombre,
						"importes": _redondear(importes_origen),
						"subcuentas": [],
						"sintetica": False,
					}
				)
		return {
			"code": nodo["code"],
			"label": nodo["label"],
			"tipo": nodo["tipo"],
			"nivel": nivel,
			"importes": _redondear(importes),
			"hijos": hijos,
			"cuentas": cuentas,
		}

	arbol = [construir(nodo, 0) for nodo in estructura()]
	por_codigo = {}

	def indexar(nodo):
		por_codigo[nodo["code"]] = nodo
		for hijo in nodo["hijos"]:
			indexar(hijo)

	for nodo in arbol:
		indexar(nodo)

	def fijar(code, importes):
		por_codigo[code]["importes"] = _redondear(importes)

	def suma(*codes, signos=None):
		signos = signos or [1] * len(codes)
		return [
			sum(s * por_codigo[c]["importes"][i] for c, s in zip(codes, signos, strict=True))
			for i in range(n)
		]

	fijar("A.5", suma("A.1", "A.2", "A.3", "A.4"))
	fijar("A", por_codigo["A.5"]["importes"])
	fijar("B.8", suma("B.6", "B.7"))
	fijar("B", por_codigo["B.8"]["importes"])
	fijar("C.12", suma("C.9", "C.10", "C.11"))
	fijar("C", por_codigo["C.12"]["importes"])
	fijar("E", suma("A.5", "B.8", "C.12", "D"))
	return arbol


def calcular(company: str, periodos: list[tuple]) -> dict:
	"""Estado de flujos de efectivo de uno o varios periodos ``(desde, hasta)``."""
	acc = _Acumulador(len(periodos))
	efectivo = []
	avisos: dict[str, str] = {}
	for i, (desde, hasta) in enumerate(periodos):
		desde, hasta = getdate(desde), getdate(hasta)
		inicio = ca.calcular_balance(company, add_days(desde, -1))
		fin = ca.calcular_balance(company, hasta)
		pyg, _mensual = ca.calcular_pyg(company, desde, hasta)
		for periodo in (inicio, fin, pyg):
			avisos.update(periodo.avisos)
		efectivo.append(acumular_periodo(acc, i, inicio, fin, pyg))

	arbol = construir_estado(acc)
	total = next(nodo for nodo in arbol if nodo["code"] == "E")["importes"]
	cuadre = []
	for i, saldos in enumerate(efectivo):
		variacion = saldos["fin"] - saldos["inicio"]
		cuadre.append(
			{
				"inicio": round(saldos["inicio"], 2),
				"fin": round(saldos["fin"], 2),
				"variacion": round(variacion, 2),
				"diferencia": round(variacion - total[i], 2),
			}
		)
	return {"lineas": arbol, "efectivo": cuadre, "avisos": sorted(avisos.values())}
