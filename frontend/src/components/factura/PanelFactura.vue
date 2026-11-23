<template>
  <div class="flex flex-col">
    <div class="border-b border-outline-gray-1 px-4 py-3">
      <div class="text-xs text-ink-gray-5">{{ __('Configuración de la factura') }}</div>
      <p class="mt-0.5 text-p-sm text-ink-gray-6">
        {{ __('Selecciona una línea o un impuesto para ver su detalle contable.') }}
      </p>
    </div>

    <Seccion :titulo="__('Contabilidad')" :icono="LucideBookOpen" :resumen="cuentaCorta(d[t.cuenta])">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'company', label: __('Compañía'), visible: companias > 1 || !d.company },
          { campo: t.cuenta, label: __(t.cuentaLabel), filters: { company: d.company, is_group: 0, account_type: t.cuentaTipo } },
          { campo: 'cost_center', label: __('Centro de coste'), filters: { company: d.company, is_group: 0 } },
          { campo: 'project', label: __('Proyecto'), filters: { company: d.company } },
          ...f.dimensiones,
          { campo: 'is_opening', label: __('Asiento de apertura') },
        ]"
      />
      <div v-if="f.editable && (d.items || []).length > 1" class="flex flex-wrap gap-2">
        <Button size="sm" :label="__('Aplicar centro de coste a todas las líneas')" @click="propagar('cost_center')" />
        <Button v-if="d.project" size="sm" :label="__('Aplicar proyecto a todas las líneas')" @click="propagar('project')" />
      </div>
    </Seccion>

    <Seccion :titulo="__(t.terceroLabel)" :icono="LucideUser" :resumen="d.tax_id || ''">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: t.tercero, label: __(t.terceroLabel), filters: t.terceroFiltro, etiquetaValor: d[t.terceroNombre] },
          { campo: t.terceroNombre, label: __('Nombre en la factura') },
          { campo: 'tax_id', label: __('NIF') },
          { campo: t.direccion, label: t.compra ? __('Dirección del proveedor') : __('Dirección de facturación'), query: 'frappe.contacts.doctype.address.address.address_query', filters: filtroTercero },
          { campo: 'address_display', label: __('Dirección'), soloLectura: true, visible: Boolean(d.address_display) },
          { campo: 'contact_person', label: __('Contacto'), query: 'frappe.contacts.doctype.contact.contact.contact_query', filters: filtroTercero },
          { campo: 'contact_email', label: __('Correo del contacto'), soloLectura: true, visible: Boolean(d.contact_email) },
          { campo: t.envio, query: 'frappe.contacts.doctype.address.address.address_query', filters: t.compra ? { link_doctype: 'Company', link_name: d.company } : filtroTercero, label: t.compra ? __('Dirección de entrega (nuestra)') : __('Dirección de envío') },
          { campo: t.envioTexto, label: __('Dirección'), soloLectura: true, visible: Boolean(d[t.envioTexto]) && d[t.envioTexto] !== d.address_display },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Fechas y numeración')" :icono="LucideCalendar" :resumen="d.naming_series || ''">
      <GrupoCampos
        :f="f"
        :columnas="2"
        :campos="[
          { campo: 'naming_series', label: __('Serie'), ancho: true },
          { campo: 'bill_no', label: __('Nº factura del proveedor') },
          { campo: 'bill_date', label: __('Fecha de la factura') },
          { campo: 'posting_date', label: t.compra ? __('Fecha de registro') : __('Fecha') },
          { campo: 'due_date', label: __('Vencimiento') },
          { campo: 'set_posting_time', label: __('Fecha distinta de hoy'), ancho: true, visible: f.editable && Boolean(d.set_posting_time) },
          { campo: 'posting_time', label: __('Hora'), visible: Boolean(d.set_posting_time) },
          { campo: 'po_no', label: __('Ref. pedido del cliente') },
          { campo: 'po_date', label: __('Fecha del pedido') },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Impuestos')" :icono="LucidePercent" :resumen="d.taxes_and_charges || ''">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'taxes_and_charges', label: __('Plantilla de impuestos'), filters: { company: d.company, disabled: 0 } },
          { campo: 'tax_category', label: __('Categoría de impuestos') },
        ]"
      />
      <p class="text-p-xs text-ink-gray-5">
        {{ __('Al cambiar la plantilla se sustituyen las filas de impuestos.') }}
      </p>
    </Seccion>

    <Seccion :titulo="__('Descuento sobre el total')" :icono="LucideBadgePercent" :resumen="resumenDescuento" :abierta="Boolean(flt(d.discount_amount))">
      <GrupoCampos
        :f="f"
        :columnas="2"
        :campos="[
          { campo: 'apply_discount_on', label: __('Aplicar sobre'), ancho: true },
          { campo: 'additional_discount_percentage', label: __('Descuento %'), sufijo: '%' },
          { campo: 'discount_amount', label: __('Importe del descuento') },
          { campo: 'is_cash_or_non_trade_discount', label: __('Descuento financiero (contra cuenta)'), ancho: true },
          { campo: 'additional_discount_account', label: __('Cuenta del descuento'), filters: { company: d.company, is_group: 0 }, visible: Boolean(d.is_cash_or_non_trade_discount), ancho: true },
        ]"
      />
    </Seccion>

    <Seccion
      v-if="t.compra && f.config?.campos?.apply_tds"
      :titulo="__('Retención (IRPF)')"
      :icono="LucideScissors"
      :resumen="d.apply_tds ? d.tax_withholding_group || __('Sí') : ''"
      :abierta="Boolean(d.apply_tds)"
    >
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'apply_tds', label: __('Aplicar retención') },
          { campo: 'tax_withholding_group', label: __('Grupo de retención'), visible: Boolean(d.apply_tds) },
          { campo: 'ignore_tax_withholding_threshold', label: __('Ignorar el umbral de retención'), visible: Boolean(d.apply_tds) },
        ]"
      />
      <p class="text-p-xs text-ink-gray-5">
        {{ __('Con una plantilla de impuestos con IRPF (p. ej. profesionales o alquiler) la retención va como fila de impuesto que resta.') }}
      </p>
    </Seccion>

    <Seccion :titulo="__(t.cobro)" :icono="LucideHandCoins" :resumen="d.payment_terms_template || ''">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'payment_terms_template', label: __('Condiciones de pago') },
          { campo: 'is_paid', label: __('Pagada al contado'), visible: t.compra },
          { campo: 'mode_of_payment', label: __('Forma de pago'), visible: !t.compra || Boolean(d.is_paid) },
          { campo: 'cash_bank_account', label: __('Cuenta de caja o banco'), filters: { company: d.company, is_group: 0 }, visible: t.compra && Boolean(d.is_paid) },
          { campo: 'paid_amount', label: __('Importe pagado'), visible: t.compra && Boolean(d.is_paid) },
          { campo: 'on_hold', label: __('Retener el pago'), visible: t.compra },
          { campo: 'release_date', label: __('Liberar el'), visible: t.compra && Boolean(d.on_hold) },
          { campo: 'hold_comment', label: __('Motivo de la retención'), visible: t.compra && Boolean(d.on_hold) },
        ]"
      />
      <div v-if="(d.payment_schedule || []).length" class="rounded border border-outline-gray-1">
        <div class="grid grid-cols-[1fr_auto_auto] gap-3 border-b border-outline-gray-1 bg-surface-gray-1 px-2.5 py-1.5 text-xs text-ink-gray-5">
          <span>{{ __('Vencimiento') }}</span>
          <span class="text-right">%</span>
          <span class="w-24 text-right">{{ __('Importe') }}</span>
        </div>
        <div
          v-for="p in d.payment_schedule"
          :key="p.name || p.idx"
          class="grid grid-cols-[1fr_auto_auto] gap-3 border-b border-outline-gray-1 px-2.5 py-1.5 text-sm last:border-b-0"
        >
          <span class="truncate text-ink-gray-8">
            {{ formatDate(p.due_date) }}
            <span v-if="p.payment_term" class="text-ink-gray-5"> · {{ p.payment_term }}</span>
          </span>
          <span class="tabular-nums text-ink-gray-6">{{ formatNumber(p.invoice_portion, 0) }}</span>
          <span class="w-24 text-right tabular-nums text-ink-gray-9">{{ formatNumber(p.payment_amount, 2) }}</span>
        </div>
      </div>
    </Seccion>

    <Seccion :titulo="__('Precios y stock')" :icono="LucideTags" :resumen="d[t.tarifa] || ''" :abierta="false">
      <GrupoCampos
        :f="f"
        :columnas="2"
        :campos="[
          { campo: t.tarifa, label: __('Tarifa'), filters: t.tarifaFiltro, ancho: true },
          { campo: 'currency', label: __('Moneda') },
          { campo: 'conversion_rate', label: __('Tipo de cambio'), visible: d.currency !== f.monedaEmpresa },
          { campo: 'ignore_pricing_rule', label: __('Ignorar reglas de precio'), ancho: true },
          { campo: 'update_stock', label: __('Mueve stock (sin albarán)'), ancho: true },
          { campo: 'set_warehouse', label: t.compra ? __('Almacén de entrada') : __('Almacén de salida'), filters: { company: d.company, is_group: 0 }, visible: Boolean(d.update_stock), ancho: true },
          { campo: 'rejected_warehouse', label: __('Almacén de rechazos'), filters: { company: d.company, is_group: 0 }, visible: t.compra && Boolean(d.update_stock), ancho: true },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Rectificativa')" :icono="LucideUndo2" :resumen="d.is_return ? d.return_against || __('Sí') : ''" :abierta="Boolean(d.is_return)">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'is_return', label: __('Es rectificativa (abono)') },
          { campo: 'return_against', label: __('Factura rectificada'), filters: { [t.tercero]: d[t.tercero], docstatus: 1, is_return: 0, company: d.company }, visible: Boolean(d.is_return) },
          { campo: 'update_outstanding_for_self', visible: Boolean(d.is_return && d.return_against) },
          { campo: 'is_debit_note', label: __('Nota de cargo'), visible: !d.is_return },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Impresión')" :icono="LucidePrinter" :abierta="false">
      <GrupoCampos
        :f="f"
        :campos="[
          { campo: 'letter_head', label: __('Membrete') },
          { campo: 'select_print_heading', label: __('Título impreso') },
          { campo: 'language', label: __('Idioma de impresión') },
        ]"
      />
    </Seccion>

    <Seccion
      v-if="personalizados.length"
      :titulo="__('Otros datos')"
      :icono="LucideSlidersHorizontal"
    >
      <GrupoCampos :f="f" :campos="personalizados" />
    </Seccion>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import Seccion from '@/components/factura/Seccion.vue'
