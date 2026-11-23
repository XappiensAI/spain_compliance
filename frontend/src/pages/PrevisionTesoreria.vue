<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Previsión de tesorería')"
    :seccion="__('Tesorería')"
    :subtitle="subtitulo"
    :companies="companies"
    :fiscal-years="fiscalYears"
    :today="today"
    :loading="report.loading || contexto.loading"
    :error="errorMessage(report.error)"
    :has-data="Boolean(datos)"
    hide-dates
    exportable
    @refresh="load"
    @export="exportar"
  >
    <template #filters>
      <CampoFiltro :label="__('Periodos')">
        <TabButtons v-model="grano" :options="opcionesGrano" />
      </CampoFiltro>
      <CampoFiltro :label="__('Horizonte')">
        <Select v-model="numero" :options="opcionesNumero" class="w-36" />
      </CampoFiltro>
      <CampoFiltro :label="__('Vencidos')">
        <Select v-model="vencidos" :options="opcionesVencidos" class="w-64" />
      </CampoFiltro>
      <CampoFiltro :label="__('Pedidos sin facturar')">
        <Switch v-model="incluirPedidos" />
      </CampoFiltro>
      <CampoFiltro :label="__('Gastos recurrentes')">
        <Switch v-model="incluirRecurrentes" />
      </CampoFiltro>
      <CampoFiltro v-if="incluirRecurrentes" :label="__('Histórico')">
        <Select
          v-model="mesesHistorico"
          :options="opcionesHistorico"
          class="w-36"
        />
      </CampoFiltro>
      <CampoFiltro :label="__('Excluir dudoso cobro')">
        <Switch v-model="excluirDudosos" />
      </CampoFiltro>
      <CampoFiltro :label="__('Saldo mínimo de seguridad')">
        <TextInput v-model="saldoMinimo" type="number" class="w-40" />
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
          :serie="kpi.serie"
          :color="kpi.color"
        />
      </div>

      <Alert
        v-if="alerta"
        :theme="alerta.tema"
        :title="alerta.titulo"
        :description="alerta.texto"
      />

      <Tarjeta
        :titulo="__('Cobros, pagos y saldo previsto')"
        :subtitulo="
          __(
            'Barras: cobros (arriba) y pagos (abajo) por origen. Línea: saldo de tesorería al final de cada periodo.',
          )
        "
      >
        <div class="h-80">
          <EChart :option="grafico" @click="alPulsarGrafico" />
        </div>
      </Tarjeta>

      <section
        class="overflow-auto rounded-xl border border-outline-gray-1 bg-surface-elevation-1"
      >
        <table class="min-w-full border-collapse text-sm">
          <thead class="bg-surface-gray-1 text-ink-gray-6">
            <tr>
              <th
                class="sticky left-0 z-[1] bg-surface-gray-1 px-3 py-2.5 text-left font-medium"
              >
                {{ __('Concepto') }}
              </th>
              <th
                v-for="(p, i) in datos.periodos"
                :key="p.inicio"
                class="cursor-pointer whitespace-nowrap px-3 py-2.5 text-right font-medium hover:text-ink-gray-9"
                :class="
                  seleccion === i ? 'bg-surface-blue-1 text-ink-blue-7' : ''
                "
                :title="`${formatDate(p.inicio)} – ${formatDate(p.fin)}`"
                @click="seleccion = seleccion === i ? null : i"
              >
                {{ p.label }}
              </th>
              <th class="whitespace-nowrap px-3 py-2.5 text-right font-medium">
                {{ __('Total') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="fila in filasPresupuesto"
              :key="fila.key"
              class="border-t border-outline-gray-1"
              :class="fila.clase"
            >
              <td
                class="sticky left-0 z-[1] whitespace-nowrap px-3 py-2"
                :class="fila.celda || 'bg-surface-elevation-1'"
              >
                {{ fila.label }}
              </td>
              <td
                v-for="(valor, i) in fila.valores"
                :key="i"
                class="whitespace-nowrap px-3 py-2 text-right tabular-nums"
                :class="[
                  seleccion === i ? 'bg-surface-blue-1' : '',
                  fila.saldo && valor < minimo
                    ? 'text-ink-red-7 font-semibold'
                    : '',
                ]"
              >
                {{ importe(valor) }}
              </td>
              <td class="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                {{ fila.total === null ? '' : importe(fila.total) }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <TablaInforme
        :titulo="
          seleccion === null
            ? __('Partidas previstas')
            : __('Partidas de {0}', datos.periodos[seleccion].label)
        "
        :subtitulo="
          __(
            'Facturas y pedidos de cada periodo. Pulse un periodo de la tabla o del gráfico para filtrar.',
          )
        "
        :columnas="columnasPartidas"
        :filas="partidasVisibles"
        :currency="datos.currency"
        buscable
        pulsable
        :clase-fila="(f) => (f.sentido === 'pagos' ? 'text-ink-red-7' : '')"
        @fila="(f) => openDesk(f.doctype, f.documento)"
      />

      <div class="grid gap-4 xl:grid-cols-2">
        <Tarjeta
          :titulo="__('Saldo de partida')"
          :subtitulo="
            __('Cuentas de caja y bancos (subgrupo 57 o tipo banco/caja) a hoy')
          "
        >
          <ul class="flex flex-col divide-y divide-outline-gray-1">
            <li
              v-for="cuenta in datos.cuentas"
              :key="cuenta.account"
              class="flex items-center justify-between gap-3 py-2 text-base"
            >
              <span class="truncate">
                <span class="tabular-nums text-ink-gray-5">{{
                  cuenta.numero
                }}</span>
                {{ cuenta.nombre }}
              </span>
              <span
                class="tabular-nums"
                :class="cuenta.saldo < 0 ? 'text-ink-red-7' : ''"
              >
                {{ formatMoney(cuenta.saldo, datos.currency) }}
              </span>
            </li>
            <li v-if="!datos.cuentas.length" class="py-2 text-ink-gray-5">
              {{ __('No hay cuentas de tesorería con saldo') }}
            </li>
          </ul>
        </Tarjeta>
        <Tarjeta
          v-if="datos.recurrentes"
          :titulo="__('Gastos e ingresos recurrentes')"
          :subtitulo="
            __(
              'Media mensual del {0} al {1} de los movimientos de tesorería que no son cobros ni pagos de facturas (nóminas, impuestos, préstamos…), por cuenta de contrapartida.',
              formatDate(datos.recurrentes.desde),
              formatDate(datos.recurrentes.hasta),
            )
          "
        >
          <TablaInforme
            class="-m-4 border-0 sm:-m-5"
            :columnas="columnasRecurrentes"
            :filas="datos.recurrentes.desglose"
            :totales="{
              entradas_mes: datos.recurrentes.entradas_mes,
              salidas_mes: datos.recurrentes.salidas_mes,
            }"
            :currency="datos.currency"
            :vacio="__('Sin movimientos recurrentes en el histórico')"
          />
        </Tarjeta>
      </div>
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import {
  Alert,
  Select,
  Switch,
  TabButtons,
  TextInput,
  createResource,
} from 'frappe-ui'
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
  formatNumber,
  openDesk,
  useInformePeriodo,
} from '@/composables/informe'
import {
  ejeCategoria,
  ejeValor,
  leyendaBase,
  tooltipBase,
} from '@/composables/graficos'
import LucideLandmark from '~icons/lucide/landmark'
import LucideTrendingUp from '~icons/lucide/trending-up'
import LucideTrendingDown from '~icons/lucide/trending-down'
import LucideArrowDownToLine from '~icons/lucide/arrow-down-to-line'
import LucideFlag from '~icons/lucide/flag'

