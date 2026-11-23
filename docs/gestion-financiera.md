# Gestión financiera

Informes de tesorería, costes, márgenes e indicadores en `/contabilidad`. Todo se
calcula sobre los documentos y el libro mayor de ERPNext; no hay tablas propias ni
procesos nocturnos. Funciona en cualquier compañía con el plan PGC (los informes
contables necesitan número de cuenta). Probado en ERPNext v16; los campos que cambian
entre versiones (almacén de trabajo en curso, componentes de coste del puesto,
subproductos) se detectan en tiempo de ejecución.

## Pantallas

| Sección | Pantalla | Ruta | Fuente |
|---------|----------|------|--------|
| — | Indicadores de gestión | `/indicators` | PyG y balance PGC, facturas, empleados |
| Tesorería | Cuentas a cobrar | `/receivables` | Payment Ledger Entry, Payment Schedule |
| Tesorería | Cuentas a pagar | `/payables` | Payment Ledger Entry, Payment Schedule |
| Tesorería | Previsión de tesorería | `/cash-forecast` | Saldos de bancos y caja, vencimientos, pedidos, histórico |
| Costes y márgenes | Costes de producción | `/production-costs` | Work Order, Stock Entry, Workstation |
| Costes y márgenes | Valoración de existencias | `/stock-valuation` | Stock Ledger Entry |
| Costes y márgenes | Rentabilidad por línea | `/profitability` | Gross Profit de ERPNext o GL por dimensión |
| Informes | Estado de flujos de efectivo | `/cash-flow-statement` | Balance y PyG PGC |

## Cuentas a cobrar y a pagar

- Pendiente por documento a la fecha elegida, en moneda de la compañía, a partir del
  *Payment Ledger Entry* (recoge cobros parciales, anticipos aplicados y abonos).
- Antigüedad por tramos configurables (por defecto 30, 60, 90 y 120 días) desde el
  vencimiento.
- Solo se detallan clientes y proveedores. Los saldos de otros terceros (empleados,
  socios) se muestran como un total sin nombre.
- Las facturas en *Dudoso Cobro* y *Pérdida* se separan del resto.
- En pagos, calendario semanal por plazos de la condición de pago y periodo medio de
  pago a proveedores según la Resolución del ICAC de 29 de enero de 2016 (límite legal
  de 60 días).

## Previsión de tesorería

Saldo inicial de las cuentas de bancos y caja (tipo *Bank* o *Cash*, o subgrupo 57) más
cobros y pagos previstos por semana o por mes.

| Fuente | Qué incluye |
|--------|-------------|
| Facturas | Pendiente de facturas de venta y compra repartido por sus plazos |
| Pedidos | Pedidos de venta y compra validados aún sin facturar, menos anticipos |
| Recurrentes | Media mensual de los últimos meses de cobros y pagos sin cliente ni proveedor (nóminas, impuestos, préstamos), por grupo del PGC de la contrapartida |

Lo vencido se trata según el filtro *Vencidos*. La opción *Prudente* (por defecto)
lleva los pagos vencidos al primer periodo y deja fuera los cobros vencidos, que se
muestran aparte. *Todos* los incluye en el primer periodo; *Ninguno* los ignora. El
saldo mínimo de seguridad marca los periodos que quedan por debajo.

## Estado de flujos de efectivo

Modelo normal del PGC por el método indirecto, con comparación con el año anterior.

- Cada partida del balance tiene una línea de destino (`MAPA_BALANCE` en
  `finanzas/flujos_efectivo.py`). La variación de cada partida entre el inicio y el
  fin del periodo va a su línea.
- Las amortizaciones, deterioros y resultados por enajenación de la PyG se ajustan en
  explotación y se compensan en la clase de inversión correspondiente.
- Las inversiones de una misma clase se presentan netas, como pagos o como cobros.
- Por construcción el total E coincide con la variación del efectivo (B.VII). Si no
  coincide, la pantalla avisa; suele indicar un balance descuadrado.

