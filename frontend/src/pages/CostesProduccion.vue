<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="__('Costes de producción')"
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
      <CampoFiltro :label="__('Artículo fabricado')">
        <TextInput
          v-model="articulo"
          :placeholder="__('Código (opcional)')"
          class="w-48"
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
          :delta="kpi.delta"
          :delta-texto="kpi.deltaTexto"
          menos-es-mejor
        />
      </div>

      <Alert
        v-if="!r.con_real"
        theme="blue"
        :title="__('Ninguna orden del periodo tiene todavía coste real')"
        :description="
          __(
            'El coste real se toma de las entradas de stock de fabricación (y de consumo de material para fabricación) validadas de cada orden. Las órdenes sin ellas se muestran solo con su coste planificado.',
          )
        "
      />

      <div v-if="r.con_real" class="grid gap-4 xl:grid-cols-5">
        <Tarjeta
          class="xl:col-span-2"
          :titulo="__('Estándar frente a real')"
          :subtitulo="
            __(
              'Materias primas, mano de obra y costes indirectos de las órdenes con coste real',
            )
          "
        >
          <div class="h-72">
            <EChart :option="graficoComponentes" />
          </div>
        </Tarjeta>
        <Tarjeta
          class="xl:col-span-3"
          :titulo="__('Productos con más desviación')"
          :subtitulo="__('Real menos estándar sobre la cantidad producida')"
        >
          <div class="h-72">
            <EChart :option="graficoProductos" />
          </div>
        </Tarjeta>
      </div>

      <div v-if="r.con_real" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div
          v-for="dato in desgloseDesviacion"
          :key="dato.label"
          class="rounded-xl border border-outline-gray-1 bg-surface-elevation-1 p-4"
        >
          <div class="text-sm text-ink-gray-5">{{ dato.label }}</div>
          <div
            class="mt-1 text-2xl font-semibold tabular-nums"
            :class="
              dato.valor > 0.005
                ? 'text-ink-red-7'
                : dato.valor < -0.005
                  ? 'text-ink-green-7'
                  : 'text-ink-gray-9'
            "
          >
            {{ formatMoney(dato.valor, datos.currency) }}
          </div>
          <div class="text-xs text-ink-gray-5">{{ dato.pista }}</div>
        </div>
      </div>

      <TablaInforme
        v-if="vista === 'productos'"
        :titulo="__('Coste por producto')"
        :subtitulo="
          __(
            'Coste unitario estándar y real, ponderado por la cantidad producida',
          )
        "
        :columnas="columnasProductos"
        :filas="filasProductos"
        :currency="datos.currency"
        :vacio="__('Ningún producto con coste real en el periodo')"
        buscable
      />
      <TablaInforme
        v-else
        :titulo="__('Órdenes de fabricación')"
        :subtitulo="
          __(
            'Pulse una orden para ver el detalle de materiales con la desviación de cantidad y de precio',
          )
        "
        :columnas="columnasOrdenes"
        :filas="filasOrdenes"
        :currency="datos.currency"
        clave-fila="name"
        :vacio="__('Sin órdenes de fabricación en el periodo')"
        buscable
        pulsable
        @fila="(f) => (ordenAbierta = ordenAbierta?.name === f.name ? null : f)"
      />

      <TablaInforme
        v-if="ordenAbierta"
        :titulo="__('Materiales de {0}', ordenAbierta.name)"
        :subtitulo="`${ordenAbierta.item_code} · ${ordenAbierta.item_name}`"
        :columnas="columnasMateriales"
        :filas="ordenAbierta.materiales"
        :currency="datos.currency"
        :vacio="__('La orden no tiene materiales')"
      >
        <template #acciones>
          <Button
            :label="__('Abrir orden')"
            variant="subtle"
            @click="openDesk('Work Order', ordenAbierta.name)"
          />
          <Button
            :label="__('Cerrar')"
            variant="ghost"
            @click="ordenAbierta = null"
          />
        </template>
      </TablaInforme>

      <Alert
        v-if="datos.limite"
        theme="yellow"
        :title="__('Se muestran solo las primeras órdenes del periodo')"
        :description="
          __('Acote el periodo o filtre por artículo para ver todas.')
        "
      />
      <Avisos
        :avisos="datos.avisos"
        :titulo="__('Puestos de trabajo sin desglose de coste')"
      />
      <p class="text-xs text-ink-gray-5">
        {{
          __(
            'Estándar: materiales y coste de operación que la orden copió de su lista de materiales, escalados a la cantidad producida. MO y CIF se separan con la «Naturaleza del coste» de cada componente de coste del puesto de trabajo.',
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
import Avisos from '@/components/informes/Avisos.vue'
import {
  descargarCsv,
  errorMessage,
  etiquetaRango,
  formatCompact,
  formatMoney,
  openDesk,
  useInformePeriodo,
} from '@/composables/informe'
import {
  ejeCategoria,
  ejeValor,
  leyendaBase,
  tooltipBase,
} from '@/composables/graficos'
import LucideFactory from '~icons/lucide/factory'
import LucideClipboardCheck from '~icons/lucide/clipboard-check'
import LucideCalculator from '~icons/lucide/calculator'
import LucideScale from '~icons/lucide/scale'
import LucideHourglass from '~icons/lucide/hourglass'

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

const articulo = ref('')
const vista = ref('ordenes')
const ordenAbierta = ref(null)
const opcionesVista = [
  { label: __('Órdenes'), value: 'ordenes' },
  { label: __('Productos'), value: 'productos' },
]

const report = createResource({
  url: 'spain_compliance.api.finanzas.costes_de_produccion',
})
const datos = computed(() => report.data || null)
const r = computed(() => datos.value?.resumen || {})

function load() {
  ordenAbierta.value = null
  report.update({
    params: {
      company: company.value,
      from_date: fromDate.value,
      to_date: toDate.value,
      item_code: articulo.value || null,
    },
  })
  report.reload()
}

whenReady(load)

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const cur = d.currency
  const res = d.resumen
  return [
    {
      key: 'ordenes',
      label: __('Órdenes del periodo'),
      valor: String(res.ordenes),
      pista: __(
        '{0} con coste real · {1} solo planificadas',
        res.con_real,
        res.en_curso,
      ),
      icono: markRaw(LucideFactory),
    },
    {
      key: 'estandar',
      label: __('Coste estándar (producido)'),
      valor: formatCompact(res.estandar.total, cur),
      titulo: formatMoney(res.estandar.total, cur),
      icono: markRaw(LucideClipboardCheck),
    },
    {
      key: 'real',
      label: __('Coste real'),
      valor: formatCompact(res.real.total, cur),
      titulo: formatMoney(res.real.total, cur),
      icono: markRaw(LucideCalculator),
    },
    {
      key: 'desviacion',
      label: __('Desviación'),
      valor: formatCompact(res.desviacion.total, cur),
      titulo: formatMoney(res.desviacion.total, cur),
      delta: res.desviacion.pct,
      deltaTexto: __('sobre el estándar'),
      icono: markRaw(LucideScale),
    },
    {
      key: 'en_curso',
      label: __('Planificado en órdenes sin cerrar'),
      valor: formatCompact(res.planificado_en_curso, cur),
      titulo: formatMoney(res.planificado_en_curso, cur),
      pista: __('Coste estándar de la cantidad pendiente de fabricar'),
      icono: markRaw(LucideHourglass),
    },
  ]
})

const COMPONENTES = [
  { key: 'mp', label: __('Materias primas'), color: '#0EA5E9' },
  { key: 'mo', label: __('Mano de obra'), color: '#EC4899' },
  { key: 'cif', label: __('Costes indirectos'), color: '#8B5CF6' },
]

const graficoComponentes = computed(() => {
  const cur = datos.value?.currency
  const res = r.value
  return {
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: leyendaBase({ top: 0 }),
    tooltip: tooltipBase({
      trigger: 'axis',
      valueFormatter: (v) => formatMoney(v, cur),
    }),
    xAxis: ejeCategoria([__('Estándar'), __('Real')]),
    yAxis: ejeValor(cur),
    series: COMPONENTES.map((c) => ({
      name: c.label,
      type: 'bar',
      stack: 'coste',
      barMaxWidth: 64,
      itemStyle: { color: c.color },
      data: [res.estandar?.[c.key] || 0, res.real?.[c.key] || 0],
    })),
  }
})

const graficoProductos = computed(() => {
  const d = datos.value
  if (!d) return {}
  const top = d.productos.slice(0, 12).reverse()
  return {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    tooltip: tooltipBase({
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v) => formatMoney(v, d.currency),
    }),
    xAxis: ejeValor(d.currency),
    yAxis: ejeCategoria(
      top.map((p) => p.item_code),
      { axisLabel: { width: 140, overflow: 'truncate' } },
    ),
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        data: top.map((p) => ({
          value: p.desviacion,
          itemStyle: {
            color: p.desviacion > 0 ? '#F43F5E' : '#10B981',
            borderRadius: 4,
          },
        })),
      },
    ],
  }
})