const {
  company,
  fromDate,
  toDate,
  companies,
  fiscalYears,
  today,
  contexto,
  ready,
} = useInformePeriodo()

const grano = ref('week')
const numero = ref('13')
const vencidos = ref('prudente')
const incluirPedidos = ref(true)
const incluirRecurrentes = ref(true)
const mesesHistorico = ref('3')
const excluirDudosos = ref(true)
const saldoMinimo = ref('0')
const seleccion = ref(null)

const opcionesGrano = [
  { label: __('Semanas'), value: 'week' },
  { label: __('Meses'), value: 'month' },
]
const opcionesNumero = computed(() =>
  (grano.value === 'week' ? [4, 8, 13, 26, 52] : [3, 6, 12, 18, 24]).map(
    (n) => ({
      label: grano.value === 'week' ? __('{0} semanas', n) : __('{0} meses', n),
      value: String(n),
    }),
  ),
)
const opcionesVencidos = [
  {
    label: __('Prudente: pagos vencidos ya, cobros vencidos fuera'),
    value: 'prudente',
  },
  { label: __('Todos en el primer periodo'), value: 'todos' },
  { label: __('Ninguno: solo lo que vence desde hoy'), value: 'ninguno' },
]
const opcionesHistorico = [3, 6, 12].map((n) => ({
  label: __('{0} meses', n),
  value: String(n),
}))

