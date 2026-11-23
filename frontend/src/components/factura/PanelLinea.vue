<template>
  <div v-if="fila" class="flex flex-col">
    <div class="border-b border-outline-gray-1 px-4 py-3">
      <div class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <div class="text-xs text-ink-gray-5">{{ __('Línea') }} {{ fila.idx }}</div>
          <div class="truncate text-base font-medium text-ink-gray-9">
            {{ fila.item_name || fila.item_code || __('Sin artículo') }}
          </div>
        </div>
        <div class="text-right">
          <div class="text-xs text-ink-gray-5">{{ __('Importe') }}</div>
          <div class="text-base font-semibold tabular-nums text-ink-gray-9">
            {{ formatMoney(fila.amount, f.doc.currency) }}
          </div>
        </div>
      </div>
      <div v-if="f.editable" class="mt-2 flex gap-1">
        <Button size="sm" variant="ghost" :tooltip="__('Subir')" @click="f.moverFila('items', clave, -1)">
          <template #icon><LucideArrowUp class="size-4" /></template>
        </Button>
        <Button size="sm" variant="ghost" :tooltip="__('Bajar')" @click="f.moverFila('items', clave, 1)">
          <template #icon><LucideArrowDown class="size-4" /></template>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          :label="__('Duplicar línea')"
          @click="duplicarLinea"
        >
          <template #prefix><LucideCopy class="size-4" /></template>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          theme="red"
          class="ml-auto"
          :label="__('Quitar')"
          @click="quitar"
        >
          <template #prefix><LucideTrash2 class="size-4" /></template>
        </Button>
      </div>
    </div>

    <Seccion :titulo="__('Contabilidad')" :icono="LucideBookOpen" :resumen="cuentaCorta(fila[f.tipo.cuentaLinea])">
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :campos="[
          { campo: f.tipo.cuentaLinea, label: __(f.tipo.cuentaLineaLabel), filters: { company: f.doc.company, is_group: 0 } },
          { campo: 'cost_center', label: __('Centro de coste'), filters: { company: f.doc.company, is_group: 0 } },
          { campo: 'project', label: __('Proyecto'), filters: { company: f.doc.company } },
          ...f.dimensiones,
          { campo: 'expense_account', label: __('Cuenta de coste (stock)'), filters: { company: f.doc.company, is_group: 0 }, visible: !f.tipo.compra && (Boolean(fila.expense_account) || Boolean(f.doc.update_stock)) },
        ]"
      />
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :columnas="2"
        :campos="[
          { campo: 'enable_deferred_revenue', label: __('Ingreso diferido'), ancho: true, visible: !f.tipo.compra },
          { campo: 'deferred_revenue_account', label: __('Cuenta de ingreso diferido'), filters: { company: f.doc.company, is_group: 0 }, visible: Boolean(fila.enable_deferred_revenue), ancho: true },
          { campo: 'enable_deferred_expense', label: __('Gasto diferido'), ancho: true, visible: f.tipo.compra },
          { campo: 'deferred_expense_account', label: __('Cuenta de gasto diferido'), filters: { company: f.doc.company, is_group: 0 }, visible: Boolean(fila.enable_deferred_expense), ancho: true },
          { campo: 'service_start_date', label: __('Inicio del servicio'), visible: Boolean(fila.enable_deferred_revenue || fila.enable_deferred_expense) },
          { campo: 'service_end_date', label: __('Fin del servicio'), visible: Boolean(fila.enable_deferred_revenue || fila.enable_deferred_expense) },
          { campo: 'is_fixed_asset', label: __('Inmovilizado'), soloLectura: true, visible: Boolean(fila.is_fixed_asset), ancho: true },
          { campo: 'asset_location', label: __('Ubicación del activo'), visible: Boolean(fila.is_fixed_asset) },
          { campo: 'asset_category', label: __('Categoría del activo'), soloLectura: true, visible: Boolean(fila.is_fixed_asset) },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Artículo')" :icono="LucidePackage">
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :campos="[
          { campo: 'item_code', label: __('Artículo'), filters: f.tipo.articuloFiltro, query: 'erpnext.controllers.queries.item_query', etiquetaValor: fila.item_name },
          { campo: 'item_name', label: __('Nombre en la factura') },
          { campo: 'description', label: __('Descripción'), filas: 3 },
        ]"
      />
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :columnas="2"
        :campos="[
          { campo: 'item_group', label: __('Grupo'), soloLectura: true },
          { campo: 'brand', soloLectura: true, visible: Boolean(fila.brand) },
        ]"
      />
    </Seccion>

    <Seccion :titulo="__('Cantidad y unidad')" :icono="LucideRuler" :resumen="`${num(fila.qty)} ${fila.uom || ''}`">
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :columnas="2"
        :campos="[
          { campo: 'qty', label: __('Cantidad') },
          { campo: 'uom', label: __('Unidad') },
          { campo: 'conversion_factor', label: __('Factor de conversión'), visible: fila.uom !== fila.stock_uom },
          { campo: 'stock_qty', label: __('Cantidad en stock'), soloLectura: true, visible: fila.uom !== fila.stock_uom },
          { campo: 'stock_uom', label: __('Unidad de stock'), soloLectura: true },
          { campo: 'received_qty', label: __('Cantidad recibida'), visible: f.tipo.compra && Boolean(f.doc.update_stock) },
          { campo: 'rejected_qty', label: __('Cantidad rechazada'), visible: f.tipo.compra && Boolean(f.doc.update_stock) },
        ]"
      />
    </Seccion>

    <Seccion
      :titulo="__('Precio y descuentos')"
      :icono="LucideTag"
      :resumen="resumenPrecio"
    >
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :columnas="2"
        :campos="[
          { campo: 'price_list_rate', label: __('Precio de tarifa') },
          { campo: 'margin_type', label: __('Tipo de margen'), visible: Boolean(fila.margin_type || fila.margin_rate_or_amount) },
          { campo: 'margin_rate_or_amount', label: __('Margen'), visible: Boolean(fila.margin_type) },
          { campo: 'discount_percentage', label: __('Descuento %'), sufijo: '%' },
          { campo: 'discount_amount', label: __('Descuento por unidad') },
          { campo: 'rate', label: __('Precio neto') },
          { campo: 'amount', label: __('Importe'), soloLectura: true },
          { campo: 'net_amount', label: __('Importe neto'), soloLectura: true, visible: flt(fila.net_amount) !== flt(fila.amount) },
          { campo: 'is_free_item', soloLectura: true, visible: Boolean(fila.is_free_item) },
          { campo: 'pricing_rules', label: __('Reglas de precio'), soloLectura: true, visible: tieneReglas, ancho: true },
        ]"
      />
      <p v-if="!fila.price_list_rate && f.editable" class="text-p-xs text-ink-gray-5">
        {{ __('Sin precio de tarifa: el descuento se aplica sobre el precio tecleado.') }}
      </p>
    </Seccion>

    <Seccion :titulo="__('Impuestos de la línea')" :icono="LucidePercent" :resumen="fila.item_tax_template || __('Los de la factura')">
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :campos="[{ campo: 'item_tax_template', label: __('Plantilla de impuestos del artículo'), filters: { company: f.doc.company, disabled: 0 } }]"
      />
      <div v-if="tasas.length" class="rounded border border-outline-gray-1">
        <div
          v-for="t in tasas"
          :key="t.cuenta"
          class="flex items-center justify-between gap-2 border-b border-outline-gray-1 px-2.5 py-1.5 text-sm last:border-b-0"
        >
          <span class="truncate text-ink-gray-7">{{ t.cuenta }}</span>
          <span class="tabular-nums text-ink-gray-9">{{ num(t.tasa) }} %</span>
        </div>
      </div>
      <p v-else class="text-p-xs text-ink-gray-5">
        {{ __('Sin plantilla de impuestos de artículo: se aplican los impuestos de la factura.') }}
      </p>
    </Seccion>

    <Seccion
      :titulo="__('Almacén y stock')"
      :icono="LucideWarehouse"
      :resumen="fila.warehouse || ''"
      :abierta="Boolean(f.doc.update_stock)"
    >
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :campos="[
          { campo: 'warehouse', label: __('Almacén'), filters: { company: f.doc.company, is_group: 0 } },
          { campo: 'rejected_warehouse', label: __('Almacén de rechazos'), filters: { company: f.doc.company, is_group: 0 }, visible: f.tipo.compra && Boolean(f.doc.update_stock) },
          { campo: 'target_warehouse', filters: { company: f.doc.company, is_group: 0 }, visible: Boolean(fila.target_warehouse) },
          { campo: 'batch_no', label: __('Lote'), filters: { item: fila.item_code }, visible: Boolean(f.doc.update_stock || fila.batch_no) },
          { campo: 'serial_no', label: __('Números de serie'), visible: Boolean(f.doc.update_stock || fila.serial_no) },
          { campo: 'delivered_by_supplier', visible: Boolean(fila.delivered_by_supplier) },
          { campo: 'incoming_rate', soloLectura: true, visible: Boolean(flt(fila.incoming_rate)) },
        ]"
      />
      <p v-if="!f.doc.update_stock" class="text-p-xs text-ink-gray-5">
        {{ __('La factura no mueve stock. Actívalo en «Precios y stock» de la factura si sale mercancía con ella.') }}
      </p>
    </Seccion>

    <Seccion
      v-if="tieneReferencias"
      :titulo="__('Origen')"
      :icono="LucideLink"
      :abierta="false"
    >
      <GrupoCampos
        :f="f"
        tabla="items"
        :fila="fila"
        :campos="[
          { campo: 'sales_order', label: __('Pedido de venta'), soloLectura: true, visible: Boolean(fila.sales_order) },
          { campo: 'purchase_order', label: __('Pedido de compra'), soloLectura: true, visible: Boolean(fila.purchase_order) },
          { campo: 'purchase_receipt', label: __('Albarán de compra'), soloLectura: true, visible: Boolean(fila.purchase_receipt) },
          { campo: 'material_request', label: __('Solicitud de material'), soloLectura: true, visible: Boolean(fila.material_request) },
          { campo: 'delivery_note', label: __('Albarán'), soloLectura: true, visible: Boolean(fila.delivery_note) },
          { campo: 'quotation_item', soloLectura: true, visible: Boolean(fila.quotation_item) },
          { campo: 'asset', soloLectura: true, visible: Boolean(fila.asset) },
        ]"
      />
    </Seccion>

    <Seccion
      v-if="personalizados.length"
      :titulo="__('Otros datos de la línea')"
      :icono="LucideSlidersHorizontal"
    >
      <GrupoCampos :f="f" tabla="items" :fila="fila" :campos="personalizados" />
    </Seccion>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import Seccion from '@/components/factura/Seccion.vue'
