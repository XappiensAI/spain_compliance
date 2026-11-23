/**
 * Estado de la vista de detalle de una factura.
 *
 * El documento vive entero en el cliente. Cada cambio que afecta a importes,
 * cuentas o impuestos se manda a `calcular`, que rellena lo que falta y
 * recalcula sin guardar (la misma lógica que el formulario de Desk, pero en el
 * servidor). Si el usuario sigue escribiendo mientras el servidor responde, la
 * respuesta se descarta y se vuelve a pedir con el documento al día.
 */
import { computed, reactive, ref, shallowRef } from 'vue'
import { call } from 'frappe-ui'
import { errorMessage } from '@/composables/sii'

export const API = 'spain_compliance.api.facturas'

// Campos que no cambian importes ni dependencias: no hace falta recalcular.
const SIN_CALCULO = new Set([
  'remarks',
  'po_no',
  'po_date',
  'description',
  'item_name',
  'letter_head',
  'select_print_heading',
  'language',
  'tipo_impuesto',
  'clave_iva',
  'clave_retencion',
  'deducible_iva',
  'project',
  'cost_center',
  'income_account',
  'expense_account',
  'warehouse',
  'batch_no',
  'serial_no',
  'debit_to',
  'credit_to',
  'bill_no',
  'supplier_name',
  'customer_name',
  'on_hold',
  'hold_comment',
  'release_date',
  'contact_person',
  'naming_series',
])

// Campos que se escriben con el teclado: se espera a que paren de teclear.
const TECLEO = new Set([
  'qty',
  'rate',
  'price_list_rate',
  'discount_percentage',
  'discount_amount',
  'margin_rate_or_amount',
  'conversion_factor',
  'additional_discount_percentage',
  'tax_amount',
  'conversion_rate',
])

/** Lo que cambia entre la factura de venta y la de compra. */
export const TIPOS = {
  'Sales Invoice': {
    doctype: 'Sales Invoice',
    compra: false,
    titulo: 'Facturas de venta',
    lista: 'SalesInvoices',
    ruta: 'SalesInvoice',
    tercero: 'customer',
    terceroDoctype: 'Customer',
    terceroNombre: 'customer_name',
    terceroLabel: 'Cliente',
    terceroFiltro: { disabled: 0 },
    cuenta: 'debit_to',
    cuentaTipo: 'Receivable',
    cuentaLabel: 'Cuenta del cliente',
    cuentaLinea: 'income_account',
    cuentaLineaLabel: 'Cuenta de ingresos',
    tarifa: 'selling_price_list',
    tarifaFiltro: { selling: 1, enabled: 1 },
    direccion: 'customer_address',
    envio: 'shipping_address_name',
    envioTexto: 'shipping_address',
    articuloFiltro: { is_sales_item: 1 },
    cobro: 'Cobro',
    cobros: 'Cobros',
    pendiente: 'Pendiente de cobro',
  },
  'Purchase Invoice': {
    doctype: 'Purchase Invoice',
    compra: true,
    titulo: 'Facturas de compra',
    lista: 'PurchaseInvoices',
    ruta: 'PurchaseInvoice',
    tercero: 'supplier',
    terceroDoctype: 'Supplier',
    terceroNombre: 'supplier_name',
    terceroLabel: 'Proveedor',
    terceroFiltro: { disabled: 0 },
    cuenta: 'credit_to',
    cuentaTipo: 'Payable',
    cuentaLabel: 'Cuenta del proveedor',
    cuentaLinea: 'expense_account',
    cuentaLineaLabel: 'Cuenta de gasto',
    tarifa: 'buying_price_list',
    tarifaFiltro: { buying: 1, enabled: 1 },
    direccion: 'supplier_address',
    envio: 'shipping_address',
    envioTexto: 'shipping_address_display',
    articuloFiltro: { is_purchase_item: 1 },
    cobro: 'Pago',
    cobros: 'Pagos',
    pendiente: 'Pendiente de pago',
  },
}

const configCache = {}

/** Llamada de solo lectura: tras un corte de red (p. ej. reinicio del servidor) se reintenta una vez. */
async function leer(metodo, args) {
  try {
    return await call(metodo, args)
  } catch (err) {
    if (!(err instanceof TypeError)) throw err
    await new Promise((r) => setTimeout(r, 800))
    return call(metodo, args)
  }
}

export async function cargarConfiguracion(doctype = 'Sales Invoice') {
  if (!configCache[doctype]) {
    configCache[doctype] = leer(`${API}.configuracion`, { doctype }).catch((e) => {
      delete configCache[doctype]
      throw e
    })
  }
  return configCache[doctype]
}

function copia(valor) {
  return JSON.parse(JSON.stringify(valor))
}

