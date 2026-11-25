# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Piezas puras de la gestión financiera: flujos de efectivo, tesorería, costes y existencias."""

from datetime import date

from frappe.tests import UnitTestCase

from spain_compliance.contabilidad import cuentas_anuales as ca
from spain_compliance.finanzas import costes_produccion as cp
from spain_compliance.finanzas import existencias as ex
from spain_compliance.finanzas import flujos_efectivo as fe
from spain_compliance.finanzas import tesoreria as tes


def _hojas(nodos, salida=None):
	salida = set() if salida is None else salida
	for nodo in nodos:
		if nodo.get("hijos"):
			_hojas(nodo["hijos"], salida)
		else:
			salida.add(nodo["code"])
	return salida


class TestFlujosEfectivo(UnitTestCase):
	def test_toda_partida_del_balance_tiene_destino(self):
		for code in ca.HOJAS_BALANCE:
			destino, origen = fe.destino_balance(code)
			if origen == fe.EFECTIVO:
				continue
			self.assertIsNotNone(destino, code)

	def test_destinos_son_lineas_del_estado(self):
		hojas = _hojas(fe.estructura())
		for code, destino in fe.MAPA_BALANCE.items():
			if destino.startswith("inv."):
				continue
			self.assertIn(destino, hojas, code)
		for linea, (ajuste, _clase) in fe._AJUSTES_INVERSION.items():
			self.assertIn(ajuste, hojas, linea)

	def test_inversiones_tienen_cobros_y_pagos(self):
		hojas = _hojas(fe.estructura())
		for letra in "abcdef":
			self.assertIn(f"B.6.{letra}", hojas)
			self.assertIn(f"B.7.{letra}", hojas)


class TestTesoreria(UnitTestCase):
	def test_parse_rangos(self):
		self.assertEqual(tes.parse_rangos("90, 30;60"), (30, 60, 90))
		self.assertEqual(tes.parse_rangos(""), tes.RANGOS_POR_DEFECTO)
		self.assertEqual(tes.parse_rangos("0, -5"), tes.RANGOS_POR_DEFECTO)

	def test_tramo(self):
		rangos = (30, 60, 90)
		self.assertIsNone(tes.tramo(0, rangos))
		self.assertEqual(tes.tramo(1, rangos), 0)
		self.assertEqual(tes.tramo(30, rangos), 0)
		self.assertEqual(tes.tramo(31, rangos), 1)
		self.assertEqual(tes.tramo(91, rangos), 3)
		self.assertEqual(len(tes.etiquetas_rangos(rangos)), 4)

	def test_repartir_en_plazos(self):
		plazos = [
			{"due_date": "2026-01-31", "outstanding": 0},
			{"due_date": "2026-02-28", "outstanding": 300},
			{"due_date": "2026-03-31", "outstanding": 100},
		]
		reparto = tes.repartir_en_plazos(200.0, "2026-01-31", plazos)
		self.assertEqual([f for f, _i in reparto], [date(2026, 2, 28), date(2026, 3, 31)])
		self.assertAlmostEqual(sum(i for _f, i in reparto), 200.0)
		self.assertAlmostEqual(reparto[0][1], 150.0)

	def test_repartir_sin_plazos(self):
		self.assertEqual(tes.repartir_en_plazos(50.0, "2026-05-10", []), [(date(2026, 5, 10), 50.0)])

	def test_tramos_semanales(self):
		periodos = tes.tramos_prevision("2026-11-04", 3, "week")
		self.assertEqual(periodos[0]["inicio"], date(2026, 11, 4))
		self.assertEqual(periodos[0]["fin"], date(2026, 11, 8))
		self.assertEqual(periodos[1]["inicio"], date(2026, 11, 9))
		self.assertEqual(periodos[-1]["fin"], date(2026, 11, 22))

	def test_tramos_mensuales(self):
		periodos = tes.tramos_prevision("2026-11-04", 2, "month")
		self.assertEqual(periodos[0]["fin"], date(2026, 11, 30))
		self.assertEqual(periodos[1]["inicio"], date(2026, 12, 1))
		self.assertEqual(periodos[1]["fin"], date(2026, 12, 31))

	def test_indice_tramo(self):
		periodos = tes.tramos_prevision("2026-11-04", 2, "week")
		self.assertEqual(tes.indice_tramo("2026-10-01", periodos), 0)
		self.assertEqual(tes.indice_tramo("2026-11-10", periodos), 1)
		self.assertIsNone(tes.indice_tramo("2026-12-01", periodos))


class TestCostesProduccion(UnitTestCase):
	def test_naturaleza_por_nombre(self):
		for nombre in ("Mano de obra", "Operario", "Labour", "Salario oficial"):
			self.assertEqual(cp.naturaleza_por_nombre(nombre), cp.NATURALEZA_MO, nombre)
		for nombre in ("Electricidad", "Amortización máquina", None, ""):
			self.assertEqual(cp.naturaleza_por_nombre(nombre), cp.NATURALEZA_CIF, nombre)


class TestExistencias(UnitTestCase):
	def _clase(self, item="X", grupo="G", almacen=None, en_curso=(), grupos=None, fabricados=(), comp=()):
		return ex.clasificar(item, grupo, almacen, set(en_curso), grupos or {}, set(fabricados), set(comp))[0]

	def test_prioridad(self):
		almacen = {"name": "WIP", "clase_existencias": ex.TERMINADOS, "numero_cuenta": "310"}
		self.assertEqual(self._clase(almacen=almacen, en_curso=["WIP"]), ex.TERMINADOS)
		almacen = {"name": "WIP", "numero_cuenta": "310"}
		self.assertEqual(self._clase(almacen=almacen, en_curso=["WIP"]), ex.EN_CURSO)
		self.assertEqual(self._clase(almacen=almacen, grupos={"G": ex.SUBPRODUCTOS}), ex.SUBPRODUCTOS)
		self.assertEqual(self._clase(almacen=almacen), ex.MATERIAS_PRIMAS)

	def test_listas_de_materiales(self):
		self.assertEqual(self._clase(fabricados=["X"]), ex.TERMINADOS)
		self.assertEqual(self._clase(fabricados=["X"], comp=["X"]), ex.SEMITERMINADOS)
		self.assertEqual(self._clase(comp=["X"]), ex.MATERIAS_PRIMAS)
		self.assertEqual(self._clase(), ex.MERCADERIAS)

	def test_cuenta_300_no_fuerza_mercaderias(self):
		almacen = {"name": "A", "numero_cuenta": "300"}
		self.assertEqual(self._clase(almacen=almacen, fabricados=["X"]), ex.TERMINADOS)