watch(grano, (valor) => {
  numero.value = valor === 'week' ? '13' : '6'
})

const report = createResource({
  url: 'spain_compliance.api.finanzas.prevision_tesoreria',
})
const datos = computed(() => report.data || null)

function load() {
  seleccion.value = null
  report.update({
    params: {
      company: company.value,
      grano: grano.value,
      periodos: numero.value,
      incluir_pedidos: incluirPedidos.value ? 1 : 0,
      incluir_recurrentes: incluirRecurrentes.value ? 1 : 0,
      meses_historico: mesesHistorico.value,
      vencidos: vencidos.value,
      excluir_dudosos: excluirDudosos.value ? 1 : 0,
    },
  })
  report.reload()
}

watch(
  [
    company,
    ready,
    numero,
    vencidos,
    incluirPedidos,
    incluirRecurrentes,
    mesesHistorico,
    excluirDudosos,
  ],
  () => {
    if (ready.value && company.value) load()
  },
  { immediate: true },
)

const minimo = computed(() => Number(saldoMinimo.value) || 0)

const subtitulo = computed(() =>
  datos.value ? __('Desde hoy, {0}', formatDate(datos.value.fecha)) : '',
)

const FUENTES = [
  {
    key: 'facturas',
    cobro: __('Cobros de facturas emitidas'),
    pago: __('Pagos de facturas recibidas'),
  },
  {
    key: 'pedidos',
    cobro: __('Cobros de pedidos de venta sin facturar'),
    pago: __('Pagos de pedidos de compra sin facturar'),
  },
  {
    key: 'recurrentes',
    cobro: __('Otros cobros recurrentes (estimación)'),
    pago: __('Otros pagos recurrentes (estimación)'),
  },
]

function suma(valores) {
  return valores.reduce((s, v) => s + (Number(v) || 0), 0)
}

