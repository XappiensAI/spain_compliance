<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Rentabilidad por línea')"
    :seccion="__('Costes y márgenes')"
    :subtitle="etiquetaRango(fromDate, toDate)"
    :companies="companies"
    :fiscal-years="fiscalYears"
    :today="today"
    :loading="report.loading || contexto.loading"
    :error="errorMessage(report.error)"
    :has-data="Boolean(datos)"
    exportable
    @refresh="load"
    @export="exportar"
  >
    <template #filters>
      <CampoFiltro :label="__('Lectura')">
        <TabButtons v-model="modo" :options="opcionesModo" />
      </CampoFiltro>
      <CampoFiltro :label="__('Agrupar por')">
        <Select v-model="agrupar" :options="opcionesAgrupar" class="w-48" />
      </CampoFiltro>
    </template>

    <template v-if="datos">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
        v-if="alerta"
        theme="yellow"
        :title="alerta.titulo"
        :description="alerta.texto"
      />

      <Tarjeta
        :titulo="
          comercial
            ? __('Ventas y margen')
            : __('Ingresos y resultado de explotación')
        "
        :subtitulo="
          __(
            'Las 15 primeras por importe; la línea indica el margen sobre ventas',
          )
        "
      >
        <div class="h-80">
          <EChart :option="grafico" />
        </div>
      </Tarjeta>

      <TablaInforme
        :titulo="tituloTabla"
        :subtitulo="
          comercial
            ? __(
                'Coste de lo vendido según el libro de stock (informe Gross Profit de ERPNext)',
              )
            : __(
                'Ingresos y gastos de los grupos 6 y 7 con la dimensión informada en el asiento',
              )
        "
        :columnas="columnas"
        :filas="datos.filas"
        :totales="{ nombre: __('Total'), ...datos.total }"
        :currency="datos.currency"
        :clase-fila="(f) => (f.clave === '' ? 'text-ink-gray-5 italic' : '')"
        buscable
        :pulsable="Boolean(doctypeAgrupacion)"
        @fila="abrir"
      />
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { Alert, Select, TabButtons, createResource } from 'frappe-ui'
import ReportFrame from '@/components/ReportFrame.vue'
import CampoFiltro from '@/components/informes/CampoFiltro.vue'
import KpiCard from '@/components/informes/KpiCard.vue'
import Tarjeta from '@/components/informes/Tarjeta.vue'
import EChart from '@/components/informes/EChart.vue'
import TablaInforme from '@/components/informes/TablaInforme.vue'
import {
  descargarCsv,
  errorMessage,
  etiquetaRango,
  formatCompact,
  formatMoney,
  formatPct,
  openDesk,
  useInformePeriodo,
} from '@/composables/informe'
import {
  ejeCategoria,
  ejeValor,
  leyendaBase,
  tooltipBase,
} from '@/composables/graficos'
import { COLOR } from '@/composables/paleta'
import LucideTrendingUp from '~icons/lucide/trending-up'
import LucideReceipt from '~icons/lucide/receipt'
import LucidePercent from '~icons/lucide/percent'
import LucideCircleHelp from '~icons/lucide/circle-help'

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

const modo = ref('comercial')
const agrupar = ref('item_group')
const opcionesModo = [
  { label: __('Margen comercial'), value: 'comercial' },
  { label: __('Resultado analítico'), value: 'analitica' },
]

const opciones = createResource({
  url: 'spain_compliance.api.finanzas.opciones_rentabilidad',
  auto: true,
})
const opcionesAgrupar = computed(() => opciones.data?.[modo.value] || [])
const columnasAnaliticas = computed(() => opciones.data?.columnas || [])

const DOCTYPES_COMERCIALES = {
  item_group: 'Item Group',
  item_code: 'Item',
  brand: 'Brand',
  customer_group: 'Customer Group',
  customer: 'Customer',
  territory: 'Territory',
}
const doctypeAgrupacion = computed(() =>
  modo.value === 'comercial'
    ? DOCTYPES_COMERCIALES[agrupar.value]
    : opcionesAgrupar.value.find((o) => o.value === agrupar.value)?.doctype,
)

