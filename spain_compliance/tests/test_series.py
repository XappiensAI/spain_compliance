# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Series de facturación por compañía (sin escrituras en BD)."""

import unittest
from unittest.mock import patch

import frappe

from spain_compliance.contabilidad import series

MOD = "spain_compliance.contabilidad.series"

CONFIG = {
	("Sales Invoice", "SRG", False): "FV.YY.#####",
	("Sales Invoice", "SRG", True): "AV.YY.#####",
	("Sales Invoice", "KDK", False): "KFV.YY.#####",
	("Sales Invoice", "KDK", True): "KAV.YY.#####",
}


def _serie_compania(doctype, company, es_rect):
	return CONFIG.get((doctype, company, bool(es_rect)))


def _otras(doctype, company):
	return {
		serie: comp
		for (dt, comp, _r), serie in CONFIG.items()
		if dt == doctype and comp != company
	}


def _doc(**kw):
	return frappe._dict({"doctype": "Sales Invoice", "is_return": 0, "naming_series": "", **kw})


@patch(f"{MOD}.serie_por_defecto", return_value="ACC-SINV-.YYYY.-")
@patch(f"{MOD}.series_de_otras_companias", side_effect=_otras)
@patch(f"{MOD}.serie_compania", side_effect=_serie_compania)
class TestAplicarSerie(unittest.TestCase):
	def test_vacia_toma_la_de_la_compania(self, *_):
		doc = _doc(company="SRG")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "FV.YY.#####")

	def test_por_defecto_se_sustituye(self, *_):
		doc = _doc(company="KDK", naming_series="ACC-SINV-.YYYY.-")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "KFV.YY.#####")

	def test_serie_de_otra_compania_se_sustituye(self, *_):
		doc = _doc(company="KDK", naming_series="FV.YY.#####")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "KFV.YY.#####")

	def test_serie_elegida_a_mano_se_respeta(self, *_):
		doc = _doc(company="SRG", naming_series="FVC.YY.#####")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "FVC.YY.#####")

	def test_rectificativa_sale_de_la_ordinaria(self, *_):
		doc = _doc(company="SRG", is_return=1, naming_series="FV.YY.#####")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "AV.YY.#####")

	def test_compania_sin_serie_no_toca(self, *_):
		doc = _doc(company="OTRA", naming_series="X-.####")
		series.aplicar_serie(doc)
		self.assertEqual(doc.naming_series, "X-.####")


@patch(f"{MOD}.series_de_otras_companias", side_effect=_otras)
@patch(f"{MOD}.serie_compania", side_effect=_serie_compania)
class TestValidarSerie(unittest.TestCase):
	def test_serie_de_otra_compania_bloquea(self, *_):
		with self.assertRaises(frappe.ValidationError):
			series.validar_serie(_doc(company="KDK", naming_series="FV.YY.#####"))

	def test_serie_propia_ok(self, *_):
		series.validar_serie(_doc(company="SRG", naming_series="AV.YY.#####"))

	def test_serie_libre_ok(self, *_):
		series.validar_serie(_doc(company="SRG", naming_series="FVC.YY.#####"))