import GrupoCampos from '@/components/factura/GrupoCampos.vue'
import { camposPersonalizados, cuentaCorta } from '@/composables/factura'
import { formatDate, formatNumber } from '@/composables/informe'
import LucideUser from '~icons/lucide/user'
import LucideScissors from '~icons/lucide/scissors'
import LucideCalendar from '~icons/lucide/calendar'
import LucideBookOpen from '~icons/lucide/book-open'
import LucidePercent from '~icons/lucide/percent'
import LucideBadgePercent from '~icons/lucide/badge-percent'
import LucideHandCoins from '~icons/lucide/hand-coins'
import LucideTags from '~icons/lucide/tags'
import LucideUndo2 from '~icons/lucide/undo-2'
import LucidePrinter from '~icons/lucide/printer'
import LucideSlidersHorizontal from '~icons/lucide/sliders-horizontal'

const props = defineProps({
  f: { type: Object, required: true },
})

const d = computed(() => props.f.doc || {})
const flt = (v) => Number(v) || 0

const t = computed(() => props.f.tipo)

const filtroTercero = computed(() =>
  d.value[t.value.tercero]
    ? { link_doctype: t.value.terceroDoctype, link_name: d.value[t.value.tercero] }
    : null,
)

const companias = computed(() => (props.f.config?.companias || []).length)

const resumenDescuento = computed(() => {
  if (!flt(d.value.discount_amount)) return ''
  return `${formatNumber(d.value.discount_amount, 2)} ${d.value.currency || ''}`
})

// Lo que ya tiene sección propia en la vista no se repite en «Otros datos».
const CURADOS = [
  'customer', 'customer_name', 'supplier', 'supplier_name', 'bill_no', 'bill_date', 'credit_to', 'tax_id', 'naming_series', 'posting_date', 'due_date',
  'po_no', 'po_date', 'debit_to', 'cost_center', 'project', 'taxes_and_charges',
  'payment_terms_template', 'remarks', 'company', 'hito_pedido',
]

const personalizados = computed(() =>
  camposPersonalizados(props.f.config, null, CURADOS),
)

function propagar(campo) {
  const valor = d.value[campo]
  for (const row of d.value.items || []) {
    props.f.cambiar(campo, valor, { tabla: 'items', fila: props.f.clave(row) })
  }
}
</script>
