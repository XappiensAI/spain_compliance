<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __(title), route: $route.fullPath }]" />
    </template>
    <template #right-header>
      <Button
        v-if="deskPath || detailRoute"
        :label="buttonLabel"
        theme="gray"
        variant="solid"
        @click="openDetail()"
      >
        <template #prefix>
          <LucidePlus class="size-4" />
        </template>
      </Button>
    </template>
  </LayoutHeader>

  <ListViewBuilder ref="builder" :options="listOptions">
    <template v-if="sii && sii_puede_enviar" #banner-actions="{ selections, unselectAll }">
      <div class="flex gap-2">
        <Button
          label="Enviar al SII"
          variant="solid"
          :loading="siiBusy === 'enviar'"
          @click="siiEnviar([...selections], unselectAll)"
        >
          <template #prefix><LucideSend class="size-4" /></template>
        </Button>
        <Button
          label="Consultar en la AEAT"
          :loading="siiBusy === 'consultar'"
          @click="siiConsultar([...selections], unselectAll)"
        >
          <template #prefix><LucideSearch class="size-4" /></template>
        </Button>
      </div>
    </template>
    <template #cell="{ column, item, row }">
      <Tooltip v-if="column.key === '_sii'" :text="siiTooltip(row)">
        <button
          type="button"
          class="flex items-center gap-1.5"
          @click.stop="siiAbrir(row)"
        >
          <component :is="siiIcono(row)" class="size-4 shrink-0" :class="siiColor(row)" />
          <span class="truncate text-base" :class="siiColor(row)">{{ siiTexto(row) }}</span>
        </button>
      </Tooltip>
      <Badge
        v-else-if="column.key === 'docstatus'"
        :label="docstatusLabel(item)"
        :theme="docstatusTheme(item)"
        variant="subtle"
      />
      <Badge
        v-else-if="column.key === 'status' && typeof item === 'string'"
        :label="item"
        :theme="statusTheme(item)"
        variant="subtle"
      />
      <span
        v-else-if="isMoneyColumn(column.key)"
        class="truncate text-base tabular-nums"
      >
        {{ formatAmount(item) }}
      </span>
      <span v-else-if="isDateColumn(column.key)" class="truncate text-base">
        {{ formatDate(item) }}
      </span>
      <span v-else class="truncate text-base">{{ item }}</span>
    </template>
  </ListViewBuilder>

  <SiiDetalleDialog
    v-if="sii"
    v-model="siiDialog"
    :registro="siiDialogRegistro"
    :documento="siiDialogDoc"
    :can-send="sii_puede_enviar"
    @changed="siiCargar(true)"
  />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Breadcrumbs, Button, Tooltip, call, dayjs, toast } from 'frappe-ui'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ListViewBuilder from '@/components/ListViewBuilder.vue'
import SiiDetalleDialog from '@/components/sii/SiiDetalleDialog.vue'
import {
  SII_API,
  enviarSii,
  consultarSii,
  errorMessage,
  resumenResultado,
} from '@/composables/sii'
import LucidePlus from '~icons/lucide/plus'
import LucideBox from '~icons/lucide/box'
import LucideSend from '~icons/lucide/send'
import LucideSearch from '~icons/lucide/search'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideCircleAlert from '~icons/lucide/circle-alert'
import LucideClock from '~icons/lucide/clock'
import LucideCircleDashed from '~icons/lucide/circle-dashed'
import LucideCircleMinus from '~icons/lucide/circle-minus'

const props = defineProps({
  title: { type: String, required: true },
  doctype: { type: String, required: true },
  deskPath: { type: String, default: '' },
  newLabel: { type: String, default: '' },
  fields: { type: Array, default: () => ['name'] },
  columns: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  orderBy: { type: String, default: 'modified desc' },
  emptyTitle: { type: String, default: '' },
  emptyDescription: { type: String, default: '' },
  // Columna `_sii` con el estado en el SII y acciones de envío / consulta.
  sii: { type: Boolean, default: false },
  // Vista de detalle propia en /contabilidad; sin ella se abre el Desk.
  detailRoute: { type: String, default: '' },
})

const router = useRouter()

const moneyKeys = new Set([
  'grand_total',
  'rounded_total',
  'paid_amount',
  'received_amount',
  'total_debit',
  'outstanding_amount',
  'base_grand_total',
])

const dateKeys = new Set([
  'posting_date',
  'transaction_date',
  'due_date',
  'valid_till',
])

const listOptions = computed(() => ({
  doctype: props.doctype,
  rowKey: 'name',
  fields: props.fields,
  filters: props.filters,
  orderBy: props.orderBy,
  pageLength: 20,
  columns: props.columns,
  onRowClick: (row) => openDetail(row.name),
  selectable: props.sii ? true : undefined,
  emptyState: {
    title: props.emptyTitle || __('Sin registros'),
    description:
      props.emptyDescription || __('No hay documentos para mostrar en ERPNext'),
  },
  emptyStateIcon: LucideBox,
}))

const buttonLabel = computed(() => props.newLabel || __('Nuevo'))

function isMoneyColumn(key) {
  return moneyKeys.has(key)
}

function isDateColumn(key) {
  return dateKeys.has(key)
}

function docstatusLabel(value) {
  return { 0: __('Borrador'), 1: __('Validado'), 2: __('Cancelado') }[value] ?? value
}

function docstatusTheme(value) {
  return { 0: 'gray', 1: 'green', 2: 'red' }[value] ?? 'gray'
}