export function useFactura(doctype = 'Sales Invoice') {
  const tipo = TIPOS[doctype]
  const doc = ref(null)
  const permisos = ref({})
  const contexto = ref({})
  const avisos = ref([])
  const config = shallowRef(null)
  const cargando = ref(false)
  const calculando = ref(false)
  const guardando = ref('')
  const sucio = ref(false)
  const error = ref('')

  let version = 0
  // Sube con cada respuesta de guardar/validar/cargar: un recálculo enviado antes se descarta.
  let epoca = 0
  // Cambios aún no enviados, con la clave de fila del cliente (no el índice).
  let pendientes = []
  let temporizador = null
  let enCurso = null
  let reintento = false

  const esNuevo = computed(() => Boolean(doc.value?.__islocal))
  // Se puede recalcular (borrador con permiso) …
  const calculable = computed(
    () => doc.value?.docstatus === 0 && Boolean(permisos.value.write),
  )
  // … y editar en pantalla, salvo mientras se guarda.
  const editable = computed(() => calculable.value && !guardando.value)

  const monedaEmpresa = computed(
    () =>
      (config.value?.companias || []).find((c) => c.name === doc.value?.company)
        ?.default_currency || doc.value?.currency,
  )
  const dimensiones = computed(() =>
    (config.value?.dimensiones || []).map((d) => ({ campo: d.fieldname, label: d.label })),
  )

  /** Pasa las claves de fila del documento anterior al nuevo (mismo orden). */
  function conservarClaves(anterior, nuevo) {
    if (!anterior || !nuevo) return
    for (const tabla of ['items', 'taxes']) {
      ;(nuevo[tabla] || []).forEach((r, i) => {
        const k = anterior[tabla]?.[i]?.__key
        if (k) r.__key = k
      })
    }
  }

  function aplicarRespuesta(res, { limpio = true, mismoDoc = false } = {}) {
    epoca++
    clearTimeout(temporizador)
    pendientes = []
    if (mismoDoc) conservarClaves(doc.value, res.doc)
    doc.value = res.doc
    if (res.permisos) permisos.value = res.permisos
    if (res.contexto) contexto.value = res.contexto
    avisos.value = res.avisos || []
    if (limpio) sucio.value = false
  }

  async function iniciar(fn) {
    cargando.value = true
    error.value = ''
    try {
      config.value = await cargarConfiguracion(doctype)
      aplicarRespuesta(await fn())
    } catch (e) {
      error.value = e
    } finally {
      cargando.value = false
    }
  }

  const cargar = (name) => iniciar(() => leer(`${API}.obtener`, { name, doctype }))
  const nueva = (args = {}) => iniciar(() => leer(`${API}.nueva`, { ...args, doctype }))
  const duplicar = (name) => iniciar(() => leer(`${API}.duplicar`, { name, doctype }))
  const rectificar = (name) => iniciar(() => leer(`${API}.rectificar`, { name, doctype }))
  // Factura de venta de un hito (fila del calendario de pagos) de una orden de venta.
  const desdeHito = (pedido, fila) =>
    iniciar(() => leer('spain_compliance.api.hitos.factura_desde_hito', { sales_order: pedido, fila }))

  /** Cambia un campo de la cabecera o de una fila y programa el recálculo. */
  function cambiar(campo, valor, { tabla = null, fila = null } = {}) {
    if (!doc.value || guardando.value) return
    if (tabla) {
      const row = doc.value[tabla]?.find((r) => clave(r) === fila)
      if (!row || row[campo] === valor) return
      row[campo] = valor
    } else {
      if (doc.value[campo] === valor) return
      doc.value[campo] = valor
    }
    sucio.value = true
    version++
    if (!calculable.value || SIN_CALCULO.has(campo)) return
    pendientes.push(tabla ? { tabla, clave: fila, campo } : { campo })
    programar(TECLEO.has(campo) ? 450 : 0)
  }

  /** Clave estable de una fila en el cliente: no cambia al guardar ni al reordenar. */
  function clave(row) {
    if (!row.__key) row.__key = row.name || `k${Math.random().toString(36).slice(2, 9)}`
    return row.__key
  }

  /**
   * Cómo identifica el servidor la fila en el documento que se le envía: por
   * `name` si ya existe, si no por su posición en ese momento.
   */
  function paraServidor(cambios, enviado) {
    return cambios
      .map((c) => {
        if (!c.tabla) return c
        const row = enviado[c.tabla]?.find((r) => r.__key === c.clave)
        if (!row) return null // la fila se ha quitado
        return { tabla: c.tabla, fila: row.name || String(row.idx), campo: c.campo }
      })
      .filter(Boolean)
  }

  function programar(retardo) {
    clearTimeout(temporizador)
    temporizador = setTimeout(recalcular, retardo)
  }

  async function recalcular() {
    if (!doc.value || !calculable.value) return
    if (enCurso) {
      // Se vuelve a lanzar al terminar el que está en marcha.
      programar(150)
      return
    }
    const v = version
    const e = epoca
    const cambios = pendientes
    pendientes = []
    ;['items', 'taxes'].forEach((t) => (doc.value[t] || []).forEach(clave))
    const enviado = copia(doc.value)
    calculando.value = true
    enCurso = call(`${API}.calcular`, {
      doctype,
      doc: enviado,
      cambio: cambios.length ? paraServidor(cambios, enviado) : null,
    })
    try {
      const res = await enCurso
      if (e !== epoca) return // llegó después de guardar o recargar
      if (v !== version) {
        // Han tecleado mientras tanto: se repite con los cambios acumulados.
        pendientes = [...cambios, ...pendientes]
        enCurso = null
        programar(0)
        return
      }
      conservarClaves(enviado, res.doc)
      doc.value = res.doc
      avisos.value = res.avisos || []
      reintento = false
    } catch (err) {
      if (e !== epoca) return
      // Los cambios no aplicados se conservan: el siguiente recálculo los vuelve a mandar.
      pendientes = [...cambios, ...pendientes]
      if (err instanceof TypeError && !reintento) {
        // Corte de red (p. ej. reinicio del servidor): se reintenta una vez.
        reintento = true
        enCurso = null
        programar(800)
        return
      }
      reintento = false
      avisos.value = [mensajeError(err)]
    } finally {
      enCurso = null
      calculando.value = false
    }
  }

  /** Deja el documento recalculado con todos los cambios antes de guardar. */
  async function esperarCalculo() {
    for (let i = 0; i < 6; i++) {
      clearTimeout(temporizador)
      if (enCurso) {
        await enCurso.catch(() => {})
        await Promise.resolve()
        continue
      }
      if (!pendientes.length) break
      await recalcular()
    }
    clearTimeout(temporizador)
  }

  async function accion(nombre, fn) {
    guardando.value = nombre
    try {
      await esperarCalculo()
      const res = await fn()
      if (res?.doc) aplicarRespuesta(res, { mismoDoc: !res.doc.__islocal })
      return res
    } finally {
      guardando.value = ''
    }
  }

  const guardar = () =>
    accion('guardar', () => call(`${API}.guardar`, { doctype, doc: copia(doc.value) }))
  const validar = () =>
    accion('validar', async () => {
      if (sucio.value) await call(`${API}.guardar`, { doctype, doc: copia(doc.value) })
      return call(`${API}.validar`, { doctype, name: doc.value.name })
    })
  const cancelar = () =>
    accion('cancelar', () => call(`${API}.cancelar`, { doctype, name: doc.value.name }))
  const eliminar = () =>
    accion('eliminar', () => call(`${API}.eliminar`, { doctype, name: doc.value.name }))
  const modificar = () =>
    accion('modificar', () => call(`${API}.modificar`, { doctype, name: doc.value.name }))
  const recargar = () => doc.value?.name && !esNuevo.value && cargar(doc.value.name)

  function anadirFila(tabla, valores = {}) {
    const filas = doc.value[tabla] || (doc.value[tabla] = [])
    const row = {
      doctype: config.value?.tablas?.[tabla]?.doctype,
      idx: filas.length + 1,
      __islocal: 1,
      ...valores,
    }
    filas.push(row)
    sucio.value = true
    version++
    return clave(row)
  }

  function quitarFila(tabla, key) {
    const filas = doc.value[tabla] || []
    const i = filas.findIndex((r) => clave(r) === key)
    if (i < 0) return
    filas.splice(i, 1)
    filas.forEach((r, n) => (r.idx = n + 1))
    sucio.value = true
    version++
    if (!calculable.value) return
    pendientes.push({ campo: '__filas' })
    programar(0)
  }

  function moverFila(tabla, key, delta) {
    const filas = doc.value[tabla] || []
    const i = filas.findIndex((r) => clave(r) === key)
    const j = i + delta
    if (i < 0 || j < 0 || j >= filas.length) return
    ;[filas[i], filas[j]] = [filas[j], filas[i]]
    filas.forEach((r, n) => (r.idx = n + 1))
    sucio.value = true
    version++
  }

  return reactive({
    tipo,
    doctype,
    doc,
    permisos,
    contexto,
    avisos,
    config,
    cargando,
    calculando,
    guardando,
    sucio,
    error,
    esNuevo,
    editable,
    monedaEmpresa,
    dimensiones,
    cargar,
    nueva,
    duplicar,
    rectificar,
    desdeHito,
    recargar,
    cambiar,
    clave,
    recalcular,
    guardar,
    validar,
    cancelar,
    eliminar,
    modificar,
    anadirFila,
    quitarFila,
    moverFila,
  })
}