import GrupoCampos from '@/components/factura/GrupoCampos.vue'
import { camposPersonalizados, cuentaCorta } from '@/composables/factura'
import { formatMoney, formatNumber } from '@/composables/informe'
import LucidePackage from '~icons/lucide/package'
import LucideRuler from '~icons/lucide/ruler'
import LucideTag from '~icons/lucide/tag'
import LucidePercent from '~icons/lucide/percent'
import LucideBookOpen from '~icons/lucide/book-open'
import LucideWarehouse from '~icons/lucide/warehouse'
import LucideLink from '~icons/lucide/link'
import LucideSlidersHorizontal from '~icons/lucide/sliders-horizontal'
import LucideArrowUp from '~icons/lucide/arrow-up'
import LucideArrowDown from '~icons/lucide/arrow-down'
import LucideCopy from '~icons/lucide/copy'
import LucideTrash2 from '~icons/lucide/trash-2'

const props = defineProps({
  f: { type: Object, required: true },
  clave: { type: String, required: true },
})
const emit = defineEmits(['seleccionar', 'cerrar'])

const fila = computed(() => props.f.doc?.items?.find((r) => props.f.clave(r) === props.clave))

const flt = (v) => Number(v) || 0
const num = (v) => formatNumber(v, Number.isInteger(flt(v)) ? 0 : 2)