const desgloseDesviacion = computed(() => {
  const desv = r.value.desviacion || {}
  return [
    {
      label: __('Desviación de materiales por cantidad'),
      valor: desv.mp_cantidad,
      pista: __('Consumo distinto del previsto, a precio estándar'),
    },
    {
      label: __('Desviación de materiales por precio'),
      valor: desv.mp_precio,
      pista: __('Precio de stock distinto del estándar, sobre lo consumido'),
    },
    {
      label: __('Desviación de mano de obra'),
      valor: desv.mo,
      pista: __('Real menos estándar'),
    },
    {
      label: __('Desviación de costes indirectos'),
      valor: desv.cif,
      pista: __('Real menos estándar'),
    },
  ]
})

const columnasOrdenes = [
  { key: 'name', label: __('Orden') },
  { key: 'item_code', label: __('Producto') },
  { key: 'status', label: __('Estado') },
  { key: 'fecha', label: __('Fecha'), tipo: 'fecha' },
  { key: 'qty', label: __('Planificado'), tipo: 'numero' },
  { key: 'producido', label: __('Producido'), tipo: 'numero' },
  { key: 'std_total', label: __('Estándar'), tipo: 'moneda' },
  { key: 'real_total', label: __('Real'), tipo: 'moneda' },
  {
    key: 'desv_total',
    label: __('Desviación'),
    tipo: 'moneda',
    clase: (f) => colorDesv(f.desv_total),
  },
  {
    key: 'desv_pct',
    label: __('%'),
    tipo: 'pct',
    clase: (f) => colorDesv(f.desv_total),
  },
  { key: 'real_unit', label: __('Coste unitario real'), tipo: 'moneda' },
]

