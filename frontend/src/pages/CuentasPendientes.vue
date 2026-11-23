<template>
  <ReportFrame
    v-model:company="company"
    v-model:from-date="fromDate"
    v-model:to-date="toDate"
    :title="esCobro ? __('Cuentas a cobrar') : __('Cuentas a pagar')"
    :seccion="__('Tesorería')"
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
      <CampoFiltro :label="__('Tramos de antigüedad (días)')">
        <TextInput v-model="rangos" class="w-44" @keyup.enter="load" />
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

      <div class="grid gap-4 xl:grid-cols-5">
        <Tarjeta
          :class="esCobro ? 'xl:col-span-5' : 'xl:col-span-2'"
          :titulo="__('Antigüedad del saldo')"
          :subtitulo="__('Pendiente por días desde el vencimiento')"
        >
          <div class="h-64">
            <EChart :option="graficoTramos" />
          </div>
        </Tarjeta>
        <Tarjeta
          v-if="!esCobro"
          class="xl:col-span-3"
          :titulo="__('Programación de pagos')"
          :subtitulo="
            __(
              'Vencimientos por semana según los plazos de cada factura. Lo vencido se muestra aparte.',
            )
          "
        >
          <div class="h-64">
            <EChart :option="graficoCalendario" />
          </div>
        </Tarjeta>
      </div>

      <Alert
        v-if="datos.otros_terceros"
        theme="blue"
        :title="
          __(
            'Además hay {0} pendientes con otros terceros (empleados, socios…), que no se detallan.',
            formatMoney(datos.otros_terceros, datos.currency),
          )
        "
      />

      <TablaInforme
        v-if="vista === 'terceros'"
        :titulo="esCobro ? __('Por cliente') : __('Por proveedor')"
        :columnas="columnasTerceros"
        :filas="filasTerceros"
        :totales="totalesTerceros"
        :currency="datos.currency"
        clave-fila="party"
        buscable
        pulsable
        @fila="
          (fila) => openDesk(esCobro ? 'Customer' : 'Supplier', fila.party)
        "
      />
      <TablaInforme
        v-else-if="vista === 'documentos'"
        :titulo="__('Documentos pendientes')"
        :subtitulo="
          datos.documentos_total > datos.documentos.length
            ? __(
                'Los {0} documentos más antiguos de {1}',
                datos.documentos.length,
                datos.documentos_total,
              )
            : ''
        "
        :columnas="columnasDocumentos"
        :filas="datos.documentos"
        :currency="datos.currency"
        clave-fila="voucher_no"
        buscable
        pulsable
        :clase-fila="
          (f) =>
            f.estado === 'Dudoso Cobro' || f.estado === 'Pérdida'
              ? 'text-ink-amber-7'
              : ''
        "
        @fila="(fila) => openDesk(fila.voucher_type, fila.voucher_no)"
      />
      <TablaInforme
        v-else
        :titulo="__('Calendario de vencimientos')"
        :subtitulo="__('Un renglón por plazo de pago abierto')"
        :columnas="columnasPlazos"
        :filas="datos.plazos"
        :currency="datos.currency"
        buscable
        pulsable
        @fila="(fila) => openDesk(fila.doctype, fila.documento)"
      />

      <Tarjeta
        v-if="!esCobro && datos.pmp"
        :titulo="__('Periodo medio de pago a proveedores')"
        :subtitulo="
          __(
            'Resolución del ICAC de 29 de enero de 2016, del {0} al {1}. Se informa en la memoria de las cuentas anuales.',
            formatDate(datos.pmp.desde),
            formatDate(datos.pmp.hasta),
          )
        "
      >
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div v-for="dato in datosPmp" :key="dato.label">
            <div class="text-sm text-ink-gray-5">{{ dato.label }}</div>
            <div
              class="mt-1 text-2xl font-semibold tabular-nums"
              :class="dato.clase || 'text-ink-gray-9'"
            >
              {{ dato.valor }}
            </div>
            <div v-if="dato.pista" class="text-xs text-ink-gray-5">
              {{ dato.pista }}
            </div>
          </div>
        </div>
        <p class="mt-4 text-xs text-ink-gray-5">
          {{
            __(
              'Los días se cuentan desde la fecha de la factura del proveedor (o de contabilización si no la tiene) porque ERPNext no guarda la fecha de recepción de la mercancía en la factura.',
            )
          }}
        </p>
      </Tarjeta>
    </template>
  </ReportFrame>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { Alert, TabButtons, TextInput, createResource } from 'frappe-ui'
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
  formatPct,
  openDesk,
  useInformePeriodo,
} from '@/composables/informe'
import { ejeCategoria, ejeValor, tooltipBase } from '@/composables/graficos'
import LucideWallet from '~icons/lucide/wallet'
import LucideClock from '~icons/lucide/clock'
import LucideAlertTriangle from '~icons/lucide/triangle-alert'
import LucideCalendarCheck from '~icons/lucide/calendar-check'
import LucideTimer from '~icons/lucide/timer'

