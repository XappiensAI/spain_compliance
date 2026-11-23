<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __('Hitos de facturación'), route: $route.fullPath }]" />
    </template>
    <template #right-header>
      <Button :label="__('Actualizar')" :loading="datos.loading" @click="cargar()">
        <template #prefix><LucideRefreshCw class="size-4" /></template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex w-full min-w-0 flex-col gap-4 p-4 sm:p-5">
    <Alert
      v-if="datos.error"
      theme="red"
      :title="__('No se han podido cargar los hitos')"
      :description="errorMessage(datos.error)"
    />

    <!-- Resumen: cada tarjeta filtra la lista -->
    <div class="grid min-w-0 grid-cols-2 gap-3 xl:grid-cols-4">
      <button
        v-for="k in kpis"
        :key="k.filtro"
        type="button"
        class="flex min-w-0 flex-col gap-0.5 rounded-lg border px-4 py-3 text-left transition-colors hover:bg-surface-gray-1"
        :class="filtro === k.filtro ? 'border-outline-gray-4 bg-surface-gray-1' : 'border-outline-gray-1 bg-surface-elevation-1'"
        @click="filtro = k.filtro"
      >
        <span class="flex min-w-0 items-center gap-1.5 text-sm text-ink-gray-6">
          <component :is="k.icono" class="size-4 shrink-0" :class="k.color" />
          <span class="truncate">{{ k.label }}</span>
        </span>
        <span class="truncate text-2xl font-semibold tabular-nums text-ink-gray-9">{{ k.valor }}</span>
        <span class="text-xs text-ink-gray-5">{{ k.pista }}</span>
      </button>
    </div>

    <div class="flex min-w-0 flex-wrap items-center gap-3">
      <TabButtons v-model="filtro" :options="pestanas" />
      <TextInput
        v-model="busqueda"
        class="w-full sm:w-72"
        :placeholder="__('Proyecto, cliente, pedido o hito…')"
      >
        <template #prefix><LucideSearch class="size-4 text-ink-gray-5" /></template>
      </TextInput>
      <span class="text-sm text-ink-gray-5">
        {{ visibles.length }} {{ visibles.length === 1 ? __('hito') : __('hitos') }} ·
        {{ __('base') }} {{ formatMoney(suma(visibles), monedaEmpresa) }}
      </span>
    </div>

    <!-- Lista en rejilla: cada celda recorta su texto y nada invade la columna de al lado -->
    <div class="min-w-0 overflow-x-auto rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
      <div class="min-w-[58rem]">
        <div
          class="grid items-end gap-x-2.5 border-b border-outline-gray-1 px-4 py-2 text-xs text-ink-gray-5"
          :class="COLUMNAS"
        >
          <span>{{ __('Fecha prevista') }}</span>
          <span>{{ __('Proyecto y cliente') }}</span>
          <span>{{ __('Pedido') }}</span>
          <span>{{ __('Hito') }}</span>
          <span class="text-right">{{ __('Base imponible') }}</span>
          <span>{{ __('Estado') }}</span>
          <span></span>
        </div>

        <div v-if="datos.loading && !hitos.length" class="py-10">
          <LoadingIndicator class="mx-auto size-5" />
        </div>

        <div
          v-for="h in visibles"
          :key="h.fila"
          class="grid items-center gap-x-2.5 border-b border-outline-gray-1 px-4 py-2.5 text-base last:border-b-0 hover:bg-surface-gray-1"
          :class="COLUMNAS"
        >
          <div class="min-w-0">
            <div class="whitespace-nowrap tabular-nums" :class="vencido(h) ? 'font-medium text-ink-red-7' : 'text-ink-gray-8'">
              {{ formatDate(h.fecha) || '—' }}
            </div>
            <div v-if="vencido(h)" class="text-xs text-ink-red-7">{{ __('vencido') }}</div>
          </div>

          <div class="min-w-0">
            <div class="truncate text-ink-gray-9" :title="`${h.proyecto || ''} ${h.proyecto_nombre || ''}`">
              <span class="font-medium">{{ h.proyecto || __('Sin proyecto') }}</span>
              <span v-if="h.proyecto_nombre" class="text-ink-gray-5"> · {{ h.proyecto_nombre }}</span>
            </div>
            <div class="truncate text-sm text-ink-gray-6" :title="h.cliente_nombre">{{ h.cliente_nombre || h.cliente }}</div>
          </div>

          <div class="min-w-0">
            <a
              :href="deskUrl('Sales Order', h.pedido)"
              target="_blank"
              class="block truncate text-ink-gray-8 hover:underline"
              :title="h.pedido"
            >{{ pedidoCorto(h.pedido) }}</a>
            <div v-if="h.po_no" class="truncate text-sm text-ink-gray-5" :title="h.po_no">{{ h.po_no }}</div>
          </div>

          <div class="min-w-0">
            <div class="flex min-w-0 items-center gap-1.5">
              <span class="truncate text-ink-gray-9" :title="h.etiqueta">{{ h.etiqueta }}</span>
              <Tooltip v-if="h.nota" :text="h.nota">
                <LucideMessageSquareText class="size-3.5 shrink-0 text-ink-gray-5" />
              </Tooltip>
            </div>
            <div class="truncate text-sm text-ink-gray-5">
              {{ porcentaje(h.porcentaje) }} · {{ __('{0} de {1}', h.numero, h.total_hitos) }}
              <template v-if="h.avance"> · {{ __('avance') }} {{ formatNumber(h.avance, 0) }} %</template>
            </div>
          </div>

          <div class="whitespace-nowrap text-right tabular-nums text-ink-gray-9">{{ formatMoney(h.base, h.moneda) }}</div>

          <div class="min-w-0">
            <Badge :label="__(etiquetaEstado(h.estado))" :theme="temaEstado(h.estado)" variant="subtle" />
          </div>

          <div class="flex min-w-0 justify-end">
            <div v-if="h.estado === 'Facturado'" class="min-w-0 text-right text-sm">
              <router-link
                v-for="fa in h.facturas.filter((x) => x.docstatus === 1)"
                :key="fa.name"
                :to="{ name: 'SalesInvoice', params: { name: fa.name } }"
                class="block truncate text-ink-gray-8 hover:underline"
              >{{ fa.name }}</router-link>
              <span
                v-if="datos.data?.ver_facturas && !h.facturas.some((x) => x.docstatus === 1)"
                class="text-ink-gray-5"
              >{{ __('Marcado en el proyecto') }}</span>
            </div>
            <Button
              v-else-if="h.estado === 'Borrador' && h.borrador"
              size="sm"
              :label="__('Abrir borrador')"
              @click="router.push({ name: 'SalesInvoice', params: { name: h.borrador } })"
            />
            <Button
              v-else-if="h.estado !== 'Borrador' && datos.data?.puede_facturar"
              size="sm"
              :variant="h.estado === 'Listo para facturar' ? 'solid' : 'subtle'"
              :label="__('Crear factura')"
              @click="crear(h)"
            >
              <template #prefix><LucideFilePlus class="size-4" /></template>
            </Button>
          </div>
        </div>

        <div v-if="!datos.loading && !visibles.length" class="px-4 py-10 text-center text-p-sm text-ink-gray-5">
          {{ hitos.length ? __('Ningún hito con este filtro.') : __('No hay órdenes de venta con calendario de pagos.') }}
        </div>
      </div>
    </div>

    <p class="text-xs text-ink-gray-5">
      {{
        __(
          'Cada hito es una fila del calendario de pagos de una orden de venta validada. La factura se crea con las líneas del pedido al porcentaje del hito, ligada al pedido y al proyecto, y se abre sin guardar para revisarla.',
        )
      }}
    </p>
  </div>
