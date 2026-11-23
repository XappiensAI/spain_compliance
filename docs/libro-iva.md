# Libro de IVA (sobre el mayor)

El libro de IVA, la liquidación y el SII se calculan **sobre los apuntes contables de IVA**. No se guarda ningún registro aparte (hasta la v0.3 existía el DocType *Registro Fiscal IVA*; se retiró para no duplicar información). La copia y la exigencia de la clasificación solo actúan en compañías con país **Spain** o con el Plan General Contable activo.

Código — `spain_compliance.contabilidad.libro_iva.movimientos_iva(company, desde, hasta, libro)`.

## De dónde sale cada dato

| Dato | Origen |
|------|--------|
| Cuota | `GL Entry` de las cuentas de impuestos (`account_type = Tax`), no canceladas, agrupado por documento y cuenta |
| Tipo, clave de IVA, deducibilidad, clave de retención | Fila de impuestos del documento con esa cuenta. Si los artículos usan una *Item Tax Template* con clave, manda esa |
| Base imponible | `base_net_amount` de la fila (negativa en rectificativas) |
| Tercero, NIF, país, nº de factura del proveedor, factura rectificada | Cabecera del documento y ficha del tercero |
| Cuota deducible (recibidas) | Cuota × prorrata general de la compañía (0 si la fila es *No deducible*) |

Por construcción, **la suma de cuotas de un periodo es el movimiento de las cuentas de impuestos** en el mayor.

- Las operaciones sin cuota (exentas, no sujetas, al 0 %) no generan apunte. El libro las añade desde las filas de impuestos con cuota 0 de las facturas validadas del periodo, y añade una línea *sin clasificar* por cada factura validada sin ninguna fila de impuestos.
- Los apuntes de IVA de asientos manuales (Journal Entry) salen *sin clasificar*. Si la cuenta empieza por 477 van a expedidas y si empieza por 472 a recibidas.
- Una factura cancelada no está en el mayor, así que no sale en el libro.
- La autorrepercusión (adquisiciones intracomunitarias, inversión del sujeto pasivo) es la fila que *resta* en la compra. Sale marcada como `autorrepercusion` y la liquidación la suma al IVA devengado.

## Clasificación

En cada fila de impuesto (y en la plantilla, que es el mismo dato) sección *Clasificación fiscal (España)*:

| Campo | Uso |
|-------|-----|
| Tipo de impuesto | IVA, recargo de equivalencia, retención de IRPF, IGIC, IPSI u otro. |
| Clave de IVA | Sujeta, exenta (por artículo), no sujeta, inversión del sujeto pasivo, intracomunitaria, importación, exportación… El código (`S1`, `E1`, `AIB`) es lo que usarán los modelos. |
| Deducibilidad | Solo compras de IVA, recargo, IGIC o IPSI: corriente o bien de inversión (los dos aplican la prorrata de la compañía) o no deducible. |
| Clave de retención | Trabajo, actividades económicas, arrendamiento, capital mobiliario o premios. |

En **Item Tax Template**, *Clave de IVA* sustituye a la de la fila de impuesto para los artículos que usen esa plantilla. Sirve para una factura con operaciones de distinta clave (sujeta y exenta).

Si la fila de la factura está vacía y hay plantilla, al validar se copia la clasificación de la fila de plantilla con la misma cuenta y el mismo tipo. Lo ya informado en la factura no se pisa.

## Qué se guarda

Por cada fila de impuesto con tipo informado, o sin tipo pero con cuenta de tipo *Tax* (un cargo *Actual* que no sea impuesto no entra):

- Libro: expedidas o recibidas.
- Ejercicio, trimestre (`1T`…`4T`) y mes, por la fecha de contabilización.
- Tercero, con el NIF y el tipo de identificación tal como estaban al validar. País `ES` si el NIF es español; si es NIF-IVA, las dos letras del país.
- Tipo de factura `F1`, o `R1` si es rectificativa, con la factura rectificada.
- Base, tipo y cuota en moneda de la compañía. Una rectificativa queda en negativo, así que el trimestre cuadra al sumar.
- En compras de IVA, recargo, IGIC o IPSI, cuota deducible: cero si no es deducible; en corriente y en bien de inversión, la cuota por la prorrata general. La prorrata vacía cuenta como 100 %. La regularización de los bienes de inversión en años posteriores queda para el modelo 303.
- *Pendiente de clasificar* si falta el tipo, la clave o, en compras, la deducibilidad.

La base sale de la cuota y el tipo (`cuota × 100 / tipo`). Al 0 % se usa el neto de los artículos de esa clave.

## Aviso o bloqueo

Por defecto la factura se valida igual y las filas quedan pendientes de clasificar, con un aviso. **Exigir clasificación fiscal** en la compañía (sección *Fiscalidad*) impide validarla —el borrador se guarda— hasta que cada impuesto tenga tipo, clave (también IGIC e IPSI) y, en compras, deducibilidad.

## Identificación del tercero

En Cliente y Proveedor, *Tipo de identificación fiscal*. Al guardar se comprueba el dígito de control del NIF, NIE o CIF, y el NIF-IVA (si empieza por `ES`, el resto tiene que ser un NIF válido; otro país solo se comprueba el formato). Si no cuadra se avisa y el tercero se guarda igual. Pasaporte, documento oficial y certificado de residencia no se validan como NIF.

## Identificación del tercero

En Cliente y Proveedor, *Tipo de identificación fiscal*. Al guardar se comprueba el dígito de control del NIF, NIE o CIF, y el NIF-IVA (si empieza por `ES`, el resto tiene que ser un NIF válido; otro país solo se comprueba el formato). Si no cuadra se avisa y el tercero se guarda igual. Pasaporte, documento oficial y certificado de residencia no se validan como NIF.
