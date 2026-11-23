<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Indicadores de gestión')"
    :subtitle="subtitulo"
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
      <CampoFiltro :label="__('Comparar con el año anterior')">
        <Switch v-model="comparar" />
      </CampoFiltro>
    </template>

    <template v-if="datos">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          v-for="kpi in principales"
          :key="kpi.key"
          :label="kpi.label"
          :valor="kpi.texto"
          :titulo="kpi.titulo"
          :delta="kpi.delta"
          :delta-texto="kpi.deltaTexto"
          :pista="kpi.pista"
          :icono="kpi.icono"
          :serie="kpi.serie"
          :color="kpi.color"
        />
      </div>

      <Alert
        v-if="sinPersonal"
        theme="yellow"
        :title="__('No hay gastos de personal contabilizados en el periodo')"
        :description="
          __(
            'El EBITDA y los márgenes salen inflados. Compruebe que las nóminas se contabilizan en el grupo 64 del PGC.',
          )
        "
      />
      <Alert
        v-if="!actual.plantilla"
        theme="blue"
        :title="__('Sin plantilla media para calcular el ingreso por empleado')"
        :description="
          __(
            'Indique la plantilla media en la ficha de la compañía (sección Indicadores) o registre los empleados con su fecha de alta y de baja.',
          )
        "
      />

      <Tarjeta
        :titulo="__('Evolución mensual')"
        :subtitulo="__('Cifra de negocios, EBITDA y margen EBITDA de cada mes')"
      >
        <div class="h-72">
          <EChart :option="grafico" />
        </div>
      </Tarjeta>

      <div class="grid gap-4 xl:grid-cols-2">
        <Tarjeta
          v-for="grupo in grupos"
          :key="grupo.titulo"
          :titulo="grupo.titulo"
          sin-relleno
        >
          <table class="w-full text-base">
            <thead>
              <tr class="text-sm text-ink-gray-5">
                <th class="px-4 py-2 text-left font-normal">
                  {{ __('Indicador') }}
                </th>
                <th class="px-4 py-2 text-right font-normal">
                  {{ etiquetas[0] }}
                </th>
                <th v-if="anterior" class="px-4 py-2 text-right font-normal">
                  {{ etiquetas[1] }}
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-outline-gray-1">
              <tr v-for="ind in grupo.indicadores" :key="ind.key">
                <td class="px-4 py-2">
                  <div class="flex items-center gap-2 text-ink-gray-8">
                    <span
                      v-if="ind.estado"
                      class="size-2 shrink-0 rounded-full"
                      :style="{ background: ESTADO_RATIO[ind.estado].color }"
                      :title="__(ESTADO_RATIO[ind.estado].label)"
                    />
                    {{ ind.label }}
                  </div>
                  <div class="text-xs text-ink-gray-5">{{ ind.formula }}</div>
                </td>
                <td
                  class="px-4 py-2 text-right font-medium tabular-nums text-ink-gray-9"
                >
                  {{ ind.formato(actual[ind.key]) }}
                </td>
                <td
                  v-if="anterior"
                  class="px-4 py-2 text-right tabular-nums text-ink-gray-6"
                >
                  {{ ind.formato(anterior[ind.key]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </Tarjeta>
      </div>

      <p class="text-xs text-ink-gray-5">
        {{
          __(
            'Rentabilidades anualizadas. Los plazos de cobro y pago usan los importes facturados con IVA del periodo; el periodo medio de pago a proveedores sigue la Resolución del ICAC de 29 de enero de 2016.',
          )
        }}
      </p>
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { Alert, Switch, createResource } from 'frappe-ui'
import ReportFrame from '@/components/ReportFrame.vue'
import CampoFiltro from '@/components/informes/CampoFiltro.vue'
import KpiCard from '@/components/informes/KpiCard.vue'
import Tarjeta from '@/components/informes/Tarjeta.vue'
import EChart from '@/components/informes/EChart.vue'
import {
  descargarCsv,
  errorMessage,
  etiquetaRango,
  formatCompact,
  formatDate,
  formatMoney,
  formatNumber,
  formatPct,
  formatRatio,
  useInformePeriodo,
  variacion,
} from '@/composables/informe'
import {
  ejeCategoria,
  ejeValor,
  leyendaBase,
  nombreMes,
  tooltipBase,
} from '@/composables/graficos'
import { COLOR, ESTADO_RATIO } from '@/composables/paleta'
import LucideTrendingUp from '~icons/lucide/trending-up'
import LucidePercent from '~icons/lucide/percent'
import LucideDroplets from '~icons/lucide/droplets'
import LucideUsers from '~icons/lucide/users'

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

const report = createResource({
  url: 'spain_compliance.api.finanzas.indicadores_gestion',
})
const datos = computed(() => report.data || null)
const actual = computed(() => datos.value?.periodos?.[0] || {})
const anterior = computed(() => datos.value?.periodos?.[1] || null)
const etiquetas = computed(() =>
  (datos.value?.periodos || []).map((p) => p.label),
)

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

const subtitulo = computed(() => {
  if (!datos.value) return etiquetaRango(fromDate.value, toDate.value)
  return anterior.value
    ? __('{0} frente a {1}', etiquetas.value[0], etiquetas.value[1])
    : etiquetas.value[0]
})

const cur = computed(() => datos.value?.currency || 'EUR')
const dinero = (v) =>
  v === null || v === undefined ? '—' : formatMoney(v, cur.value)
const pct = (v) => (v === null || v === undefined ? '—' : formatPct(v))
const ratio = (v) => (v === null || v === undefined ? '—' : formatRatio(v))
const dias = (v) =>
  v === null || v === undefined ? '—' : `${formatNumber(v, 0)} ${__('días')}`
const numero = (v) => (v === null || v === undefined ? '—' : formatNumber(v, 1))

const sinPersonal = computed(
  () =>
    actual.value.cifra_negocios > 0 &&
    Math.abs(actual.value.gastos_personal || 0) < 0.005,
)

function delta(key, menosEsMejor = false) {
  if (!anterior.value) return { delta: null, deltaTexto: '' }
  const a = actual.value[key]
  const b = anterior.value[key]
  if (a === null || a === undefined || b === null || b === undefined) {
    return { delta: null, deltaTexto: '' }
  }
  return {
    delta: variacion(a, b).pct,
    deltaTexto: __('vs {0}', etiquetas.value[1]),
    menosEsMejor,
  }
}

const principales = computed(() => {
  const a = actual.value
  if (!datos.value) return []
  return [
    {
      key: 'ebitda',
      label: __('EBITDA'),
      texto: formatCompact(a.ebitda, cur.value),
      titulo: formatMoney(a.ebitda, cur.value),
      pista: __('Margen EBITDA {0}', pct(a.margen_ebitda)),
      icono: markRaw(LucideTrendingUp),
      serie: a.serie_ebitda,
      color: COLOR.total,
      ...delta('ebitda'),
    },
    {
      key: 'margen_operativo',
      label: __('Margen operativo'),
      texto: pct(a.margen_operativo),
      pista: __(
        'Resultado de explotación {0}',
        formatCompact(a.resultado_explotacion, cur.value),
      ),
      icono: markRaw(LucidePercent),
      serie: a.serie_explotacion,
      color: COLOR.positivo,
      ...delta('margen_operativo'),
    },
    {
      key: 'liquidez',
      label: __('Índice de liquidez'),
      texto: ratio(a.liquidez),
      pista: __(
        'Tesorería {0} a {1}',
        formatCompact(datos.value.tesoreria, cur.value),
        formatDate(datos.value.tesoreria_fecha),
      ),
      icono: markRaw(LucideDroplets),
      ...delta('liquidez'),
    },
    {
      key: 'ingreso_por_empleado',
      label: __('Ingreso por empleado'),
      texto:
        a.ingreso_por_empleado === null
          ? '—'
          : formatCompact(a.ingreso_por_empleado_anual, cur.value),
      titulo:
        a.ingreso_por_empleado === null
          ? ''
          : formatMoney(a.ingreso_por_empleado_anual, cur.value),
      pista: a.plantilla
        ? __(
            'Anualizado · plantilla media {0} ({1})',
            numero(a.plantilla),
            a.plantilla_origen === 'manual'
              ? __('indicada en la compañía')
              : __('según empleados'),
          )
        : __('Sin plantilla media'),
      icono: markRaw(LucideUsers),
      ...delta('ingreso_por_empleado_anual'),
    },
  ]
})

function semaforo(valor, umbrales) {
  if (valor === null || valor === undefined) return null
  const [riesgo, ajustado, optimo] = umbrales
  if (valor < riesgo) return 'riesgo'
  if (valor < ajustado) return 'ajustado'
  if (valor <= optimo) return 'optimo'
  return 'holgado'
}

const grupos = computed(() => {
  const a = actual.value
  const pmp = datos.value?.pmp || {}
  return [
    {
      titulo: __('Resultados y márgenes'),
      indicadores: [
        {
          key: 'cifra_negocios',
          label: __('Cifra de negocios'),
          formula: __('Línea 1 de la PyG'),
          formato: dinero,
        },
        {
          key: 'margen_bruto',
          label: __('Margen bruto'),
          formula: __(
            'Cifra de negocios + variación de existencias (2) + aprovisionamientos (4)',
          ),
          formato: dinero,
        },
        {
          key: 'margen_bruto_pct',
          label: __('Margen bruto %'),
          formula: __('Margen bruto / cifra de negocios'),
          formato: pct,
        },
        {
          key: 'ebitda',
          label: __('EBITDA'),
          formula: __(
            'Resultado de explotación + amortización (8) + deterioros y resultados por enajenación (11)',
          ),
          formato: dinero,
        },
        {
          key: 'margen_ebitda',
          label: __('Margen EBITDA'),
          formula: __('EBITDA / cifra de negocios'),
          formato: pct,
        },
        {
          key: 'resultado_explotacion',
          label: __('Resultado de explotación'),
          formula: __('Subtotal A.1 de la PyG'),
          formato: dinero,
        },
        {
          key: 'margen_operativo',
          label: __('Margen operativo'),
          formula: __('Resultado de explotación / cifra de negocios'),
          formato: pct,
        },
        {
          key: 'margen_neto',
          label: __('Margen neto'),
          formula: __('Resultado del ejercicio / cifra de negocios'),
          formato: pct,
        },
        {
          key: 'peso_personal',
          label: __('Peso de los gastos de personal'),
          formula: __('Gastos de personal (6) / cifra de negocios'),
          formato: pct,
        },
      ],
    },
    {
      titulo: __('Liquidez y solvencia'),
      indicadores: [
        {
          key: 'liquidez',
          label: __('Liquidez'),
          formula: __('Activo corriente / pasivo corriente'),
          formato: ratio,
          estado: semaforo(a.liquidez, [1, 1.5, 2]),
        },
        {
          key: 'acida',
          label: __('Prueba ácida'),
          formula: __('(Activo corriente − existencias) / pasivo corriente'),
          formato: ratio,
          estado: semaforo(a.acida, [0.7, 1, 1.5]),
        },
        {
          key: 'disponibilidad',
          label: __('Disponibilidad'),
          formula: __('Efectivo / pasivo corriente'),
          formato: ratio,
        },
        {
          key: 'fondo_maniobra',
          label: __('Fondo de maniobra'),
          formula: __('Activo corriente − pasivo corriente'),
          formato: dinero,
        },
        {
          key: 'endeudamiento',
          label: __('Endeudamiento'),
          formula: __('Pasivo exigible / (patrimonio neto + pasivo exigible)'),
          formato: pct,
        },
        {
          key: 'solvencia',
          label: __('Solvencia'),
          formula: __('Activo total / pasivo exigible'),
          formato: ratio,
          estado: semaforo(a.solvencia, [1.1, 1.5, 2.5]),
        },
        {
          key: 'roa',
          label: __('Rentabilidad económica (ROA)'),
          formula: __('Resultado de explotación anualizado / activo total'),
          formato: pct,
        },
        {
          key: 'roe',
          label: __('Rentabilidad financiera (ROE)'),
          formula: __('Resultado anualizado / patrimonio neto'),
          formato: pct,
        },
      ],
    },
    {
      titulo: __('Ciclo de caja'),
      indicadores: [
        {
          key: 'dso',
          label: __('Plazo medio de cobro'),
          formula: __('Clientes / ventas facturadas con IVA × días'),
          formato: dias,
        },
        {
          key: 'dio',
          label: __('Rotación de existencias'),
          formula: __('Existencias / consumos × días'),
          formato: dias,
        },
        {
          key: 'dpo',
          label: __('Plazo medio de pago'),
          formula: __('Proveedores / compras facturadas con IVA × días'),
          formato: dias,
        },
        {
          key: 'ciclo_caja',
          label: __('Ciclo de caja'),
          formula: __('Cobro + existencias − pago'),
          formato: dias,
        },
        {
          key: '_pmp',
          label: __('Periodo medio de pago (ICAC)'),
          formula: __('Límite legal {0} días', pmp.plazo_legal || 60),
          formato: () => dias(pmp.pmp),
          estado:
            pmp.pmp === null || pmp.pmp === undefined
              ? null
              : pmp.pmp > (pmp.plazo_legal || 60)
                ? 'riesgo'
                : 'optimo',
        },
      ],
    },
    {
      titulo: __('Productividad'),
      indicadores: [
        {
          key: 'plantilla',
          label: __('Plantilla media'),
          formula:
            a.plantilla_origen === 'manual'
              ? __('Indicada en la compañía')
              : __('Empleados en alta al cierre de cada mes'),
          formato: numero,
        },
        {
          key: 'ingreso_por_empleado',
          label: __('Ingreso por empleado (periodo)'),
          formula: __('Cifra de negocios / plantilla media'),
          formato: dinero,
        },
        {
          key: 'ingreso_por_empleado_anual',
          label: __('Ingreso por empleado (anual)'),
          formula: __('Anualizado al número de días del periodo'),
          formato: dinero,
        },
        {
          key: 'ebitda_por_empleado',
          label: __('EBITDA por empleado'),
          formula: __('EBITDA / plantilla media'),
          formato: dinero,
        },
        {
          key: 'gastos_personal',
          label: __('Gastos de personal'),
          formula: __('Línea 6 de la PyG'),
          formato: dinero,
        },
      ],
    },
  ]
})

const grafico = computed(() => {
  const a = actual.value
  if (!a.meses) return {}
  const margen = a.serie_cifra.map((c, i) =>
    Math.abs(c) > 0.005 ? a.serie_ebitda[i] / c : null,
  )
  return {
    grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
    legend: leyendaBase({ top: 0 }),
    tooltip: tooltipBase({
      trigger: 'axis',
      formatter: (params) =>
        [
          params[0]?.name,
          ...params.map(
            (p) =>
              `${p.marker}${p.seriesName} <b>${
                p.seriesIndex === 2
                  ? pct(p.value)
                  : formatMoney(p.value, cur.value)
              }</b>`,
          ),
        ].join('<br/>'),
    }),
    xAxis: ejeCategoria(a.meses.map(nombreMes)),
    yAxis: [
      ejeValor(cur.value),
      {
        type: 'value',
        position: 'right',
        splitLine: { show: false },
        axisLabel: { formatter: (v) => formatPct(v, 0) },
      },
    ],
    series: [
      {
        name: __('Cifra de negocios'),
        type: 'bar',
        barMaxWidth: 26,
        itemStyle: { color: COLOR.anterior, borderRadius: 4 },
        data: a.serie_cifra,
      },
      {
        name: __('EBITDA'),
        type: 'bar',
        barMaxWidth: 26,
        data: a.serie_ebitda.map((v) => ({
          value: v,
          itemStyle: {
            color: v >= 0 ? COLOR.total : COLOR.negativo,
            borderRadius: 4,
          },
        })),
      },
      {
        name: __('Margen EBITDA'),
        type: 'line',
        yAxisIndex: 1,
        symbolSize: 6,
        itemStyle: { color: COLOR.positivo },
        data: margen,
      },
    ],
  }
})

function exportar() {
  const d = datos.value
  const filas = []
  for (const grupo of grupos.value) {
    for (const ind of grupo.indicadores) {
      filas.push([
        grupo.titulo,
        ind.label,
        ind.key.startsWith('_')
          ? (d.pmp?.pmp ?? '')
          : (actual.value[ind.key] ?? ''),
        anterior.value && !ind.key.startsWith('_')
          ? (anterior.value[ind.key] ?? '')
          : '',
        ind.formula,
      ])
    }
  }
  descargarCsv(
    `indicadores-${company.value}-${d.from_date}-${d.to_date}`,
    [
      __('Grupo'),
      __('Indicador'),
      etiquetas.value[0],
      etiquetas.value[1] || '',
      __('Fórmula'),
    ],
    filas,
  )
}
</script>