const filasOrdenes = computed(() =>
  (datos.value?.ordenes || []).map((o) => ({
    ...o,
    std_total: o.estandar.total,
    real_total: o.real?.total ?? null,
    desv_total: o.desviacion?.total ?? null,
    desv_pct: o.desviacion?.pct ?? null,
    real_unit: o.real?.unitario ?? null,
  })),
)

const columnasProductos = [
  { key: 'item_code', label: __('Producto') },
  { key: 'item_name', label: __('Descripción') },
  { key: 'ordenes', label: __('Órdenes'), tipo: 'entero' },
  { key: 'producido', label: __('Producido'), tipo: 'numero' },
  { key: 'std_unit', label: __('Unitario estándar'), tipo: 'moneda' },
  { key: 'real_mp', label: __('MP real / ud.'), tipo: 'moneda' },
  { key: 'real_mo', label: __('MO real / ud.'), tipo: 'moneda' },
  { key: 'real_cif', label: __('CIF real / ud.'), tipo: 'moneda' },
  { key: 'real_unit', label: __('Unitario real'), tipo: 'moneda' },
  {
    key: 'desviacion',
    label: __('Desviación total'),
    tipo: 'moneda',
    clase: (f) => colorDesv(f.desviacion),
  },
  {
    key: 'desviacion_pct',
    label: __('%'),
    tipo: 'pct',
    clase: (f) => colorDesv(f.desviacion),
  },
]

const filasProductos = computed(() =>
  (datos.value?.productos || []).map((p) => {
    const por = (v) => (p.producido ? v / p.producido : null)
    return {
      ...p,
      std_unit: p.estandar.unitario,
      real_unit: p.real.unitario,
      real_mp: por(p.real.mp),
      real_mo: por(p.real.mo),
      real_cif: por(p.real.cif),
    }
  }),
)

const columnasMateriales = [
  { key: 'item_code', label: __('Material') },
  { key: 'item_name', label: __('Descripción') },
  { key: 'qty_std', label: __('Cant. estándar'), tipo: 'numero', decimales: 3 },
  { key: 'qty_real', label: __('Cant. real'), tipo: 'numero', decimales: 3 },
  { key: 'precio_std', label: __('Precio estándar'), tipo: 'moneda' },
  { key: 'precio_real', label: __('Precio real'), tipo: 'moneda' },
  { key: 'importe_std', label: __('Importe estándar'), tipo: 'moneda' },
  { key: 'importe_real', label: __('Importe real'), tipo: 'moneda' },
  {
    key: 'desv_cantidad',
    label: __('Desv. cantidad'),
    tipo: 'moneda',
    clase: (f) => colorDesv(f.desv_cantidad),
  },
  {
    key: 'desv_precio',
    label: __('Desv. precio'),
    tipo: 'moneda',
    clase: (f) => colorDesv(f.desv_precio),
  },
]

function colorDesv(valor) {
  if (valor === null || valor === undefined || Math.abs(valor) < 0.005)
    return ''
  return valor > 0 ? 'text-ink-red-7' : 'text-ink-green-7'
}

function exportar() {
  const d = datos.value
  const cabeceras = [
    __('Orden'),
    __('Producto'),
    __('Estado'),
    __('Producido'),
    __('MP estándar'),
    __('MO estándar'),
    __('CIF estándar'),
    __('Total estándar'),
    __('MP real'),
    __('MO real'),
    __('CIF real'),
    __('Total real'),
    __('Desviación'),
    __('Desv. cantidad MP'),
    __('Desv. precio MP'),
  ]
  descargarCsv(
    `costes-produccion-${company.value}-${d.from_date}-${d.to_date}`,
    cabeceras,
    d.ordenes.map((o) => [
      o.name,
      o.item_code,
      o.status,
      o.producido,
      o.estandar.mp,
      o.estandar.mo,
      o.estandar.cif,
      o.estandar.total,
      o.real?.mp ?? '',
      o.real?.mo ?? '',
      o.real?.cif ?? '',
      o.real?.total ?? '',
      o.desviacion?.total ?? '',
      o.desviacion?.mp_cantidad ?? '',
      o.desviacion?.mp_precio ?? '',
    ]),
  )
}
</script>