const filasPresupuesto = computed(() => {
  const d = datos.value
  if (!d) return []
  const p = d.periodos
  const filas = [
    {
      key: 'inicial',
      label: __('Saldo inicial'),
      valores: p.map((x) => x.saldo_inicial),
      total: null,
      clase: 'bg-surface-gray-1 font-medium',
      celda: 'bg-surface-gray-1',
    },
  ]
  for (const f of FUENTES) {
    const valores = p.map((x) => x.cobros[f.key])
    if (suma(valores))
      filas.push({
        key: `c-${f.key}`,
        label: `+ ${f.cobro}`,
        valores,
        total: suma(valores),
      })
  }
  filas.push({
    key: 'cobros',
    label: __('Total cobros'),
    valores: p.map((x) => x.total_cobros),
    total: suma(p.map((x) => x.total_cobros)),
    clase: 'font-medium text-ink-green-7',
  })
  for (const f of FUENTES) {
    const valores = p.map((x) => -x.pagos[f.key])
    if (suma(valores))
      filas.push({
        key: `p-${f.key}`,
        label: `− ${f.pago}`,
        valores,
        total: suma(valores),
      })
  }
  filas.push({
    key: 'pagos',
    label: __('Total pagos'),
    valores: p.map((x) => -x.total_pagos),
    total: -suma(p.map((x) => x.total_pagos)),
    clase: 'font-medium text-ink-red-7',
  })
  filas.push({
    key: 'neto',
    label: __('Flujo neto del periodo'),
    valores: p.map((x) => x.neto),
    total: suma(p.map((x) => x.neto)),
    clase: 'font-medium',
  })
  filas.push({
    key: 'final',
    label: __('Saldo final'),
    valores: p.map((x) => x.saldo_final),
    total: null,
    saldo: true,
    clase: 'bg-surface-blue-1 font-semibold',
    celda: 'bg-surface-blue-1',
  })
  return filas
})

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const cur = d.currency
  const final = d.periodos.at(-1)?.saldo_final ?? d.saldo_inicial
  const cobros = suma(d.periodos.map((x) => x.total_cobros))
  const pagos = suma(d.periodos.map((x) => x.total_pagos))
  const minimoPeriodo =
    d.minimo.periodo === null ? null : d.periodos[d.minimo.periodo]
  return [
    {
      key: 'hoy',
      label: __('Saldo de tesorería hoy'),
      valor: formatCompact(d.saldo_inicial, cur),
      titulo: formatMoney(d.saldo_inicial, cur),
      pista: __('{0} cuentas de caja y bancos', d.cuentas.length),
      icono: markRaw(LucideLandmark),
    },
    {
      key: 'cobros',
      label: __('Cobros previstos'),
      valor: formatCompact(cobros, cur),
      titulo: formatMoney(cobros, cur),
      icono: markRaw(LucideTrendingUp),
      serie: d.periodos.map((x) => x.total_cobros),
      color: '#10B981',
    },
    {
      key: 'pagos',
      label: __('Pagos previstos'),
      valor: formatCompact(pagos, cur),
      titulo: formatMoney(pagos, cur),
      icono: markRaw(LucideTrendingDown),
      serie: d.periodos.map((x) => x.total_pagos),
      color: '#F43F5E',
    },
    {
      key: 'minimo',
      label: __('Saldo mínimo previsto'),
      valor: formatCompact(d.minimo.saldo, cur),
      titulo: formatMoney(d.minimo.saldo, cur),
      pista: minimoPeriodo
        ? __('En {0}', minimoPeriodo.label)
        : __('El saldo no baja del actual'),
      icono: markRaw(LucideArrowDownToLine),
    },
    {
      key: 'final',
      label: __('Saldo al final del horizonte'),
      valor: formatCompact(final, cur),
      titulo: formatMoney(final, cur),
      pista: d.periodos.length ? formatDate(d.periodos.at(-1).fin) : '',
      icono: markRaw(LucideFlag),
      serie: d.periodos.map((x) => x.saldo_final),
      color: '#4F46E5',
    },
  ]
})

const alerta = computed(() => {
  const d = datos.value
  if (!d) return null
  const cur = d.currency
  if (d.primer_negativo !== null) {
    const p = d.periodos[d.primer_negativo]
    return {
      tema: 'red',
      titulo: __('Tensión de tesorería en {0}', p.label),
      texto: __(
        'El saldo previsto pasa a ser negativo ({0}) entre el {1} y el {2}.',
        formatMoney(p.saldo_final, cur),
        formatDate(p.inicio),
        formatDate(p.fin),
      ),
    }
  }
  const bajo = d.periodos.findIndex((p) => p.saldo_final < minimo.value)
  if (minimo.value > 0 && bajo >= 0) {
    const p = d.periodos[bajo]
    return {
      tema: 'yellow',
      titulo: __('Por debajo del saldo mínimo en {0}', p.label),
      texto: __('El saldo previsto es {0}.', formatMoney(p.saldo_final, cur)),
    }
  }
  const fuera = d.vencidos.cobros.incluidos ? 0 : d.vencidos.cobros.total
  if (fuera > 0.005) {
    return {
      tema: 'blue',
      titulo: __(
        '{0} de cobros vencidos no entran en la previsión',
        formatMoney(fuera, cur),
      ),
      texto: __(
        'Facturas y pedidos con fecha anterior a hoy que siguen pendientes. Cámbielo en «Vencidos» si espera cobrarlos ya.',
      ),
    }
  }
  return null
})

