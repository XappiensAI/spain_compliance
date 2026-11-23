<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Estado de flujos de efectivo')"
    :subtitle="subtitulo"
    :companies="companies"
    :fiscal-years="fiscalYears"
    :today="today"
    :loading="report.loading || contexto.loading"
    :error="errorMessage(report.error)"
    :has-data="Boolean(datos)"
    :badges="[
      { label: __('PGC · modelo normal · método indirecto'), theme: 'blue' },
    ]"
    exportable
    @refresh="load"
    @export="exportar"
  >
    <template #filters>
      <CampoFiltro :label="__('Comparar con el año anterior')">
        <Switch v-model="comparar" />
      </CampoFiltro>
      <CampoFiltro :label="__('Detalle de la tabla')">
        <TabButtons v-model="detalle" :options="opcionesDetalle" />
      </CampoFiltro>
      <CampoFiltro :label="__('Líneas sin importe')">
        <Switch v-model="mostrarCeros" />
      </CampoFiltro>
    </template>

    <template v-if="datos">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          v-for="kpi in kpis"
          :key="kpi.key"
          :label="kpi.label"
          :valor="formatCompact(kpi.valor, datos.currency)"
          :titulo="formatMoney(kpi.valor, datos.currency)"
          :delta="kpi.delta"
          :delta-texto="kpi.deltaTexto"
          :pista="kpi.pista"
          :icono="kpi.icono"
          :neutro="kpi.neutro"
        />
      </div>

      <Alert
        v-if="descuadre"
        theme="yellow"
        :title="__('El estado no explica toda la variación del efectivo')"
        :description="
          __(
            'Diferencia de {0}. Suele deberse a un balance descuadrado (revise el balance de situación a ambas fechas).',
            formatMoney(descuadre, datos.currency),
          )
        "
      />

      <div class="grid gap-4 xl:grid-cols-5">
        <Tarjeta
          class="xl:col-span-3"
          :titulo="__('Del efectivo inicial al final')"
          :subtitulo="
            __('Aportación de cada actividad a la variación de tesorería')
          "
        >
          <div class="h-72">
            <EChart :option="cascada" />
          </div>
        </Tarjeta>
        <Tarjeta
          class="xl:col-span-2"
          :titulo="__('Calidad del flujo de explotación')"
          :subtitulo="
            __('Del resultado antes de impuestos al flujo de explotación')
          "
        >
          <ul class="flex flex-col divide-y divide-outline-gray-1">
            <li
              v-for="fila in puente"
              :key="fila.code"
              class="flex items-center justify-between gap-3 py-2 text-base"
              :class="
                fila.total ? 'font-semibold text-ink-gray-9' : 'text-ink-gray-7'
              "
            >
              <span class="truncate">{{ fila.label }}</span>
              <span
                class="tabular-nums"
                :class="!fila.total && fila.valor < 0 ? 'text-ink-red-7' : ''"
              >
                {{ formatMoney(fila.valor, datos.currency) }}
              </span>
            </li>
          </ul>
          <p class="mt-3 text-xs text-ink-gray-5">
            {{ conversion }}
          </p>
        </Tarjeta>
      </div>

      <StatementTable
        :titulo="__('Estado de flujos de efectivo')"
        :subtitulo="
          __(
            'Despliegue cada línea hasta la partida del balance o de la PyG que la origina. Las inversiones de una misma clase se presentan netas.',
          )
        "
        :nodos="nodos"
        :periodos="etiquetasPeriodo"
        :detalle="detalle"
        :mostrar-ceros="mostrarCeros"
        :total="totalE"
        tono="pyg"
      />

      <section
        class="grid gap-3 rounded-xl border border-outline-gray-1 bg-surface-elevation-1 p-4 sm:grid-cols-3"
      >
        <div v-for="dato in efectivoResumen" :key="dato.label">
          <div class="text-sm text-ink-gray-5">{{ dato.label }}</div>
          <div class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">
            {{ formatMoney(dato.valor, datos.currency) }}
          </div>
        </div>
      </section>

      <Avisos :avisos="datos.avisos" />
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { Alert, Switch, TabButtons, createResource } from 'frappe-ui'
import ReportFrame from '@/components/ReportFrame.vue'
import CampoFiltro from '@/components/informes/CampoFiltro.vue'
import KpiCard from '@/components/informes/KpiCard.vue'
import Tarjeta from '@/components/informes/Tarjeta.vue'
import EChart from '@/components/informes/EChart.vue'
import StatementTable from '@/components/informes/StatementTable.vue'
import Avisos from '@/components/informes/Avisos.vue'
import {
  descargarCsv,
  errorMessage,
  etiquetaRango,
  formatCompact,
  formatMoney,
  formatPct,
  useInformePeriodo,
  variacion,
} from '@/composables/informe'
import { aplanarEstado, buscarNodo } from '@/composables/estados'
import { ejeCategoria, ejeValor, tooltipBase } from '@/composables/graficos'
import { COLOR } from '@/composables/paleta'
import LucideActivity from '~icons/lucide/activity'
import LucideFactory from '~icons/lucide/factory'
import LucideLandmark from '~icons/lucide/landmark'
import LucideArrowLeftRight from '~icons/lucide/arrow-left-right'
import LucideWallet from '~icons/lucide/wallet'

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