## Costes de producción

Por cada orden de fabricación del periodo (iniciada en él o con fabricación o consumo
de material en él).

- **Estándar.** Materiales de la orden (tasa × cantidad requerida) y coste de operación
  planificado, escalados a la cantidad producida. Si la orden no tiene tasas se usa el
  coste de la lista de materiales.
- **Real.** Entradas de stock de fabricación y de consumo de material validadas, más
  los costes adicionales de esas entradas.
- **Mano de obra (MO) y costes indirectos (CIF).** Se separan con el campo
  *Naturaleza del coste* del *Workstation Operating Component*. Si está vacío se
  deduce del nombre (mano de obra, operario, salario, labour… → MO; el resto → CIF).
  Los puestos sin componentes cuentan como CIF.
- **Desviaciones.** Total y por componente. En materiales se separa la desviación de
  cantidad (a precio estándar) de la de precio (sobre la cantidad real).

## Valoración de existencias

Valor del libro de stock a una fecha, por clase del PGC (subgrupos 30 a 36), almacén y
artículo, con artículos sin salidas en *N* días y existencias negativas. Con inventario
permanente se compara con el saldo de las cuentas de existencias de los almacenes.

La clase se decide por este orden.

1. Campo *Clase de existencias* del almacén.
2. Almacén de trabajo en curso (compañía, ajustes de fabricación u órdenes) → productos
   en curso.
3. Campo *Clase de existencias* del grupo de artículos o de un grupo padre.
4. Cuenta de existencias del almacén, si es de los subgrupos 31 a 36.
5. Uso en listas de materiales. Si se fabrica y es componente es semiterminado; si solo
   se fabrica, terminado; si solo es componente, materia prima. En otro caso,
   mercaderías.

## Rentabilidad por línea

- **Margen comercial.** Ventas menos coste de lo vendido por grupo de artículos,
  artículo, marca, grupo de clientes, cliente o territorio. Usa el generador del
  informe *Gross Profit* de ERPNext. Las ventas sin coste (servicios, artículos sin
  stock) se señalan.
- **Resultado analítico.** Ingresos y gastos de los grupos 6 y 7 por proyecto, centro de
  coste o cualquier dimensión contable activa, en columnas de la PyG (cifra de negocios,
  aprovisionamientos, personal, otros gastos, amortización, financiero). Es la lectura
  adecuada para obras y proyectos, porque incluye mano de obra y servicios.

## Indicadores de gestión

EBITDA, márgenes (bruto, EBITDA, operativo, neto), liquidez, prueba ácida,
disponibilidad, fondo de maniobra, endeudamiento, solvencia, ROA y ROE anualizados,
plazos de cobro, pago y existencias, ciclo de caja, periodo medio de pago (ICAC) e
ingreso y EBITDA por empleado. Cada indicador muestra su fórmula y se compara con el
mismo periodo del año anterior.

La plantilla media es el campo *Plantilla media* de la compañía si está informado. Si
no, se calcula como la media de empleados en alta al cierre de cada mes. Solo se usa el
recuento, nunca datos individuales.

## Configuración

| DocType | Campo | Uso |
|---------|-------|-----|
| Company | Plantilla media (sección *Indicadores*) | Ingreso por empleado. Vacío = se calcula con los empleados |
| Warehouse | Clase de existencias | Fuerza la clase del PGC de todo lo que hay en el almacén |
| Item Group | Clase de existencias | Clase de los artículos del grupo y sus subgrupos |
| Workstation Operating Component | Naturaleza del coste | Mano de obra o costes indirectos |

## Permisos

Los informes exigen permiso de lectura sobre el origen de los datos. Los contables
necesitan *GL Entry*, las cuentas a cobrar *Sales Invoice*, las cuentas a pagar
*Purchase Invoice*, los costes *Work Order* y las existencias *Stock Ledger Entry*.
