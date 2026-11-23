/**
 * Utilidades del SII para las listas de facturas y la pantalla SII de /contabilidad.
 */
import { call } from 'frappe-ui'

export const SII_API = 'spain_compliance.api.sii'

export const SII_THEME = {
  Pendiente: 'orange',
  Aceptado: 'green',
  'Aceptado con errores': 'amber',
  Rechazado: 'red',
  'Error de comunicación': 'red',
  'Error de datos': 'red',
  'Baja pendiente': 'orange',
  'Dado de baja': 'gray',
  'No aplica': 'gray',
}

export const SII_ABIERTOS = ['Pendiente', 'Rechazado', 'Error de comunicación', 'Error de datos']

export function siiTheme(estado) {
  return SII_THEME[estado] || 'gray'
}

/** Etiqueta de la columna SII de una factura (con o sin registro). */
export function siiLabel(row) {
  if (row.sii_estado) return row.sii_estado
  if (row.docstatus === 2) return 'Cancelada'
  return row.sii_aplica ? 'Sin enviar' : 'Fuera del SII'
}

export function siiRowTheme(row) {
  if (row.sii_estado) return siiTheme(row.sii_estado)
  return row.sii_aplica ? 'orange' : 'gray'
}

export function fmtDate(value) {
  if (!value) return '—'
  const d = new Date(String(value).slice(0, 10) + 'T00:00:00')
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function fmtDateTime(value) {
  if (!value) return '—'
  const d = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function fmtMoney(value, currency = 'EUR') {
  if (value == null || value === '') return '—'
  return new Intl.NumberFormat('es-ES', { style: 'currency', currency: currency || 'EUR' }).format(value)
}

export function deskUrl(doctype, name) {
  const slug = doctype.toLowerCase().replace(/ /g, '-')
  return `/app/${slug}/${encodeURIComponent(name)}`
}

export function errorMessage(err, fallback = 'No se pudo completar la operación') {
  if (!err) return fallback
  if (Array.isArray(err.messages) && err.messages.length) return err.messages.join(' ')
  return err.message || fallback
}

/** Texto corto con el resultado de enviar / consultar. */
export function resumenResultado(res) {
  if (!res) return ''
  if (res.encolado) return `${res.n} registros en cola. El estado se actualizará en unos minutos.`
  const partes = Object.entries(res.estados || {}).map(([estado, n]) => `${n} ${estado.toLowerCase()}`)
  if (res.creados) partes.unshift(`${res.creados} registros nuevos`)
  if (res.omitidos) partes.push(`${res.omitidos} sin cambios`)
  return partes.join(' · ') || 'Nada que enviar'
}

export function enviarSii({ registros, documentos, modificar } = {}) {
  return call(`${SII_API}.enviar`, {
    registros: registros || null,
    documentos: documentos || null,
    modificar: modificar ? 1 : 0,
  })
}

export function consultarSii({ registros, documentos, entorno } = {}) {
  return call(`${SII_API}.consultar`, {
    registros: registros || null,
    documentos: documentos || null,
    entorno: entorno || null,
  })
}
