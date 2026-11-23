<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  createResource,
  call,
  Badge,
  Breadcrumbs,
  Button,
  DatePicker,
  Dialog,
  FormControl,
  LoadingIndicator,
  TabButtons,
  Tooltip,
  toast,
} from 'frappe-ui'
import LayoutHeader from '@/components/LayoutHeader.vue'
import SiiDetalleDialog from '@/components/sii/SiiDetalleDialog.vue'
import {
  SII_API,
  siiTheme,
  fmtDate,
  fmtDateTime,
  fmtMoney,
  errorMessage,
  resumenResultado,
  enviarSii,
  consultarSii,
} from '@/composables/sii'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideLandmark from '~icons/lucide/landmark'
import LucideAlertTriangle from '~icons/lucide/alert-triangle'
import LucideFilterX from '~icons/lucide/filter-x'
import LucideSend from '~icons/lucide/send'
import LucideSearch from '~icons/lucide/search'
import LucideSettings from '~icons/lucide/settings'
import LucideLock from '~icons/lucide/lock'
import LucideFlaskConical from '~icons/lucide/flask-conical'
import LucideShieldCheck from '~icons/lucide/shield-check'
import LucideGitCompare from '~icons/lucide/git-compare'

const router = useRouter()
const route = useRoute()
const q = route.query

const company = ref(typeof q.company === 'string' ? q.company : '')
const libro = ref(q.libro === 'Recibidas' ? 'Recibidas' : 'Expedidas')
const estado = ref(typeof q.estado === 'string' ? q.estado : '')
const search = ref(typeof q.q === 'string' ? q.q : '')
const fromDate = ref(typeof q.from === 'string' ? q.from : '')
const toDate = ref(typeof q.to === 'string' ? q.to : '')
const soloVencidos = ref(q.vencidos === '1')
const PAGE = 200
const limit = ref(PAGE)

const resumen = createResource({
  url: `${SII_API}.resumen`,
  makeParams() {
    return { company: company.value || null }
  },
  onSuccess(data) {
    if (!company.value && data.company) company.value = data.company
  },
})
const sinAcceso = computed(() => /PermissionError/.test(resumen.error?.exc_type || resumen.error?.message || ''))
const r = computed(() => resumen.data || {})
const cfg = computed(() => r.value.config)
const canSend = computed(() => !!r.value.puede_enviar)
const companyOptions = computed(() => (r.value.companias || []).map((c) => ({ label: c, value: c })))

const libroButtons = [
  { label: 'Emitidas', value: 'Expedidas' },
  { label: 'Recibidas', value: 'Recibidas' },
]
const estadoOptions = computed(() => [
  { label: 'Todos los estados', value: '' },
  { label: 'Abiertos (pendientes y errores)', value: 'abiertos' },
  ...(r.value.estados || []).map((e) => ({ label: e, value: e })),
])

const registros = createResource({
  url: `${SII_API}.registros`,
  makeParams() {
    return {
      company: company.value,
      libro: libro.value,
      estado: estado.value || null,
      search: search.value || null,
      desde: fromDate.value || null,
      hasta: toDate.value || null,
      vencidos: soloVencidos.value ? 1 : 0,
      limit: limit.value,
    }
  },
})

function syncQuery() {
  const query = {}
  if (company.value) query.company = company.value
  if (libro.value !== 'Expedidas') query.libro = libro.value
  if (estado.value) query.estado = estado.value
  if (search.value) query.q = search.value
  if (fromDate.value) query.from = fromDate.value
  if (toDate.value) query.to = toDate.value
  if (soloVencidos.value) query.vencidos = '1'
  router.replace({ query })
}

function reload(resetPage = true) {
  if (!company.value) return
  if (resetPage) limit.value = PAGE
  selected.value = new Set()
  syncQuery()
  registros.reload()
}

let searchTimer = null
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => reload(), 300)
})
watch(company, () => {
  resumen.reload()
  reload()
})
watch([libro, estado, fromDate, toDate, soloVencidos], () => reload())
onMounted(() => {
  resumen.fetch()
  if (company.value) registros.fetch()
})