const props = defineProps({
  tipo: { type: String, default: 'cobrar' },
})

const esCobro = computed(() => props.tipo === 'cobrar')
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

const rangos = ref('30, 60, 90, 120')
const vista = ref('terceros')
const opcionesVista = computed(() => [
  {
    label: esCobro.value ? __('Clientes') : __('Proveedores'),
    value: 'terceros',
  },
  { label: __('Documentos'), value: 'documentos' },
  ...(esCobro.value ? [] : [{ label: __('Vencimientos'), value: 'plazos' }]),
])

const recursos = {
  cobrar: createResource({
    url: 'spain_compliance.api.finanzas.cuentas_a_cobrar',
  }),
  pagar: createResource({
    url: 'spain_compliance.api.finanzas.cuentas_a_pagar',
  }),
}
const report = computed(() => recursos[props.tipo] || recursos.cobrar)
const datos = computed(() => report.value.data || null)

function load() {
  report.value.update({
    params: {
      company: company.value,
      to_date: toDate.value,
      rangos: rangos.value,
    },
  })
  report.value.reload()
}

whenReady(load)
watch(
  () => props.tipo,
  () => {
    vista.value = 'terceros'
    if (company.value && toDate.value) load()
  },
)

const subtitulo = computed(() =>
  datos.value ? __('Saldos a {0}', formatDate(datos.value.fecha)) : '',
)

const tramos = computed(() => {
  const d = datos.value
  if (!d) return []
  return [
    { label: __('No vencido'), valor: d.resumen.no_vencido, color: '#10B981' },
    ...d.etiquetas.map((label, i) => ({
      label,
      valor: d.resumen.tramos[i],
      color: [
        '#FBBF24',
        '#F59E0B',
        '#F97316',
        '#EF4444',
        '#B91C1C',
        '#7F1D1D',
        '#450A0A',
        '#000',
      ][i],
    })),
  ]
})