const report = createResource({
  url: 'spain_compliance.api.finanzas.rentabilidad_por_linea',
})
const datos = computed(() =>
  report.data && report.data.modo === modo.value ? report.data : null,
)
const comercial = computed(() => modo.value === 'comercial')

function load() {
  report.update({
    params: {
      company: company.value,
      from_date: fromDate.value,
      to_date: toDate.value,
      modo: modo.value,
      agrupar: agrupar.value,
    },
  })
  report.reload()
}

whenReady(load)
watch(modo, (valor) => {
  agrupar.value = valor === 'comercial' ? 'item_group' : 'project'
})
watch(agrupar, () => {
  if (company.value && fromDate.value && toDate.value) load()
})

const tituloTabla = computed(() => {
  const opcion = opcionesAgrupar.value.find((o) => o.value === agrupar.value)
  return opcion ? __('Por {0}', opcion.label.toLowerCase()) : ''
})

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const cur = d.currency
  const t = d.total
  const dinero = (key, label, valor, icono, pista = '') => ({
    key,
    label,
    valor: formatCompact(valor, cur),
    titulo: formatMoney(valor, cur),
    icono: markRaw(icono),
    pista,
  })
  if (comercial.value) {
    return [
      dinero('ventas', __('Ventas'), t.ventas, LucideReceipt),
      dinero('coste', __('Coste de lo vendido'), t.coste, LucideReceipt),
      dinero('margen', __('Margen comercial'), t.margen, LucideTrendingUp),
      {
        key: 'pct',
        label: __('Margen sobre ventas'),
        valor: formatPct(t.margen_pct),
        icono: markRaw(LucidePercent),
      },
    ]
  }
  const ingresos = t.cifra_negocios + t.otros_ingresos
  const sinAsignar = d.sin_asignar
  return [
    dinero('ingresos', __('Ingresos de explotación'), ingresos, LucideReceipt),
    dinero(
      'explotacion',
      __('Resultado de explotación'),
      t.resultado_explotacion,
      LucideTrendingUp,
    ),
    {
      key: 'pct',
      label: __('Margen de explotación'),
      valor: formatPct(t.margen_pct),
      icono: markRaw(LucidePercent),
    },
    dinero(
      'sin',
      __('Resultado sin asignar'),
      sinAsignar?.resultado_explotacion || 0,
      LucideCircleHelp,
      __('Asientos sin la dimensión informada'),
    ),
  ]
})

const alerta = computed(() => {
  const d = datos.value
  if (!d) return null
  if (comercial.value && d.ventas_sin_coste > 0.005) {
    return {
      titulo: __(
        '{0} de ventas sin coste asociado',
        formatMoney(d.ventas_sin_coste, d.currency),
      ),
      texto: __(
        'Son ventas de servicios o de artículos sin movimiento de stock ni tasa de valoración. Su margen aparece al 100 %. Para obras y proyectos use el resultado analítico.',
      ),
    }
  }
  if (!comercial.value && d.sin_asignar) {
    const ingresos = d.total.cifra_negocios + d.total.otros_ingresos
    const propios = d.sin_asignar.cifra_negocios + d.sin_asignar.otros_ingresos
    if (ingresos && Math.abs(propios / ingresos) > 0.2) {
      return {
        titulo: __(
          '{0} de los ingresos no tienen la dimensión informada',
          formatPct(propios / ingresos, 0),
        ),
        texto: __(
          'Informe el proyecto o el centro de coste en las facturas y asientos para que el resultado de cada línea sea completo.',
        ),
      }
    }
  }
  return null
})