const COLORES = {
  cobros: { facturas: '#10B981', pedidos: '#6EE7B7', recurrentes: '#A7F3D0' },
  pagos: { facturas: '#F43F5E', pedidos: '#FDA4AF', recurrentes: '#FECDD3' },
}

const grafico = computed(() => {
  const d = datos.value
  if (!d) return {}
  const cur = d.currency
  const series = []
  for (const sentido of ['cobros', 'pagos']) {
    for (const f of FUENTES) {
      const valores = d.periodos.map(
        (x) => (sentido === 'cobros' ? 1 : -1) * x[sentido][f.key],
      )
      if (!suma(valores)) continue
      series.push({
        name: sentido === 'cobros' ? f.cobro : f.pago,
        type: 'bar',
        stack: sentido,
        barMaxWidth: 36,
        itemStyle: { color: COLORES[sentido][f.key] },
        data: valores,
      })
    }
  }
  series.push({
    name: __('Saldo final'),
    type: 'line',
    smooth: true,
    symbolSize: 6,
    yAxisIndex: 1,
    itemStyle: { color: '#4F46E5' },
    lineStyle: { width: 3 },
    data: d.periodos.map((x) => x.saldo_final),
    markLine: minimo.value
      ? {
          symbol: 'none',
          lineStyle: { color: '#F59E0B', type: 'dashed' },
          label: { formatter: __('Mínimo') },
          data: [{ yAxis: minimo.value }],
        }
      : undefined,
  })
  return {
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    legend: leyendaBase({ top: 0 }),
    tooltip: tooltipBase({
      trigger: 'axis',
      valueFormatter: (v) => formatMoney(v, cur),
    }),
    xAxis: ejeCategoria(d.periodos.map((x) => x.label)),
    yAxis: [
      ejeValor(cur),
      ejeValor(cur, { position: 'right', splitLine: { show: false }, scale: true }),
    ],
    series,
  }
})

function alPulsarGrafico(params) {
  if (params?.dataIndex !== undefined) seleccion.value = params.dataIndex
}

const ETIQUETA_FUENTE = {
  facturas: __('Factura'),
  pedidos: __('Pedido'),
}

const columnasPartidas = [
  { key: 'fecha', label: __('Fecha prevista'), tipo: 'fecha' },
  { key: 'periodo_label', label: __('Periodo') },
  { key: 'tipo', label: __('Tipo') },
  { key: 'documento', label: __('Documento') },
  { key: 'tercero', label: __('Tercero') },
  { key: 'importe_signo', label: __('Importe'), tipo: 'moneda' },
]

const partidasVisibles = computed(() => {
  const d = datos.value
  if (!d) return []
  return d.partidas
    .filter((p) => seleccion.value === null || p.periodo === seleccion.value)
    .map((p) => ({
      ...p,
      periodo_label: d.periodos[p.periodo]?.label,
      tipo: `${p.sentido === 'cobros' ? __('Cobro') : __('Pago')} · ${
        ETIQUETA_FUENTE[p.fuente] || p.fuente
      }${p.vencida ? ` · ${__('vencido')}` : ''}`,
      importe_signo: p.sentido === 'cobros' ? p.importe : -p.importe,
    }))
})

const columnasRecurrentes = [
  { key: 'concepto', label: __('Contrapartida') },
  { key: 'entradas_mes', label: __('Entradas / mes'), tipo: 'moneda' },
  { key: 'salidas_mes', label: __('Salidas / mes'), tipo: 'moneda' },
]

function importe(valor) {
  const v = Number(valor) || 0
  if (Math.abs(v) < 0.005) return '—'
  return v < 0 ? `(${formatNumber(-v)})` : formatNumber(v)
}

function exportar() {
  const d = datos.value
  descargarCsv(
    `prevision-tesoreria-${company.value}-${d.fecha}`,
    [__('Concepto'), ...d.periodos.map((p) => p.label), __('Total')],
    filasPresupuesto.value.map((f) => [f.label, ...f.valores, f.total ?? '']),
  )
}
</script>