function refrescar() {
  resumen.reload()
  reload(false)
}

const hasActiveFilters = computed(
  () => !!estado.value || !!search.value || !!fromDate.value || !!toDate.value || soloVencidos.value
)
function resetFilters() {
  estado.value = ''
  search.value = ''
  fromDate.value = ''
  toDate.value = ''
  soloVencidos.value = false
}

const rows = computed(() => registros.data?.registros || [])
const total = computed(() => registros.data?.total || 0)
const listError = computed(() => (registros.error ? errorMessage(registros.error, 'No se pudo cargar el listado') : ''))

const contLibro = computed(() => (r.value.contadores || {})[libro.value] || {})
function cont(...estados) {
  return estados.reduce((s, e) => s + (contLibro.value[e] || 0), 0)
}
const cards = computed(() => [
  { estado: 'Pendiente', label: 'Pendientes', value: cont('Pendiente'), warn: true },
  { estado: 'Aceptado', label: 'Aceptadas', value: cont('Aceptado') },
  { estado: 'Aceptado con errores', label: 'Aceptadas con errores', value: cont('Aceptado con errores'), warn: true },
  { estado: 'abiertos', label: 'Rechazadas / errores', value: cont('Rechazado', 'Error de datos', 'Error de comunicación'), danger: true },
  { estado: 'Baja pendiente', label: 'Bajas pendientes', value: cont('Baja pendiente'), warn: true },
  { vencidos: true, label: 'Fuera de plazo', value: r.value.contadores?.vencidos || 0, danger: true },
])
function clickCard(c) {
  if (c.vencidos) {
    estado.value = ''
    soloVencidos.value = !soloVencidos.value
  } else {
    soloVencidos.value = false
    estado.value = estado.value === c.estado ? '' : c.estado
  }
}

// --- Selección y acciones ---------------------------------------------------
const selected = ref(new Set())
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((x) => selected.value.has(x.name)))
function toggle(name) {
  const s = new Set(selected.value)
  s.has(name) ? s.delete(name) : s.add(name)
  selected.value = s
}
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(rows.value.map((x) => x.name))
}

const busy = ref('')
async function accion(nombre, fn) {
  busy.value = nombre
  try {
    await fn()
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
    refrescar()
  }
}

function enviarSeleccion() {
  return accion('enviar', async () => {
    const res = await enviarSii({ registros: [...selected.value] })
    toast.success(resumenResultado(res))
  })
}
function consultarSeleccion() {
  if (selected.value.size > 50) {
    toast.warning('Consulte como mucho 50 registros a la vez, o use «Cruzar periodo».')
    return
  }
  return accion('consultar', async () => {
    const res = await consultarSii({ registros: [...selected.value] })
    ;(res.errores || []).slice(0, 3).forEach((e) => toast.error(e))
    toast.success(resumenResultado(res))
  })
}
function enviarPendientes() {
  return accion('pendientes', async () => {
    const res = await call(`${SII_API}.enviar_pendientes`, { company: company.value })
    toast.success(resumenResultado(res))
  })
}
function generar() {
  return accion('generar', async () => {
    const res = await call(`${SII_API}.generar`, { company: company.value })
    toast.success(res.creados ? `${res.creados} registros nuevos` : 'No hay facturas nuevas que registrar')
  })
}

function abrirConfiguracion() {
  const url = r.value.configurada
    ? `/app/sii-configuracion/${encodeURIComponent(company.value)}`
    : `/app/sii-configuracion/new?company=${encodeURIComponent(company.value)}`
  window.open(url, '_blank')
}

// --- Detalle ----------------------------------------------------------------
const dialogOpen = ref(false)
const dialogRegistro = ref(null)
const dialogDoc = ref(null)
function verDetalle(row) {
  dialogRegistro.value = row.name
  dialogDoc.value = { doctype: row.documento_tipo, name: row.documento }
  dialogOpen.value = true
}