/** Mensaje de error de una llamada, sin HTML (las validaciones de Frappe traen <strong>…). */
export function mensajeError(e) {
  if (!e) return ''
  return String(errorMessage(e, __('No se ha podido completar la operación'))).replace(/<[^>]+>/g, '')
}

/** Etiqueta del meta de un campo, con alternativa. */
export function etiqueta(config, campo, tabla = null, alternativa = '') {
  const campos = tabla ? config?.tablas?.[tabla]?.campos : config?.campos
  return campos?.[campo]?.label || alternativa || campo
}

export function df(config, campo, tabla = null) {
  const campos = tabla ? config?.tablas?.[tabla]?.campos : config?.campos
  return campos?.[campo] || { fieldname: campo, fieldtype: 'Data', label: campo }
}

export const ESTADOS = {
  Draft: ['Borrador', 'gray'],
  Unpaid: ['Pendiente de cobro', 'orange'],
  Overdue: ['Vencida', 'red'],
  'Partly Paid': ['Cobrada en parte', 'blue'],
  Paid: ['Cobrada', 'green'],
  Return: ['Rectificativa', 'gray'],
  'Credit Note Issued': ['Rectificada', 'gray'],
  Cancelled: ['Cancelada', 'red'],
  'Unpaid and Discounted': ['Descontada', 'blue'],
  'Overdue and Discounted': ['Vencida y descontada', 'red'],
  'Partly Paid and Discounted': ['Cobrada en parte y descontada', 'blue'],
  'Dudoso Cobro': ['Dudoso cobro', 'red'],
  Pérdida: ['Pérdida', 'red'],
}