const CURADOS = [
  'item_code', 'item_name', 'description', 'qty', 'uom', 'rate', 'income_account', 'expense_account',
  'cost_center', 'project', 'warehouse',
]

// La copia es una línea independiente: no factura otra vez el mismo pedido, albarán o lote.
const VINCULOS_ORIGEN = [
  'sales_order', 'so_detail', 'delivery_note', 'dn_detail', 'quotation_item',
  'purchase_order', 'po_detail', 'purchase_receipt', 'pr_detail',
  'material_request', 'material_request_item', 'sales_invoice_item', 'pos_invoice_item',
  'serial_and_batch_bundle', 'serial_no', 'batch_no', 'asset',
]

const personalizados = computed(() => camposPersonalizados(props.f.config, 'items', CURADOS))

const tasas = computed(() => {
  let mapa = fila.value?.item_tax_rate
  if (!mapa) return []
  try {
    if (typeof mapa === 'string') mapa = JSON.parse(mapa)
  } catch {
    return []
  }
  return Object.entries(mapa || {}).map(([cuenta, tasa]) => ({ cuenta, tasa }))
})

const tieneReglas = computed(() => {
  const r = fila.value?.pricing_rules
  return Boolean(r && r !== '[]')
})

const tieneReferencias = computed(() => {
  const r = fila.value || {}
  return Boolean(
    r.sales_order || r.delivery_note || r.quotation_item || r.asset ||
      r.purchase_order || r.purchase_receipt || r.material_request,
  )
})

const resumenPrecio = computed(() => {
  const r = fila.value || {}
  const dto = flt(r.discount_percentage) ? ` · −${num(r.discount_percentage)} %` : ''
  return `${formatNumber(r.rate, 2)}${dto}`
})

function duplicarLinea() {
  const r = fila.value
  const copia = { ...r }
  for (const k of ['name', '__key', 'idx', 'creation', 'modified', 'owner', 'modified_by', ...VINCULOS_ORIGEN]) {
    delete copia[k]
  }
  const nueva = props.f.anadirFila('items', copia)
  props.f.recalcular()
  emit('seleccionar', nueva)
}

function quitar() {
  props.f.quitarFila('items', props.clave)
  emit('cerrar')
}
</script>
