# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Plazo de envío: 4 días hábiles y antes del día 16 del mes siguiente.

Son hábiles los días que no son sábado, domingo ni festivo nacional. Los
festivos autonómicos y locales no se descuentan (criterio conservador: el plazo
nunca sale más largo que el real).
"""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.easter import easter
from frappe.utils import getdate

DIAS_PLAZO = 4

_FESTIVOS_FIJOS = ((1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25))


def festivos_nacionales(anio: int) -> set[date]:
	dias = {date(anio, m, d) for m, d in _FESTIVOS_FIJOS}
	dias.add(easter(anio) - timedelta(days=2))  # Viernes Santo
	return dias


def es_habil(dia: date) -> bool:
	return dia.weekday() < 5 and dia not in festivos_nacionales(dia.year)


def sumar_habiles(desde, dias: int) -> date:
	dia = getdate(desde)
	sumados = 0
	while sumados < dias:
		dia += timedelta(days=1)
		if es_habil(dia):
			sumados += 1
	return dia


def fecha_limite(fecha_base, fecha_periodo) -> date:
	"""Cuatro días hábiles desde ``fecha_base``, como mucho el 15 del mes siguiente a ``fecha_periodo``."""
	limite = sumar_habiles(fecha_base, DIAS_PLAZO)
	p = getdate(fecha_periodo)
	tope = date(p.year + 1, 1, 15) if p.month == 12 else date(p.year, p.month + 1, 15)
	return min(limite, tope)