// En compras se paga, no se cobra.
const ESTADOS_COMPRA = {
  Unpaid: ['Pendiente de pago', 'orange'],
  'Partly Paid': ['Pagada en parte', 'blue'],
  Paid: ['Pagada', 'green'],
  'Debit Note Issued': ['Rectificada', 'gray'],
  Internal: ['Interna', 'gray'],
}

export function estadoFactura(doc) {
  if (!doc) return ['', 'gray']
  if (doc.__islocal) return ['Nueva', 'blue']
  const compra = doc.doctype === 'Purchase Invoice'
  return (compra && ESTADOS_COMPRA[doc.status]) || ESTADOS[doc.status] || [doc.status, 'gray']
}

/**
 * Campos personalizados (Custom Field) de la cabecera o de una tabla que la vista
 * no pinta en otra sección. Así cada instalación ve los suyos sin tocar la SPA.
 */
export function camposPersonalizados(config, tabla = null, excluir = []) {
  const campos = tabla ? config?.tablas?.[tabla]?.campos : config?.campos
  const fuera = new Set(excluir)
  return Object.values(campos || {})
    .filter(
      (c) =>
        c.is_custom &&
        !c.hidden &&
        !fuera.has(c.fieldname) &&
        !['Table', 'Table MultiSelect', 'Attach', 'Attach Image', 'Signature', 'Geolocation'].includes(
          c.fieldtype,
        ),
    )
    .sort((a, b) => a.idx - b.idx)
    .map((c) => c.fieldname)
}

/** Número de cuenta (o primer tramo) para mostrar en poco espacio. */
export function cuentaCorta(cuenta) {
  if (!cuenta) return ''
  const partes = String(cuenta).split(' - ')
  return partes.length > 2 ? `${partes[0]} ${partes[1]}` : partes[0]
}

const BLOQUE_FINAL = /<\/(p|div|li|h[1-6])>\s*$/i

/**
 * Texto plano para editar un campo HTML (Text Editor) en un textarea.
 * Es la inversa exacta de `textoAHtml`, así que el cursor no salta mientras se escribe.
 */
export function htmlATexto(html) {
  const s = html == null ? '' : String(html)
  if (!/[<&]/.test(s)) return s
  let t = s
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|h[1-6])>/gi, '\n')
    .replace(/<[^>]*>/g, '')
  const el = document.createElement('textarea')
  el.innerHTML = t
  t = el.value
  return BLOQUE_FINAL.test(s) ? t.replace(/\n+$/, '') : t
}

/** HTML mínimo para guardar lo escrito en un textarea; el texto sin saltos ni símbolos se guarda tal cual. */
export function textoAHtml(texto) {
  const s = texto == null ? '' : String(texto)
  if (!/[\n<>&]/.test(s)) return s
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}