const kpis = computed(() => {
  const d = datos.value
  if (!d) return []
  const r = d.resumen
  const masDe90 = d.rangos.reduce(
    (suma, limite, i) => (limite >= 90 ? suma + (r.tramos[i + 1] || 0) : suma),
    0,
  )
  const cur = d.currency
  const lista = [
    {
      key: 'total',
      label: esCobro.value ? __('Pendiente de cobro') : __('Pendiente de pago'),
      valor: formatCompact(r.total, cur),
      titulo: formatMoney(r.total, cur),
      pista: __('{0} documentos', r.documentos),
      icono: markRaw(LucideWallet),
    },
    {
      key: 'no_vencido',
      label: __('No vencido'),
      valor: formatCompact(r.no_vencido, cur),
      titulo: formatMoney(r.no_vencido, cur),
      pista: r.sin_aplicar
        ? __(
            'Anticipos y abonos sin aplicar: {0}',
            formatMoney(r.sin_aplicar, cur),
          )
        : '',
      icono: markRaw(LucideCalendarCheck),
    },
    {
      key: 'vencido',
      label: __('Vencido'),
      valor: formatCompact(r.vencido, cur),
      titulo: formatMoney(r.vencido, cur),
      pista: r.total
        ? __('{0} del pendiente', formatPct(r.vencido / r.total))
        : '',
      icono: markRaw(LucideClock),
    },
    {
      key: 'mas90',
      label: __('Vencido hace más de 90 días'),
      valor: formatCompact(masDe90, cur),
      titulo: formatMoney(masDe90, cur),
      pista: r.total
        ? __('{0} del pendiente', formatPct(masDe90 / r.total))
        : '',
      icono: markRaw(LucideAlertTriangle),
    },
  ]
  if (esCobro.value) {
    lista.push({
      key: 'dudoso',
      label: __('Dudoso cobro y pérdidas'),
      valor: formatCompact(r.dudoso + r.perdida, cur),
      titulo: formatMoney(r.dudoso + r.perdida, cur),
      pista: __('Facturas marcadas con esos estados'),
      icono: markRaw(LucideAlertTriangle),
    })
  } else if (d.pmp) {
    lista.push({
      key: 'pmp',
      label: __('Periodo medio de pago'),
      valor:
        d.pmp.pmp === null
          ? '—'
          : `${formatNumber(d.pmp.pmp, 1)} ${__('días')}`,
      pista: __('Máximo legal {0} días (Ley 15/2010)', d.pmp.plazo_legal),
      icono: markRaw(LucideTimer),
    })
  }
  return lista
})

const graficoTramos = computed(() => {
  const cur = datos.value?.currency
  return {
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: tooltipBase({
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v) => formatMoney(v, cur),
    }),
    xAxis: ejeCategoria(tramos.value.map((t) => t.label)),
    yAxis: ejeValor(cur),
    series: [
      {
        type: 'bar',
        barMaxWidth: 48,
        data: tramos.value.map((t) => ({
          value: Math.round(t.valor * 100) / 100,
          itemStyle: { color: t.color, borderRadius: [6, 6, 0, 0] },
        })),
      },
    ],
  }
})

const graficoCalendario = computed(() => {
  const d = datos.value
  if (!d?.calendario) return {}
  const cur = d.currency
  const etiquetas = [
    __('Vencido'),
    ...d.calendario.map((c) => c.label),
    __('Después'),
  ]
  const valores = [
    d.vencido.importe,
    ...d.calendario.map((c) => c.importe),
    d.posterior.importe,
  ]
  return {
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: tooltipBase({
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v) => formatMoney(v, cur),
    }),
    xAxis: ejeCategoria(etiquetas, { axisLabel: { rotate: 45, fontSize: 10 } }),
    yAxis: ejeValor(cur),
    series: [
      {
        type: 'bar',
        barMaxWidth: 32,
        data: valores.map((v, i) => ({
          value: v,
          itemStyle: {
            color:
              i === 0
                ? '#EF4444'
                : i === valores.length - 1
                  ? '#94A3B8'
                  : '#F59E0B',
            borderRadius: [4, 4, 0, 0],
          },
        })),
      },
    ],
  }
})

const columnasTramos = computed(() => {
  const d = datos.value
  if (!d) return []
  return [
    { key: 'no_vencido', label: __('No vencido'), tipo: 'moneda' },
    ...d.etiquetas.map((label, i) => ({
      key: `tramo_${i}`,
      label,
      tipo: 'moneda',
    })),
  ]
})

const columnasTerceros = computed(() => [
  { key: 'nombre', label: esCobro.value ? __('Cliente') : __('Proveedor') },
  { key: 'documentos', label: __('Docs.'), tipo: 'entero' },
  { key: 'total', label: __('Pendiente'), tipo: 'moneda' },
  ...columnasTramos.value,
  { key: 'sin_aplicar', label: __('Sin aplicar'), tipo: 'moneda' },
  { key: 'dias_max', label: __('Máx. días vencido'), tipo: 'dias' },
])

