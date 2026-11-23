# SII — Suministro Inmediato de Información

Comunicación de las facturas emitidas y recibidas a la AEAT (esquema 1.1). Los
importes salen del [libro de IVA sobre el mayor](libro-iva.md), así que el SII cuadra
con el libro y con la liquidación. El certificado es el
[Certificado Digital](certificados-digitales.md) de la compañía con uso SII.

Código — `spain_compliance/contabilidad/sii/` (datos, XML, transporte, registro) y la
API `spain_compliance.api.sii`.

## Configuración (*SII Configuracion*, una por compañía)

| Campo | Uso |
|-------|-----|
| Activo | Crea un registro pendiente al validar cada factura desde la fecha de inicio |
| Entorno | Pruebas (sin efectos fiscales) o Producción. Al pasar a Producción, lo aceptado en Pruebas vuelve a Pendiente |
| Fecha de inicio | Solo se comunican las facturas con fecha contable igual o posterior. Las anteriores se pueden consultar |
| Envío automático | Cada 15 minutos se envían los pendientes y se reintentan los errores de comunicación (hasta 10 veces) |
| Comunicar facturas recibidas | Libro de recibidas activado o no |
| Certificado / Certificado de sello | Certificado concreto (vacío = el vigente con uso SII). Sello usa los servidores `www10` |
| Nombre y NIF del titular | Cabecera. Vacío = datos de la compañía |
| Tipo de operación con extranjeros | Entrega o prestación de servicios cuando la clave no lo fija. Automático = entrega si la mayor parte del neto son artículos de stock |

## Registro (*SII Registro*, uno por factura)

Estados — Pendiente, Aceptado, Aceptado con errores, Rechazado, Error de comunicación,
Error de datos, Baja pendiente, Dado de baja, No aplica. Guarda CSV, código y texto de
error, fecha límite, XML enviado, respuesta y el historial de envíos y consultas.

- **Alta (A0)** — primer envío. Si la AEAT dice *Factura duplicada* y la tiene como
  correcta, el registro queda aceptado y lo siguiente va como **modificación (A1)**. Si
  la tiene anulada, se reenvía solo como A1.
- **Errores de datos** — falta clave de IVA, NIF, número del proveedor… No se envía y
  el mensaje dice qué corregir.
- **Cancelar** una factura comunicada la deja en *Baja pendiente*. La baja se envía a
  mano. Una factura sin comunicar se cancela y su registro se borra.
- **Plazo** — 4 días hábiles (sin sábados, domingos ni festivos nacionales) desde la
  expedición (emitidas) o el registro contable (recibidas), y como mucho el día 15 del
  mes siguiente.
- **Consulta** — por factura o por periodo completo (*cruzar periodo*). Con el entorno de
  la configuración actualiza los registros y crea los de las facturas que la AEAT ya
  tiene (por ejemplo las comunicadas por otro programa). Con otro entorno solo informa.

## De clave de IVA a SII

| Clave | Emitidas | Recibidas |
|-------|----------|-----------|
| S1 | NoExenta S1 con DetalleIVA | DesgloseIVA |
| ISP | NoExenta S2 (tipo 0) | InversionSujetoPasivo, clave 01 |
| E1–E6, EIB, EXP | Exenta con su causa (EIB → E5, EXP → E2). Con E2 clave de régimen 02 | DetalleIVA solo con base |
| N1 / N2, SEU | NoSujeta (arts. 7 y 14 / localización) | No se comunica (*No aplica* si solo hay no sujetas) |
| AIB | — | DesgloseIVA, clave 09 |
| AIS | — | InversionSujetoPasivo, clave 09 (a validar con el asesor) |
| IMP | — | Factura F5, emisor el propio titular |
| Recargo de equivalencia | En el mismo DetalleIVA que el IVA de su base | Igual |

Con contraparte extranjera (IDOtro o NIF que empieza por N) se usa
`DesgloseTipoOperacion`. Las claves de exportación e intracomunitaria van en *Entrega*;
N2 y SEU en *Prestación de servicios*.

Las rectificativas van como `R1` por diferencias (`TipoRectificativa = I`) con la factura
rectificada. Los impuestos de importe fijo dan tipos como 20,99 %; se ajustan al tipo legal
cuya cuota cuadra (2 céntimos o 1 %).

El tercero sin tipo de identificación es NIF si valida como español, NIF-IVA (`02`) si
empieza por el prefijo de un país UE, y documento oficial (`04`) en el resto.

## API

| Método | Qué hace |
|--------|----------|
| `resumen(company)` | Configuración, certificado, contadores y permisos |
| `registros(company, libro, estado, ...)` | Listado filtrado |
| `registro(name)` | Detalle con historial y XML |
| `enviar(registros \| documentos, modificar)` | Envía (más de 50 → cola `long`) |
| `enviar_pendientes(company)` / `generar(company)` | Todo lo pendiente / registros que falten |
| `consultar(registros \| documentos, entorno)` | Estado en la AEAT |
| `sincronizar(company, libro, ejercicio, periodo, entorno)` | Cruce de un mes |
| `vista_previa(doctype, name)` | XML y errores sin enviar |
| `estado_documentos(doctype, names)` | Estado SII para listados |

Leer — Accounts User, Accounts Manager, System Manager. Comunicar con la AEAT —
Accounts Manager y System Manager.