const comparar = ref(true)
const detalle = ref('partidas')
const mostrarCeros = ref(false)
const opcionesDetalle = [
  { label: __('Líneas'), value: 'epigrafes' },
  { label: __('Partidas'), value: 'partidas' },
  { label: __('Origen'), value: 'cuentas' },
]

const report = createResource({
  url: 'spain_compliance.api.finanzas.estado_flujos_efectivo',
})
const datos = computed(() => report.data || null)

function load() {
  report.update({
    params: {
      company: company.value,
      from_date: fromDate.value,
      to_date: toDate.value,
      comparar: comparar.value ? 1 : 0,
    },
  })
  report.reload()
}

whenReady(load)
watch(comparar, () => {
  if (company.value && fromDate.value && toDate.value) load()
})

const etiquetasPeriodo = computed(() =>
  (datos.value?.periodos || []).map((p) => p.label),
)
const nodos = computed(() =>
  (datos.value?.lineas || []).filter((n) => n.code !== 'E'),
)
const totalE = computed(
  () => (datos.value?.lineas || []).find((n) => n.code === 'E') || null,
)

const subtitulo = computed(() => {
  if (!datos.value) return etiquetaRango(fromDate.value, toDate.value)
  const [actual, anterior] = datos.value.periodos
  const texto = etiquetaRango(actual.desde, actual.hasta)
  return anterior
    ? __(
        '{0} frente a {1}',
        texto,
        etiquetaRango(anterior.desde, anterior.hasta),
      )
    : texto
})

function valor(code, i = 0) {
  const nodo = buscarNodo(datos.value?.lineas || [], code)
  return nodo ? nodo.importes[i] || 0 : 0
}

const descuadre = computed(() => {
  const d = datos.value?.efectivo?.[0]?.diferencia || 0
  return Math.abs(d) >= 0.01 ? d : 0
})

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const hayAnterior = d.periodos.length > 1
  const tarjeta = (key, code, label, icono, pista = '', neutro = false) => ({
    key,
    label,
    valor: valor(code),
    icono: markRaw(icono),
    pista,
    neutro,
    delta: hayAnterior ? variacion(valor(code), valor(code, 1)).pct : null,
    deltaTexto: hayAnterior ? __('vs {0}', d.periodos[1].label) : '',
  })
  return [
    tarjeta(
      'explotacion',
      'A.5',
      __('Flujo de explotación'),
      LucideFactory,
      __('Caja generada por el negocio'),
    ),
    tarjeta(
      'inversion',
      'B.8',
      __('Flujo de inversión'),
      LucideActivity,
      __('Compras y ventas de inmovilizado e inversiones'),
      true,
    ),
    tarjeta(
      'financiacion',
      'C.12',
      __('Flujo de financiación'),
      LucideLandmark,
      __('Socios, deuda financiera y dividendos'),
      true,
    ),
    {
      ...tarjeta(
        'libre',
        'A.5',
        __('Flujo de caja libre'),
        LucideArrowLeftRight,
        __('Explotación más inversión'),
      ),
      valor: valor('A.5') + valor('B.8'),
      delta: hayAnterior
        ? variacion(
            valor('A.5') + valor('B.8'),
            valor('A.5', 1) + valor('B.8', 1),
          ).pct
        : null,
    },
    tarjeta(
      'neto',
      'E',
      __('Variación neta del efectivo'),
      LucideWallet,
      __('Efectivo final {0}', formatMoney(d.efectivo[0].fin, d.currency)),
      true,
    ),
  ]
})