// --- Cruzar periodo con la AEAT --------------------------------------------
const hoy = new Date()
const cruceOpen = ref(false)
const cruce = ref({
  ejercicio: String(hoy.getFullYear()),
  periodo: String(hoy.getMonth() + 1),
  entorno: '',
})
const cruceRes = ref(null)
const mesOptions = Array.from({ length: 12 }, (_, i) => ({
  label: new Date(2000, i, 1).toLocaleDateString('es-ES', { month: 'long' }),
  value: String(i + 1),
}))
const entornoOptions = computed(() => [
  { label: `El de la configuración (${cfg.value?.entorno || '—'})`, value: '' },
  { label: 'Producción (solo informa, no cambia registros)', value: 'Producción' },
  { label: 'Pruebas (solo informa, no cambia registros)', value: 'Pruebas' },
].filter((o) => !o.value || o.value !== cfg.value?.entorno))

function abrirCruce() {
  cruceRes.value = null
  cruceOpen.value = true
}
async function cruzar() {
  busy.value = 'cruce'
  cruceRes.value = null
  try {
    cruceRes.value = await call(`${SII_API}.sincronizar`, {
      company: company.value,
      libro: libro.value,
      ejercicio: cruce.value.ejercicio,
      periodo: cruce.value.periodo,
      entorno: cruce.value.entorno || null,
    })
    if (!cruceRes.value.ok) toast.error(`AEAT — ${cruceRes.value.error}`)
    refrescar()
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: 'Cumplimiento' }, { label: 'SII', route: $route.fullPath }]" />
    </template>
    <template #right-header>
      <Button label="Actualizar" variant="subtle" :loading="registros.loading || resumen.loading" @click="refrescar">
        <template #prefix><LucideRefreshCw class="size-4" /></template>
      </Button>
    </template>
  </LayoutHeader>
  <div class="relative flex min-h-0 flex-1 flex-col overflow-auto bg-surface-gray-1">
  <div class="mx-auto flex w-full max-w-[1480px] flex-col gap-5 px-4 py-5 sm:px-6">

    <div v-if="sinAcceso" class="max-w-2xl rounded-lg border border-outline-gray-2 bg-surface-white p-8 text-center">
      <LucideLock class="mx-auto mb-3 h-6 w-6 text-ink-gray-5" />
      <p class="text-base font-medium text-ink-gray-9">Sin acceso</p>
      <p class="mt-1 text-sm text-ink-gray-6">El SII está reservado a los roles de Contabilidad.</p>
    </div>

    <div v-else class="space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex items-start gap-3">
          <div class="rounded-md bg-surface-gray-2 p-2">
            <LucideLandmark class="h-5 w-5 text-ink-gray-8" />
          </div>
          <div>
            <h1 class="text-6xl font-semibold leading-tight tracking-tight text-ink-gray-9">SII</h1>
            <p class="mt-0.5 text-sm text-ink-gray-6">
              Suministro Inmediato de Información — facturas comunicadas a la AEAT, pendientes y errores.
            </p>
          </div>
        </div>
        <div v-if="companyOptions.length > 1" class="w-60"><FormControl v-model="company" type="select" :options="companyOptions" /></div>
      </div>

      <!-- Configuración -->
      <div v-if="resumen.data" class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1 p-4">
        <div v-if="!r.configurada" class="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span class="text-ink-gray-7">Esta compañía no tiene configuración SII.</span>
          <Button v-if="canSend" variant="solid" @click="abrirConfiguracion">Configurar SII</Button>
        </div>
        <div v-else class="flex flex-wrap items-start justify-between gap-4">
          <div class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-5">
            <div>
              <div class="text-xs text-ink-gray-5">Estado</div>
              <Badge :theme="cfg.activo ? 'green' : 'gray'" variant="subtle" :label="cfg.activo ? 'Activo' : 'Desactivado'" />
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Entorno</div>
              <Badge :theme="cfg.entorno === 'Producción' ? 'blue' : 'orange'" variant="subtle" :label="cfg.entorno" />
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Desde</div>
              <div class="text-ink-gray-9">{{ fmtDate(cfg.fecha_inicio) }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Envío</div>
              <div class="text-ink-gray-9">{{ cfg.envio_automatico ? 'Automático (15 min)' : 'Manual' }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Certificado</div>
              <div v-if="r.certificado" class="flex items-center gap-1 text-ink-gray-9">
                <LucideShieldCheck class="h-4 w-4" :class="r.certificado.estado === 'Vigente' ? 'text-ink-green-7' : 'text-ink-amber-7'" />
                <Tooltip :text="r.certificado.titulo">
                  <span>vence {{ fmtDate(r.certificado.valido_hasta) }}</span>
                </Tooltip>
              </div>
              <div v-else class="font-medium text-ink-red-7">Sin certificado SII</div>
            </div>
          </div>
          <div v-if="canSend" class="flex flex-wrap gap-2">
            <Button variant="ghost" @click="abrirConfiguracion">
              <template #prefix><LucideSettings class="h-4 w-4" /></template>
              Configuración
            </Button>
            <Button variant="subtle" :disabled="!cfg.activo" :loading="busy === 'generar'" @click="generar">
              Buscar facturas nuevas
            </Button>
            <Button variant="subtle" :loading="busy === 'cruce'" @click="abrirCruce">
              <template #prefix><LucideGitCompare class="h-4 w-4" /></template>
              Cruzar periodo
            </Button>
            <Button variant="solid" :disabled="!cfg.activo" :loading="busy === 'pendientes'" @click="enviarPendientes">
              <template #prefix><LucideSend class="h-4 w-4" /></template>
              Enviar pendientes
            </Button>
          </div>
        </div>
        <div
          v-if="r.configurada && cfg.entorno !== 'Producción'"
          class="mt-3 flex items-start gap-2 rounded-md bg-surface-amber-1 px-3 py-2 text-sm text-ink-amber-7"
        >
          <LucideFlaskConical class="mt-0.5 h-4 w-4 shrink-0" />
          <span>Entorno de pruebas de la AEAT — lo enviado no tiene efectos fiscales. Al pasar a Producción lo aceptado en pruebas vuelve a Pendiente.</span>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <TabButtons v-model="libro" :options="libroButtons" />
      </div>

      <div class="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <button
          v-for="c in cards"
          :key="c.label"
          type="button"
          class="rounded-md border bg-surface-white px-3 py-2 text-left transition hover:border-outline-gray-3"
          :class="(c.vencidos ? soloVencidos : estado === c.estado) ? 'border-outline-gray-4' : 'border-outline-gray-2'"
          @click="clickCard(c)"
        >
          <div class="text-xs text-ink-gray-5">{{ c.label }}</div>
          <div
            class="text-base font-semibold tabular-nums"
            :class="c.value && c.danger ? 'text-ink-red-7' : c.value && c.warn ? 'text-ink-amber-7' : 'text-ink-gray-9'"
          >
            {{ c.value }}
          </div>
        </button>
      </div>

      <div class="flex flex-wrap items-end gap-2">
        <div class="w-64"><FormControl v-model="search" type="text" placeholder="Buscar factura, tercero o NIF" /></div>
        <div class="w-64"><FormControl v-model="estado" type="select" :options="estadoOptions" /></div>
        <div class="w-40"><DatePicker v-model="fromDate" placeholder="Desde" /></div>
        <div class="w-40"><DatePicker v-model="toDate" placeholder="Hasta" /></div>
        <Tooltip v-if="hasActiveFilters" text="Limpiar filtros">
          <Button variant="ghost" @click="resetFilters">
            <template #icon><LucideFilterX class="h-4 w-4" /></template>
          </Button>
        </Tooltip>
      </div>

      <div
        v-if="selected.size && canSend"
        class="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-md border border-outline-gray-3 bg-surface-white px-3 py-2 shadow-sm"
      >
        <span class="text-sm text-ink-gray-8">{{ selected.size }} seleccionados</span>
        <Button variant="solid" size="sm" :loading="busy === 'enviar'" @click="enviarSeleccion">
          <template #prefix><LucideSend class="h-4 w-4" /></template>
          Enviar
        </Button>
        <Button variant="subtle" size="sm" :loading="busy === 'consultar'" @click="consultarSeleccion">
          <template #prefix><LucideSearch class="h-4 w-4" /></template>
          Consultar en la AEAT
        </Button>
        <Button variant="ghost" size="sm" @click="selected = new Set()">Quitar selección</Button>
      </div>

      <div
        v-if="listError"
        class="flex items-start gap-2 rounded-md border border-outline-red-2 bg-surface-red-1 px-3 py-2 text-sm text-ink-red-7"
      >
        <LucideAlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>{{ listError }}</span>
      </div>

      <div v-if="registros.loading && !rows.length" class="flex justify-center py-16">
        <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
      </div>
      <div v-else class="overflow-x-auto rounded-lg border border-outline-gray-2 bg-surface-white">
        <table class="w-full min-w-[1000px] text-sm">
          <thead class="border-b border-outline-gray-2 bg-surface-gray-1 text-left text-xs text-ink-gray-5">
            <tr>
              <th v-if="canSend" class="w-8 px-3 py-2">
                <input type="checkbox" class="rounded" :checked="allSelected" @change="toggleAll" />
              </th>
              <th class="px-3 py-2 font-medium">Factura</th>
              <th class="px-3 py-2 font-medium">Tercero</th>
              <th class="px-3 py-2 font-medium">Fecha</th>
              <th class="px-3 py-2 font-medium">Periodo</th>
              <th class="px-3 py-2 text-right font-medium">Importe</th>
              <th class="px-3 py-2 font-medium">Estado</th>
              <th class="px-3 py-2 font-medium">Plazo</th>
              <th class="px-3 py-2 font-medium">CSV / detalle</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.name"
              class="cursor-pointer border-b border-outline-gray-1 align-top last:border-0 hover:bg-surface-gray-1"
              :class="selected.has(row.name) ? 'bg-surface-gray-1' : ''"
              @click="verDetalle(row)"
            >
              <td v-if="canSend" class="px-3 py-2" @click.stop>
                <input type="checkbox" class="rounded" :checked="selected.has(row.name)" @change="toggle(row.name)" />
              </td>
              <td class="px-3 py-2">
                <div class="font-medium text-ink-gray-9">{{ row.documento }}</div>
                <div v-if="row.numero_factura && row.numero_factura !== row.documento" class="text-xs text-ink-gray-5">
                  Nº {{ row.numero_factura }}
                </div>
              </td>
              <td class="max-w-[260px] px-3 py-2">
                <div class="truncate text-ink-gray-8" :title="row.tercero">{{ row.tercero }}</div>
                <div class="text-xs text-ink-gray-5">{{ row.nif || 'sin NIF' }}</div>
              </td>
              <td class="whitespace-nowrap px-3 py-2 text-ink-gray-7">{{ fmtDate(row.fecha_contable) }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-ink-gray-7">{{ row.periodo }}/{{ row.ejercicio }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink-gray-9">{{ fmtMoney(row.importe_total) }}</td>
              <td class="whitespace-nowrap px-3 py-2">
                <Badge :theme="siiTheme(row.estado)" variant="subtle" :label="row.estado" />
                <div class="mt-0.5 text-[11px] text-ink-gray-5">
                  {{ row.tipo_comunicacion }}<span v-if="row.entorno"> · {{ row.entorno }}</span><span v-if="row.origen !== 'Frappe'"> · {{ row.origen }}</span>
                </div>
              </td>
              <td class="whitespace-nowrap px-3 py-2" :class="row.vencido ? 'font-medium text-ink-red-7' : 'text-ink-gray-6'">
                {{ fmtDate(row.fecha_limite) }}
              </td>
              <td class="max-w-[320px] px-3 py-2">
                <div v-if="row.descripcion_error" class="line-clamp-2 text-xs" :class="['Aceptado', 'Aceptado con errores'].includes(row.estado) ? 'text-ink-gray-6' : 'text-ink-red-7'">
                  <span v-if="row.codigo_error">[{{ row.codigo_error }}] </span>{{ row.descripcion_error }}
                </div>
                <div v-if="row.csv" class="font-mono text-xs text-ink-gray-6">{{ row.csv }}</div>
                <div v-if="row.fecha_envio" class="text-[11px] text-ink-gray-5">{{ fmtDateTime(row.fecha_envio) }}</div>
              </td>
            </tr>
            <tr v-if="!rows.length && !registros.loading">
              <td :colspan="canSend ? 9 : 8" class="px-3 py-10 text-center text-sm text-ink-gray-5">
                No hay registros SII que cumplan los filtros.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="rows.length" class="flex items-center justify-between text-sm text-ink-gray-6">
        <span>{{ rows.length }} de {{ total }} registros</span>
        <Button v-if="rows.length < total" variant="subtle" :loading="registros.loading" @click="limit += PAGE; registros.reload()">
          Cargar más
        </Button>
      </div>
    </div>

    <SiiDetalleDialog
      v-model="dialogOpen"
      :registro="dialogRegistro"
      :documento="dialogDoc"
      :can-send="canSend"
      @changed="refrescar"
    />

    <Dialog v-model="cruceOpen" :options="{ size: 'lg' }">
      <template #body-title>
        <h3 class="text-lg font-semibold text-ink-gray-9">Cruzar periodo con la AEAT · {{ libro === 'Expedidas' ? 'Emitidas' : 'Recibidas' }}</h3>
      </template>
      <template #body-content>
        <div class="space-y-3 text-sm">
          <p class="text-ink-gray-6">
            Lee de la AEAT todo lo registrado en el mes y lo compara con las facturas de Frappe. Con el entorno de la
            configuración actualiza los registros (y recoge lo que comunicó otro programa, como BC).
          </p>
          <div class="grid grid-cols-3 gap-2">
            <FormControl v-model="cruce.ejercicio" type="text" label="Ejercicio" />
            <FormControl v-model="cruce.periodo" type="select" label="Mes" :options="mesOptions" />
            <FormControl v-model="cruce.entorno" type="select" label="Entorno" :options="entornoOptions" />
          </div>
          <div v-if="cruceRes && cruceRes.ok" class="space-y-2 rounded-md border border-outline-gray-2 p-3">
            <div class="grid grid-cols-3 gap-2">
              <div>
                <div class="text-xs text-ink-gray-5">En la AEAT</div>
                <div class="text-base font-semibold">{{ cruceRes.en_aeat }}</div>
              </div>
              <div>
                <div class="text-xs text-ink-gray-5">Coinciden con Frappe</div>
                <div class="text-base font-semibold">{{ cruceRes.coinciden }}</div>
              </div>
              <div>
                <div class="text-xs text-ink-gray-5">En Frappe y no en la AEAT</div>
                <div class="text-base font-semibold" :class="cruceRes.total_no_en_aeat ? 'text-ink-amber-7' : ''">
                  {{ cruceRes.total_no_en_aeat }}
                </div>
              </div>
            </div>
            <div v-if="cruceRes.sin_factura_local?.length" class="text-xs text-ink-red-7">
              En la AEAT sin factura en Frappe — {{ cruceRes.sin_factura_local.map((x) => x.numero).join(', ') }}
            </div>
            <div v-if="cruceRes.no_en_aeat?.length" class="max-h-24 overflow-auto text-xs text-ink-gray-6">
              No constan — {{ cruceRes.no_en_aeat.join(', ') }}
            </div>
            <div class="text-[11px] text-ink-gray-5">
              Entorno {{ cruceRes.entorno }}{{ cruceRes.actualizados ? ` · ${cruceRes.actualizados} registros actualizados` : '' }}
            </div>
          </div>
          <div v-else-if="cruceRes" class="rounded-md bg-surface-red-1 px-3 py-2 text-ink-red-7">{{ cruceRes.error }}</div>
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="cruceOpen = false">Cerrar</Button>
          <Button variant="solid" :loading="busy === 'cruce'" @click="cruzar">Consultar AEAT</Button>
        </div>
      </template>
    </Dialog>
  </div>
  </div>
</template>