const columnas = computed(() => {
  const nombre = { key: 'nombre', label: __('Nombre') }
  const pct = {
    key: 'margen_pct',
    label: __('Margen %'),
    tipo: 'pct',
    clase: (f) => (f.margen_pct < 0 ? 'text-ink-red-7' : ''),
  }
  if (comercial.value) {
    return [
      nombre,
      { key: 'qty', label: __('Cantidad'), tipo: 'numero' },
      { key: 'ventas', label: __('Ventas'), tipo: 'moneda' },
      { key: 'coste', label: __('Coste'), tipo: 'moneda' },
      {
        key: 'margen',
        label: __('Margen'),
        tipo: 'moneda',
        clase: (f) => (f.margen < 0 ? 'text-ink-red-7' : ''),
      },
      pct,
    ]
  }
  return [
    nombre,
    ...columnasAnaliticas.value.map((c) => ({
      key: c.key,
      label: c.label,
      tipo: 'moneda',
    })),
    {
      key: 'resultado_explotacion',
      label: __('Resultado de explotación'),
      tipo: 'moneda',
      clase: (f) =>
        `font-medium ${f.resultado_explotacion < 0 ? 'text-ink-red-7' : ''}`,
    },
    pct,
    {
      key: 'resultado',
      label: __('Resultado antes de impuestos'),
      tipo: 'moneda',
    },
  ]
})

const grafico = computed(() => {
  const d = datos.value
  if (!d) return {}
  const cur = d.currency
  const top = d.filas
    .filter((f) => f.clave !== '' || !comercial.value)
    .slice(0, 15)
  const ingresos = (f) =>
    comercial.value ? f.ventas : f.cifra_negocios + f.otros_ingresos
  const margen = (f) => (comercial.value ? f.margen : f.resultado_explotacion)
  return {
    grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
    legend: leyendaBase({ top: 0 }),
    tooltip: tooltipBase({
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) =>
        [
          params[0]?.name,
          ...params.map(
            (p) =>
              `${p.marker}${p.seriesName} <b>${
                p.seriesIndex === 2
                  ? formatPct(p.value)
                  : formatMoney(p.value, cur)
              }</b>`,
          ),
        ].join('<br/>'),
    }),
    xAxis: ejeCategoria(
      top.map((f) => f.nombre),
      {
        axisLabel: {
          interval: 0,
          rotate: top.length > 6 ? 30 : 0,
          width: 110,
          overflow: 'truncate',
        },
      },
    ),
    yAxis: [
      ejeValor(cur),
      {
        type: 'value',
        position: 'right',
        splitLine: { show: false },
        axisLabel: { formatter: (v) => formatPct(v, 0) },
      },
    ],
    series: [
      {
        name: comercial.value ? __('Ventas') : __('Ingresos'),
        type: 'bar',
        barMaxWidth: 28,
        itemStyle: { color: COLOR.anterior, borderRadius: 4 },
        data: top.map(ingresos),
      },
      {
        name: comercial.value ? __('Margen') : __('Resultado de explotación'),
        type: 'bar',
        barMaxWidth: 28,
        data: top.map((f) => ({
          value: margen(f),
          itemStyle: {
            color: margen(f) >= 0 ? COLOR.positivo : COLOR.negativo,
            borderRadius: 4,
          },
        })),
      },
      {
        name: __('Margen %'),
        type: 'line',
        yAxisIndex: 1,
        symbolSize: 6,
        itemStyle: { color: COLOR.total },
        data: top.map((f) => f.margen_pct),
      },
    ],
  }
})

function abrir(fila) {
  if (fila.clave && doctypeAgrupacion.value)
    openDesk(doctypeAgrupacion.value, fila.clave)
}

function exportar() {
  const d = datos.value
  descargarCsv(
    `rentabilidad-${modo.value}-${agrupar.value}-${company.value}-${d.from_date}-${d.to_date}`,
    [__('Clave'), ...columnas.value.map((c) => c.label)],
    d.filas.map((f) => [f.clave, ...columnas.value.map((c) => f[c.key] ?? '')]),
  )
}
</script>
