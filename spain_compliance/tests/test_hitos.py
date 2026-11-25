# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Hitos de facturación: importes y línea de la factura (sin escrituras en BD)."""

import unittest
from unittest.mock import patch

import frappe

from spain_compliance.api import hitos

MOD = "spain_compliance.api.hitos"


class TestBases(unittest.TestCase):
	def test_el_ultimo_absorbe_el_redondeo(self):
		bases = hitos._bases(100.01, [33.333, 33.333, 33.334])
		self.assertAlmostEqual(sum(bases), 100.01, places=2)

	def test_porcentaje_sobre_el_neto(self):
		self.assertEqual(hitos._bases(1000.5, [40, 60]), [400.2, 600.3])

	def test_sin_sumar_100_no_se_fuerza(self):
		self.assertEqual(hitos._bases(1000, [10, 20]), [100, 200])

	def test_vacio(self):
		self.assertEqual(hitos._bases(1000, []), [])


class TestLineaHito(unittest.TestCase):
	def _linea(self, descripcion, pct, total=2, idioma="es"):
		plazo = frappe._dict(name="f1", idx=1, description=descripcion, invoice_portion=pct)
		pedido = frappe._dict(
			name="SO-1", customer="C", currency="EUR", net_total=1000, payment_schedule=[plazo] * total
		)
		with (
			patch(f"{MOD}.frappe.get_cached_value", return_value=idioma),
			patch.object(frappe.db, "get_single_value", return_value="Ud."),
			patch(f"{MOD}.fmt_money", return_value="1.000,00"),
		):
			return hitos._linea_hito(pedido, plazo, 500.0, "700", "CC")

	def test_nombre_y_porcentaje(self):
		linea = self._linea("Anticipo al pedido", 50)
		self.assertEqual(linea["item_name"], "Anticipo al pedido — 50 %")
		self.assertEqual(linea["description"], "50 % de 1.000,00 EUR")
		self.assertEqual((linea["qty"], linea["rate"]), (1, 500.0))
		self.assertEqual(linea["sales_order"], "SO-1")
		self.assertNotIn("so_detail", linea)
		self.assertNotIn("item_code", linea)

	def test_no_repite_el_porcentaje(self):
		self.assertEqual(self._linea("Entrega 50%", 50)["item_name"], "Entrega 50%")
		self.assertEqual(self._linea("Resto tras 150%", 50)["item_name"], "Resto tras 150% — 50 %")

	def test_ingles(self):
		self.assertEqual(self._linea("Order", 8.666, idioma="en")["description"], "8,666 % of 1.000,00 EUR")

	def test_nombre_largo_cabe(self):
		self.assertLessEqual(len(self._linea("x" * 300, 8.666)["item_name"]), 140)


class TestSeguimiento(unittest.TestCase):
	def test_sin_hook(self):
		with patch(f"{MOD}.frappe.get_hooks", return_value=[]):
			self.assertEqual(hitos._seguimiento(["SO-1"]), {})

	def test_con_hook(self):
		marcas = {"f1": {"billing_status": "Facturado"}}
		with (
			patch(f"{MOD}.frappe.get_hooks", return_value=["app.f"]),
			patch(f"{MOD}.frappe.get_attr", return_value=lambda pedidos: marcas),
		):
			self.assertEqual(hitos._seguimiento(["SO-1"]), marcas)


class TestAsignar(unittest.TestCase):
	def test_parte_sobre_el_neto(self):
		lista = [
			{"fila": "a", "porcentaje": 40, "marcado_facturado": False, "facturas": []},
			{"fila": "b", "porcentaje": 60, "marcado_facturado": False, "facturas": []},
		]
		f = frappe._dict(name="F1", docstatus=1, is_return=0, hito_pedido="b", importe=600)
		hitos._asignar(lista, [f], 1000)
		self.assertEqual(lista[0]["facturas"], [])
		self.assertEqual(lista[1]["facturas"][0]["parte"], 60)