</template>

<script setup>
/**
 * Hitos de facturación de todas las órdenes de venta, con el botón para crear la factura.
 * Datos: `spain_compliance.api.hitos.listar`.
 */
import { computed, markRaw, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  LoadingIndicator,
  TabButtons,
  TextInput,
  Tooltip,
  createResource,
  dayjs,
} from 'frappe-ui'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { deskUrl, errorMessage } from '@/composables/sii'
import { formatDate, formatMoney, formatNumber } from '@/composables/informe'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSearch from '~icons/lucide/search'
import LucideFilePlus from '~icons/lucide/file-plus'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideFilePen from '~icons/lucide/file-pen'
import LucideMessageSquareText from '~icons/lucide/message-square-text'

// Fecha · proyecto y cliente · pedido · hito · base · estado · acción.
const COLUMNAS =
  'grid-cols-[5.75rem_minmax(9rem,1.4fr)_minmax(7.5rem,0.8fr)_minmax(10rem,1.8fr)_7.5rem_7rem_8.5rem]'

const router = useRouter()

const datos = createResource({ url: 'spain_compliance.api.hitos.listar' })

const hitos = computed(() => datos.data?.hitos || [])
const hoy = computed(() => datos.data?.hoy || dayjs().format('YYYY-MM-DD'))

const filtro = ref('pendientes')
const busqueda = ref('')

