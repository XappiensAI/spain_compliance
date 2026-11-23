<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Valoración de existencias')"
    :seccion="__('Costes y márgenes')"
    :subtitle="subtitulo"
    :companies="companies"
    :fiscal-years="fiscalYears"
    :today="today"
    :loading="report.loading || contexto.loading"
    :error="errorMessage(report.error)"
    :has-data="Boolean(datos)"
    as-of
    exportable
    @refresh="load"
    @export="exportar"
  >
    <template #filters>
      <CampoFiltro :label="__('Sin salidas desde hace (días)')">
        <TextInput
          v-model="dias"
          type="number"
          class="w-28"
          @keyup.enter="load"
        />
      </CampoFiltro>
      <CampoFiltro :label="__('Ver')">
        <TabButtons v-model="vista" :options="opcionesVista" />
      </CampoFiltro>
    </template>

    <template v-if="datos">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          v-for="kpi in kpis"
          :key="kpi.key"
          :label="kpi.label"
          :valor="kpi.valor"
          :titulo="kpi.titulo"
          :pista="kpi.pista"
          :icono="kpi.icono"
        />
      </div>

      <Alert
        v-if="alertaContable"
        theme="yellow"
        :title="__('El libro de stock no coincide con la contabilidad')"
        :description="alertaContable"
      />
      <Alert
        v-if="datos.negativos"
        theme="red"
        :title="__('{0} artículos con existencias negativas', datos.negativos)"
        :description="
          __(
            'Las salidas registradas antes que sus entradas distorsionan la valoración. Revise las fechas de los movimientos o active la validación de stock negativo.',
          )
        "
      />

      <div class="grid gap-4 xl:grid-cols-5">
        <Tarjeta
          class="xl:col-span-2"
          :titulo="__('Por clase de existencias')"
          :subtitulo="__('Subgrupos 30 a 36 del PGC')"
        >
          <div class="h-72">
            <EChart :option="graficoClases" @click="filtrarClase" />
          </div>
        </Tarjeta>
        <Tarjeta
          class="xl:col-span-3"
          :titulo="__('Detalle por clase')"
          :subtitulo="__('Pulse una clase para ver sus artículos')"
        >
          <ul class="flex flex-col divide-y divide-outline-gray-1">
            <li
              v-for="c in datos.clases"
              :key="c.clase"
              class="flex cursor-pointer items-center gap-3 py-2 text-base hover:bg-surface-gray-1"
              :class="clase === c.clase ? 'font-semibold' : ''"
              @click="filtrarClase({ name: c.clase })"
            >
              <span
                class="size-2.5 shrink-0 rounded-full"
                :style="{ background: colorClase(c.clase) }"
              />
              <span class="flex-1 truncate text-ink-gray-8">{{
                __(c.clase)
              }}</span>
              <span class="text-sm text-ink-gray-5">{{
                __('{0} líneas', c.articulos)
              }}</span>
              <span class="w-32 text-right tabular-nums text-ink-gray-9">
                {{ formatMoney(c.valor, datos.currency) }}
              </span>
              <span
                class="w-14 text-right text-sm tabular-nums text-ink-gray-5"
              >
                {{ formatPct(datos.total ? c.valor / datos.total : 0, 0) }}
              </span>
            </li>
          </ul>
        </Tarjeta>
      </div>

      <TablaInforme
        v-if="vista === 'almacenes'"
        :titulo="__('Por almacén')"
        :columnas="columnasAlmacenes"
        :filas="datos.almacenes"
        :currency="datos.currency"
        :totales="{ warehouse: __('Total'), valor: datos.total }"
        buscable
      />
      <TablaInforme
        v-else
        :titulo="tituloArticulos"
        :subtitulo="subtituloArticulos"
        :columnas="columnasArticulos"
        :filas="articulosFiltrados"
        :currency="datos.currency"
        :clase-fila="(f) => (f.qty < 0 ? 'text-ink-red-7' : '')"
        buscable
        pulsable
        @fila="(f) => openDesk('Item', f.item_code)"
      >
        <template #acciones>
          <Button
            v-if="clase || soloLentos"
            :label="__('Quitar filtro')"
            variant="ghost"
            @click="quitarFiltro"
          />
          <Button
            v-else
            :label="__('Solo sin salidas')"
            variant="subtle"
            @click="soloLentos = true"
          />
        </template>
      </TablaInforme>

      <p class="text-xs text-ink-gray-5">
        {{
          __(
            'La clase se decide por este orden: campo «Clase de existencias» del almacén, almacén de trabajo en curso, campo del grupo de artículos, cuenta de existencias del almacén (31 a 36) y, por último, el uso del artículo en listas de materiales.',
          )
        }}
      </p>
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref } from 'vue'
import { Alert, Button, TabButtons, TextInput, createResource } from 'frappe-ui'
import ReportFrame from '@/components/ReportFrame.vue'
import CampoFiltro from '@/components/informes/CampoFiltro.vue'
import KpiCard from '@/components/informes/KpiCard.vue'
import Tarjeta from '@/components/informes/Tarjeta.vue'
import EChart from '@/components/informes/EChart.vue'
import TablaInforme from '@/components/informes/TablaInforme.vue'
import {
  descargarCsv,
  errorMessage,
  formatCompact,
  formatDate,
  formatMoney,
  formatPct,
  openDesk,
  useInformePeriodo,
} from '@/composables/informe'
import { tooltipBase } from '@/composables/graficos'
import LucidePackage from '~icons/lucide/package'
import LucideBoxes from '~icons/lucide/boxes'
import LucideWrench from '~icons/lucide/wrench'
import LucidePackageCheck from '~icons/lucide/package-check'
import LucideSnail from '~icons/lucide/snail'