const filasTerceros = computed(() =>
  (datos.value?.terceros || []).map((t) => ({
    ...t,
    ...Object.fromEntries(t.tramos.map((v, i) => [`tramo_${i}`, v])),
  })),
)

const totalesTerceros = computed(() => {
  const r = datos.value?.resumen
  if (!r) return null
  return {
    documentos: r.documentos,
    total: r.total,
    no_vencido: r.no_vencido,
    sin_aplicar: r.sin_aplicar,
    ...Object.fromEntries(r.tramos.map((v, i) => [`tramo_${i}`, v])),
  }
})

const columnasDocumentos = computed(() => [
  { key: 'voucher_no', label: __('Documento') },
  { key: 'nombre', label: esCobro.value ? __('Cliente') : __('Proveedor') },
  { key: 'fecha', label: __('Fecha'), tipo: 'fecha' },
  { key: 'vencimiento', label: __('Vencimiento'), tipo: 'fecha' },
  { key: 'dias', label: __('Días vencido'), tipo: 'entero' },
  { key: 'importe', label: __('Importe'), tipo: 'moneda' },
  { key: 'pendiente', label: __('Pendiente'), tipo: 'moneda' },
  { key: 'estado', label: __('Estado') },
])

const columnasPlazos = computed(() => [
  { key: 'fecha', label: __('Vence'), tipo: 'fecha' },
  { key: 'documento', label: __('Documento') },
  { key: 'tercero', label: __('Proveedor') },
  { key: 'importe', label: __('Importe'), tipo: 'moneda' },
])

const datosPmp = computed(() => {
  const p = datos.value?.pmp
  if (!p) return []
  const cur = datos.value.currency
  const dias = (v) => (v === null ? '—' : `${formatNumber(v, 1)} ${__('días')}`)
  return [
    {
      label: __('Periodo medio de pago'),
      valor: dias(p.pmp),
      clase:
        p.pmp !== null && p.pmp > p.plazo_legal
          ? 'text-ink-red-7'
          : 'text-ink-green-7',
      pista: __('Máximo legal {0} días', p.plazo_legal),
    },
    {
      label: __('Ratio de operaciones pagadas'),
      valor: dias(p.ratio_pagadas),
      pista: __(
        '{0} pagados en {1} pagos',
        formatMoney(p.pagado, cur),
        p.pagos,
      ),
    },
    {
      label: __('Ratio de operaciones pendientes'),
      valor: dias(p.ratio_pendientes),
      pista: __('{0} pendientes al cierre', formatMoney(p.pendiente, cur)),
    },
    {
      label: __('Pagado dentro del plazo legal'),
      valor: p.pagado ? formatPct(p.pagado_en_plazo / p.pagado) : '—',
      pista: __(
        '{0} de {1} pagos; pendiente fuera de plazo {2}',
        p.pagos_en_plazo,
        p.pagos,
        formatMoney(p.pendiente_fuera_plazo, cur),
      ),
    },
  ]
})

function exportar() {
  const d = datos.value
  const nombre = `${esCobro.value ? 'cuentas-a-cobrar' : 'cuentas-a-pagar'}-${company.value}-${
    d.fecha
  }`
  if (vista.value === 'documentos') {
    descargarCsv(
      nombre,
      columnasDocumentos.value.map((c) => c.label),
      d.documentos.map((f) => columnasDocumentos.value.map((c) => f[c.key])),
    )
    return
  }
  if (vista.value === 'plazos') {
    descargarCsv(
      nombre,
      columnasPlazos.value.map((c) => c.label),
      d.plazos.map((f) => columnasPlazos.value.map((c) => f[c.key])),
    )
    return
  }
  descargarCsv(
    nombre,
    columnasTerceros.value.map((c) => c.label),
    filasTerceros.value.map((f) => columnasTerceros.value.map((c) => f[c.key])),
  )
}
</script>
