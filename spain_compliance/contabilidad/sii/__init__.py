# Copyright (c) 2026, Xappiens and contributors
# License: MIT

"""Suministro Inmediato de Información (SII) de la AEAT.

- :mod:`.constantes` — URLs, espacios de nombres y estados.
- :mod:`.datos` — factura → datos SII, a partir del libro de IVA sobre el mayor.
- :mod:`.xml` — mensajes SOAP (alta, modificación, baja, consulta) y lectura de respuestas.
- :mod:`.transporte` — llamada HTTPS a la AEAT con el certificado de la compañía.
- :mod:`.registro` — *SII Registro*: creación, envío, consulta y tareas programadas.
"""