const {
  company,
  fromDate,
  toDate,
  companies,
  fiscalYears,
  today,
  contexto,
  whenReady,
} = useInformePeriodo()

const dias = ref(180)
const vista = ref('articulos')
const clase = ref('')
const soloLentos = ref(false)
const opcionesVista = [
  { label: __('Artículos'), value: 'articulos' },
  { label: __('Almacenes'), value: 'almacenes' },
]

const COLORES = {
  Mercaderías: '#0EA5E9',
  'Materias primas': '#4F46E5',
  'Otros aprovisionamientos': '#06B6D4',
  'Productos en curso': '#F59E0B',
  'Productos semiterminados': '#EC4899',
  'Productos terminados': '#10B981',
  'Subproductos, residuos y materiales recuperados': '#94A3B8',
}
const colorClase = (c) => COLORES[c] || '#94A3B8'

const report = createResource({
  url: 'spain_compliance.api.finanzas.valoracion_existencias',
})
const datos = computed(() => report.data || null)

function load() {
  report.update({
    params: {
      company: company.value,
      to_date: toDate.value,
      dias_sin_salida: dias.value,
    },
  })
  report.reload()
}

whenReady(load)

const subtitulo = computed(() =>
  datos.value ? __('Existencias a {0}', formatDate(datos.value.fecha)) : '',
)

function valorClase(...nombres) {
  return (datos.value?.clases || [])
    .filter((c) => nombres.includes(c.clase))
    .reduce((s, c) => s + c.valor, 0)
}

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const cur = d.currency
  const tarjeta = (key, label, valor, icono, pista = '') => ({
    key,
    label,
    valor: formatCompact(valor, cur),
    titulo: formatMoney(valor, cur),
    icono: markRaw(icono),
    pista:
      pista ||
      (d.total ? __('{0} del total', formatPct(valor / d.total, 0)) : ''),
  })
  return [
    tarjeta(
      'total',
      __('Existencias valoradas'),
      d.total,
      LucidePackage,
      __('{0} líneas artículo-almacén', d.articulos_total),
    ),
    tarjeta(
      'mp',
      __('Materias primas y aprovisionamientos'),
      valorClase('Materias primas', 'Otros aprovisionamientos'),
      LucideBoxes,
    ),
    tarjeta(
      'wip',
      __('Productos en curso'),
      valorClase('Productos en curso', 'Productos semiterminados'),
      LucideWrench,
      __('Incluye semiterminados'),
    ),
    tarjeta(
      'pt',
      __('Terminados y mercaderías'),
      valorClase(
        'Productos terminados',
        'Mercaderías',
        'Subproductos, residuos y materiales recuperados',
      ),
      LucidePackageCheck,
    ),
    tarjeta(
      'lento',
      __('Sin salidas en {0} días', d.sin_salida.dias),
      d.sin_salida.valor,
      LucideSnail,
      __('{0} líneas', d.sin_salida.articulos),
    ),
  ]
})