function statusTheme(value) {
  const v = String(value).toLowerCase()
  if (['paid', 'submitted', 'completed', 'return'].includes(v)) return 'green'
  if (['overdue', 'cancelled', 'canceled', 'unpaid'].includes(v)) return 'red'
  if (['draft', 'cancelled'].includes(v)) return 'gray'
  return 'blue'
}

function formatDate(value) {
  return value ? dayjs(value).format('DD/MM/YYYY') : ''
}

const currencyFormat = new Intl.NumberFormat('es-ES', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(value) {
  return typeof value === 'number' ? currencyFormat.format(value) : value
}

function openDetail(name) {
  if (props.detailRoute) {
    router.push({ name: props.detailRoute, params: { name: name || 'new' } })
    return
  }
  openInDesk(name)
}

function openInDesk(name) {
  if (!props.deskPath) return
  const base = `/app/${props.deskPath}`
  window.open(name ? `${base}/${name}` : `${base}/new`, '_blank')
}
// --- SII --------------------------------------------------------------------
const builder = ref(null)
const siiEstados = ref({})
const sii_puede_enviar = ref(false)
const siiBusy = ref('')
const siiDialog = ref(false)
const siiDialogRegistro = ref(null)
const siiDialogDoc = ref(null)

const visibles = computed(() => (builder.value?.list?.data || []).map((r) => r.name))

async function siiCargar(force = false) {
  if (!props.sii || !visibles.value.length) return
  const faltan = force ? visibles.value : visibles.value.filter((n) => !(n in siiEstados.value))
  if (!faltan.length) return
  try {
    const res = await call(`${SII_API}.estado_documentos`, { doctype: props.doctype, names: faltan })
    siiEstados.value = { ...siiEstados.value, ...(res.estados || res) }
    if (res.puede_enviar !== undefined) sii_puede_enviar.value = !!res.puede_enviar
  } catch (e) {
    // Sin permiso de contabilidad: la columna queda vacía.
  }
}
watch(visibles, () => siiCargar(), { immediate: true })

function siiInfo(row) {
  return siiEstados.value[row.name] || null
}
function siiTexto(row) {
  const i = siiInfo(row)
  if (!i) return row.docstatus === 0 ? '—' : '…'
  if (i.estado) return i.estado
  if (row.docstatus === 0) return '—'
  if (row.docstatus === 2) return 'Cancelada'
  return i.aplica ? 'Sin enviar' : 'Fuera del SII'
}
function siiColor(row) {
  const t = siiTexto(row)
  if (t === 'Aceptado' || t === 'Dado de baja') return 'text-ink-green-7'
  if (t === 'Aceptado con errores' || t === 'Sin enviar' || t === 'Pendiente' || t === 'Baja pendiente') return 'text-ink-amber-7'
  if (['Rechazado', 'Error de datos', 'Error de comunicación'].includes(t)) return 'text-ink-red-7'
  return 'text-ink-gray-5'
}
function siiIcono(row) {
  const t = siiTexto(row)
  if (t === 'Aceptado' || t === 'Dado de baja') return LucideCircleCheck
  if (['Rechazado', 'Error de datos', 'Error de comunicación', 'Aceptado con errores'].includes(t)) return LucideCircleAlert
  if (t === 'Sin enviar' || t === 'Pendiente' || t === 'Baja pendiente') return LucideClock
  if (t === 'Fuera del SII' || t === 'No aplica') return LucideCircleMinus
  return LucideCircleDashed
}
function siiTooltip(row) {
  const i = siiInfo(row)
  if (!i) return ''
  if (i.descripcion_error) return i.descripcion_error
  if (i.csv) return `CSV ${i.csv}${i.entorno ? ' · ' + i.entorno : ''}`
  if (i.aplica) return 'Pendiente de comunicar a la AEAT'
  return 'Anterior a la fecha de inicio del SII o compañía sin SII activo. Se puede consultar en la AEAT.'
}
function siiAbrir(row) {
  if (row.docstatus === 0) return
  siiDialogRegistro.value = siiInfo(row)?.name || null
  siiDialogDoc.value = { doctype: props.doctype, name: row.name }
  siiDialog.value = true
}
async function siiEnviar(names, unselectAll) {
  siiBusy.value = 'enviar'
  try {
    const res = await enviarSii({ documentos: names.map((name) => ({ doctype: props.doctype, name })) })
    ;(res.avisos || []).slice(0, 5).forEach((a) => toast.warning(a))
    if (res.n) toast.success(resumenResultado(res))
    unselectAll?.()
    await siiCargar(true)
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    siiBusy.value = ''
  }
}
async function siiConsultar(names, unselectAll) {
  if (names.length > 50) {
    toast.warning('Consulte como mucho 50 facturas a la vez, o use «Cruzar periodo» en la pantalla SII.')
    return
  }
  siiBusy.value = 'consultar'
  try {
    const res = await consultarSii({ documentos: names.map((name) => ({ doctype: props.doctype, name })) })
    const r = res.resultados || []
    const err = r.find((x) => !x.ok)
    if (err) toast.error(`AEAT — ${err.error}`)
    toast.success(`${r.filter((x) => x.ok && x.encontrado).length} en la AEAT · ${r.filter((x) => x.ok && !x.encontrado).length} no constan`)
    unselectAll?.()
    await siiCargar(true)
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    siiBusy.value = ''
  }
}

</script>