const cascada = computed(() => {
  const d = datos.value
  if (!d) return {}
  const cur = d.currency
  const pasos = [
    { label: __('Efectivo inicial'), valor: d.efectivo[0].inicio, total: true },
    { label: __('Explotación'), valor: valor('A.5') },
    { label: __('Inversión'), valor: valor('B.8') },
    { label: __('Financiación'), valor: valor('C.12') },
    { label: __('Tipo de cambio'), valor: valor('D') },
    { label: __('Efectivo final'), valor: d.efectivo[0].fin, total: true },
  ]
  let acumulado = 0
  const base = []
  const barras = []
  for (const paso of pasos) {
    if (paso.total) {
      base.push(0)
      barras.push({
        value: paso.valor,
        itemStyle: { color: COLOR.total, borderRadius: 4 },
      })
      acumulado = paso.valor
      continue
    }
    const inicio = acumulado
    acumulado += paso.valor
    base.push(Math.min(inicio, acumulado))
    barras.push({
      value: Math.abs(paso.valor),
      real: paso.valor,
      itemStyle: {
        color: paso.valor >= 0 ? COLOR.positivo : COLOR.negativo,
        borderRadius: 4,
      },
    })
  }
  return {
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: tooltipBase({
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const barra = params.find((p) => p.seriesIndex === 1)
        const real = barra?.data?.real ?? barra?.value
        return `${barra.name}<br/><b>${formatMoney(real, cur)}</b>`
      },
    }),
    xAxis: ejeCategoria(pasos.map((p) => p.label)),
    yAxis: ejeValor(cur),
    series: [
      {
        type: 'bar',
        stack: 'c',
        itemStyle: { color: 'transparent' },
        data: base,
        silent: true,
      },
      { type: 'bar', stack: 'c', barMaxWidth: 56, data: barras },
    ],
  }
})

const puente = computed(() => [
  {
    code: 'A.1',
    label: __('Resultado antes de impuestos'),
    valor: valor('A.1'),
  },
  {
    code: 'A.2',
    label: __('+ Ajustes sin movimiento de caja'),
    valor: valor('A.2'),
  },
  {
    code: 'A.3',
    label: __('+ Variación del capital corriente'),
    valor: valor('A.3'),
  },
  {
    code: 'A.4',
    label: __('+ Intereses e impuestos cobrados y pagados'),
    valor: valor('A.4'),
  },
  {
    code: 'A.5',
    label: __('= Flujo de explotación'),
    valor: valor('A.5'),
    total: true,
  },
])

const conversion = computed(() => {
  const resultado = valor('A.1')
  if (Math.abs(resultado) < 0.005) return ''
  return __(
    'Por cada 100 € de resultado antes de impuestos el negocio ha generado {0} de caja de explotación.',
    formatPct(valor('A.5') / resultado, 0).replace(' %', ' €'),
  )
})

const efectivoResumen = computed(() => {
  const e = datos.value?.efectivo?.[0]
  if (!e) return []
  return [
    { label: __('Efectivo al comienzo del periodo'), valor: e.inicio },
    { label: __('Efectivo al final del periodo'), valor: e.fin },
    { label: __('Variación según balance (B.VII)'), valor: e.variacion },
  ]
})

function exportar() {
  const d = datos.value
  descargarCsv(
    `flujos-de-efectivo-${company.value}-${d.from_date}-${d.to_date}`,
    [__('Código'), __('Concepto'), ...etiquetasPeriodo.value],
    aplanarEstado(d.lineas).map((fila) => [
      fila.codigo,
      fila.concepto,
      ...fila.importes,
    ]),
  )
}
</script>