const alertaContable = computed(() => {
  const d = datos.value
  if (
    !d ||
    d.diferencia_contable === null ||
    Math.abs(d.diferencia_contable) < 1
  )
    return ''
  return __(
    'El saldo de las cuentas de existencias ({0}) es {1} y el libro de stock suma {2}, una diferencia de {3}. Suele deberse a asientos manuales en cuentas de existencias, a almacenes sin cuenta o a movimientos contabilizados en otra cuenta.',
    d.cuentas_stock.join(', ') || '—',
    formatMoney(d.contable, d.currency),
    formatMoney(d.total, d.currency),
    formatMoney(d.diferencia_contable, d.currency),
  )
})

const graficoClases = computed(() => {
  const d = datos.value
  if (!d) return {}
  return {
    tooltip: tooltipBase({
      trigger: 'item',
      formatter: (p) =>
        `${p.data.label}<br/><b>${formatMoney(p.value, d.currency)}</b> (${p.percent} %)`,
    }),
    series: [
      {
        type: 'pie',
        radius: ['55%', '80%'],
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        data: d.clases
          .filter((c) => c.valor > 0)
          .map((c) => ({
            name: c.clase,
            label: __(c.clase),
            value: c.valor,
            itemStyle: { color: colorClase(c.clase) },
          })),
      },
    ],
  }
})

function filtrarClase(p) {
  if (!p?.name) return
  clase.value = clase.value === p.name ? '' : p.name
  vista.value = 'articulos'
}

function quitarFiltro() {
  clase.value = ''
  soloLentos.value = false
}

const articulosFiltrados = computed(() =>
  (datos.value?.articulos || []).filter(
    (a) =>
      (!clase.value || a.clase === clase.value) &&
      (!soloLentos.value || a.lento),
  ),
)

const tituloArticulos = computed(() => {
  if (clase.value) return __('Artículos · {0}', __(clase.value))
  if (soloLentos.value) return __('Artículos sin salidas')
  return __('Artículos')
})

const subtituloArticulos = computed(() => {
  const d = datos.value
  if (d && d.articulos_total > d.articulos.length) {
    return __(
      'Se muestran las {0} líneas de mayor valor de {1}',
      d.articulos.length,
      d.articulos_total,
    )
  }
  return __('Pulse una fila para abrir el artículo')
})

const columnasArticulos = [
  { key: 'item_code', label: __('Artículo') },
  { key: 'item_name', label: __('Descripción') },
  { key: 'warehouse', label: __('Almacén') },
  { key: 'clase', label: __('Clase'), valor: (f) => __(f.clase) },
  { key: 'motivo', label: __('Según') },
  { key: 'qty', label: __('Cantidad'), tipo: 'numero', decimales: 3 },
  { key: 'uom', label: __('Ud.') },
  { key: 'precio_medio', label: __('Precio medio'), tipo: 'moneda' },
  { key: 'valor', label: __('Valor'), tipo: 'moneda' },
  { key: 'ultima_salida', label: __('Última salida'), tipo: 'fecha' },
  {
    key: 'dias_sin_salida',
    label: __('Días'),
    tipo: 'dias',
    clase: (f) => (f.lento ? 'text-ink-amber-7 font-medium' : ''),
  },
]

const columnasAlmacenes = [
  { key: 'warehouse', label: __('Almacén') },
  { key: 'cuenta', label: __('Cuenta') },
  { key: 'articulos', label: __('Líneas'), tipo: 'entero' },
  { key: 'valor', label: __('Valor'), tipo: 'moneda' },
]

function exportar() {
  const d = datos.value
  descargarCsv(
    `existencias-${company.value}-${d.fecha}`,
    columnasArticulos.map((c) => c.label),
    d.articulos.map((a) => [
      a.item_code,
      a.item_name,
      a.warehouse,
      a.clase,
      a.motivo,
      a.qty,
      a.uom,
      a.precio_medio ?? '',
      a.valor,
      a.ultima_salida,
      a.dias_sin_salida ?? '',
    ]),
  )
}
</script>
