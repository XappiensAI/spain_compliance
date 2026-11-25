# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Elección de formato y motor del PDF de facturas."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from spain_compliance.api import impresion


class TestImpresion(FrappeTestCase):
	def _motor(self, resuelto, wkhtmltopdf=None, plutoprint=True):
		with (
			patch.object(impresion, "resolve_pdf_generator", return_value=resuelto),
			patch.object(impresion.shutil, "which", return_value=wkhtmltopdf),
			patch.object(impresion.importlib.util, "find_spec", return_value=plutoprint or None),
		):
			return impresion._motor("Standard")

	def test_respeta_el_motor_del_formato(self):
		self.assertEqual(self._motor("PlutoPrint"), "PlutoPrint")
		self.assertEqual(self._motor("chrome"), "chrome")
		self.assertEqual(self._motor("wkhtmltopdf", wkhtmltopdf="/usr/bin/wkhtmltopdf"), "wkhtmltopdf")

	def test_sin_wkhtmltopdf_usa_otro_motor(self):
		self.assertEqual(self._motor("wkhtmltopdf"), "PlutoPrint")
		self.assertEqual(self._motor("wkhtmltopdf", plutoprint=False), "chrome")

	def test_solo_facturas(self):
		self.assertRaises(frappe.ValidationError, impresion.descargar_pdf, "User", "Administrator")