// Los pedidos ya facturados del todo solo se leen al abrir Facturados o Todos.
const conFacturados = computed(() => ['facturados', 'todos'].includes(filtro.value))
function cargar() {
  datos.submit({ incluir_facturados: conFacturados.value ? 1 : 0 })
}
watch(conFacturados, (si) => si && cargar())
cargar()

// Los totales se suman en la moneda de la empresa (cada hito trae su base convertida).
const monedaEmpresa = computed(() => hitos.value[0]?.moneda_empresa || 'EUR')

const ABIERTOS = new Set(['Pendiente', 'En curso', 'Listo para facturar'])

function vencido(h) {
  return ABIERTOS.has(h.estado) && h.fecha && h.fecha <= hoy.value
}

const FILTROS = {
  pendientes: (h) => ABIERTOS.has(h.estado),
  listos: (h) => h.estado === 'Listo para facturar',
  vencidos: vencido,
  borrador: (h) => h.estado === 'Borrador',
  proximos: (h) => {
    const limite = dayjs(hoy.value).add(30, 'day').format('YYYY-MM-DD')
    return ABIERTOS.has(h.estado) && h.fecha && h.fecha > hoy.value && h.fecha <= limite
  },
  facturados: (h) => h.estado === 'Facturado',
  todos: () => true,
}

const pestanas = computed(() => {
  const n = (clave) => hitos.value.filter(FILTROS[clave]).length
  return [
    { label: `${__('Por facturar')} · ${n('pendientes')}`, value: 'pendientes' },
    { label: `${__('Listos')} · ${n('listos')}`, value: 'listos' },
    { label: `${__('Vencidos')} · ${n('vencidos')}`, value: 'vencidos' },
    { label: `${__('Próximos 30 días')} · ${n('proximos')}`, value: 'proximos' },
    { label: `${__('En borrador')} · ${n('borrador')}`, value: 'borrador' },
    { label: __('Facturados'), value: 'facturados' },
    { label: __('Todos'), value: 'todos' },
  ]
})

function normalizar(texto) {
  return String(texto || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
}

const visibles = computed(() => {
  const q = normalizar(busqueda.value.trim())
  return hitos.value.filter((h) => {
    if (!FILTROS[filtro.value](h)) return false
    if (!q) return true
    return normalizar(
      [h.proyecto, h.proyecto_nombre, h.cliente, h.cliente_nombre, h.pedido, h.po_no, h.etiqueta, h.nota].join(' '),
    ).includes(q)
  })
})

function suma(lista) {
  return lista.reduce((t, h) => t + (Number(h.base_empresa) || 0), 0)
}

const kpis = computed(() => {
  const pista = (lista) => (lista.length === 1 ? __('1 hito') : __('{0} hitos', lista.length))
  const tarjeta = (filtroTarjeta, label, icono, color) => {
    const lista = hitos.value.filter(FILTROS[filtroTarjeta])
    return { filtro: filtroTarjeta, label, icono: markRaw(icono), color, valor: formatMoney(suma(lista), monedaEmpresa.value), pista: pista(lista) }
  }
  return [
    tarjeta('listos', __('Listo para facturar'), LucideCircleCheck, 'text-ink-green-7'),
    tarjeta('vencidos', __('Vencido sin facturar'), LucideTriangleAlert, 'text-ink-red-7'),
    tarjeta('proximos', __('Próximos 30 días'), LucideCalendarClock, 'text-ink-gray-5'),
    tarjeta('borrador', __('En borrador'), LucideFilePen, 'text-ink-blue-7'),
  ]
})

// «SAL-ORD-2026-00038-1» → «2026-00038-1»: el prefijo es igual en todos y tapaba el número.
function pedidoCorto(nombre) {
  return String(nombre || '').replace(/^SAL-ORD-/, '')
}

function porcentaje(v) {
  const n = Number(v) || 0
  return `${formatNumber(n, Number.isInteger(n) ? 0 : 2)} %`
}

const ESTADOS = {
  Facturado: { label: 'Facturado', theme: 'gray' },
  Borrador: { label: 'En borrador', theme: 'blue' },
  'Listo para facturar': { label: 'Listo para facturar', theme: 'green' },
  'En curso': { label: 'En curso', theme: 'orange' },
  Pendiente: { label: 'Pendiente', theme: 'gray' },
}

function etiquetaEstado(e) {
  return ESTADOS[e]?.label || e
}

function temaEstado(e) {
  return ESTADOS[e]?.theme || 'gray'
}

function crear(h) {
  router.push({ name: 'SalesInvoice', params: { name: 'new' }, query: { pedido: h.pedido, hito: h.fila } })
}
</script>
