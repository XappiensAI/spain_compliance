<template>
  <section
    class="flex min-w-0 flex-col rounded-xl border border-outline-gray-1 bg-surface-elevation-1 print:break-inside-avoid"
  >
    <header
      v-if="titulo || $slots.acciones"
      class="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 sm:px-5"
    >
      <div class="min-w-0">
        <h3 class="text-xl font-semibold text-ink-gray-9">{{ titulo }}</h3>
        <p v-if="subtitulo" class="mt-1 text-sm text-ink-gray-5">
          {{ subtitulo }}
        </p>
      </div>
      <div class="flex items-center gap-2 print:hidden">
        <TextInput
          v-if="buscable"
          v-model="texto"
          type="search"
          :placeholder="__('Buscar…')"
          class="w-56"
        />
        <slot name="acciones" />
      </div>
    </header>
    <div class="mt-3 overflow-auto">
      <table class="min-w-full border-collapse text-base">
        <thead class="sticky top-0 z-[2] bg-surface-gray-1 text-ink-gray-6">
          <tr>
            <th
              v-for="col in columnas"
              :key="col.key"
              class="whitespace-nowrap px-3 py-2.5 text-sm font-medium"
              :class="[alinear(col), col.ancho || '']"
            >
              <button
                v-if="ordenable"
                type="button"
                class="inline-flex items-center gap-1 hover:text-ink-gray-9"
                @click="ordenarPor(col.key)"
              >
                {{ col.label }}
                <span v-if="orden.key === col.key" class="text-xs">{{
                  orden.asc ? '▲' : '▼'
                }}</span>
              </button>
              <template v-else>{{ col.label }}</template>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(fila, i) in pagina"
            :key="claveFila ? fila[claveFila] : i"
            class="border-t border-outline-gray-1"
            :class="[
              pulsable ? 'cursor-pointer hover:bg-surface-gray-1' : '',
              claseFila ? claseFila(fila) : '',
            ]"
            @click="pulsable && $emit('fila', fila)"
          >
            <td
              v-for="col in columnas"
              :key="col.key"
              class="px-3 py-2"
              :class="[
                alinear(col),
                col.tipo && col.tipo !== 'texto'
                  ? 'whitespace-nowrap tabular-nums'
                  : 'max-w-xs truncate',
                col.clase ? col.clase(fila) : '',
              ]"
              :title="col.tipo === 'texto' || !col.tipo ? valor(fila, col) : ''"
            >
              <slot
                :name="`celda-${col.key}`"
                :fila="fila"
                :valor="fila[col.key]"
              >
                {{ formatear(fila, col) }}
              </slot>
            </td>
          </tr>
          <tr v-if="!filtradas.length">
            <td
              :colspan="columnas.length"
              class="px-4 py-10 text-center text-base text-ink-gray-5"
            >
              {{ vacio || __('Sin datos') }}
            </td>
          </tr>
        </tbody>
        <tfoot v-if="totales && filtradas.length">
          <tr
            class="border-t-2 border-outline-gray-3 bg-surface-gray-2 font-semibold text-ink-gray-9"
          >
            <td
              v-for="(col, i) in columnas"
              :key="col.key"
              class="whitespace-nowrap px-3 py-2.5 tabular-nums"
              :class="alinear(col)"
            >
              <template v-if="i === 0">{{ __('Total') }}</template>
              <template v-else-if="totales[col.key] !== undefined">
                {{ formatear(totales, col) }}
              </template>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
    <div
      v-if="filtradas.length > limite"
      class="flex items-center justify-between gap-2 border-t border-outline-gray-1 px-4 py-2 text-sm text-ink-gray-6 print:hidden"
    >
      <span>{{
        __('Se muestran {0} de {1} filas', pagina.length, filtradas.length)
      }}</span>
      <Button
        v-if="pagina.length < filtradas.length"
        :label="__('Mostrar más')"
        variant="ghost"
        @click="visibles += limite"
      />
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button, TextInput } from 'frappe-ui'
import {
  formatDate,
  formatMoney,
  formatNumber,
  formatPct,
} from '@/composables/informe'

const props = defineProps({
  titulo: { type: String, default: '' },
  subtitulo: { type: String, default: '' },
  columnas: { type: Array, required: true },
  filas: { type: Array, default: () => [] },
  totales: { type: Object, default: null },
  currency: { type: String, default: 'EUR' },
  claveFila: { type: String, default: '' },
  pulsable: { type: Boolean, default: false },
  buscable: { type: Boolean, default: false },
  ordenable: { type: Boolean, default: true },
  limite: { type: Number, default: 100 },
  vacio: { type: String, default: '' },
  claseFila: { type: Function, default: null },
})

defineEmits(['fila'])

const texto = ref('')
const visibles = ref(props.limite)
const orden = ref({ key: '', asc: false })

watch(
  () => [props.filas, texto.value],
  () => {
    visibles.value = props.limite
  },
)

function alinear(col) {
  if (col.alinear) return `text-${col.alinear}`
  return col.tipo && !['texto', 'fecha'].includes(col.tipo)
    ? 'text-right'
    : 'text-left'
}

function valor(fila, col) {
  const v = col.valor ? col.valor(fila) : fila[col.key]
  return v === null || v === undefined ? '' : String(v)
}

function formatear(fila, col) {
  const v = col.valor ? col.valor(fila) : fila[col.key]
  if (v === null || v === undefined || v === '') return col.tipo ? '—' : ''
  switch (col.tipo) {
    case 'moneda':
      return Math.abs(Number(v)) < 0.005 ? '—' : formatMoney(v, props.currency)
    case 'numero':
      return formatNumber(v, col.decimales ?? 2)
    case 'entero':
      return formatNumber(v, 0)
    case 'pct':
      return formatPct(v)
    case 'fecha':
      return formatDate(v)
    case 'dias':
      return `${formatNumber(v, 0)} ${__('d')}`
    default:
      return String(v)
  }
}

const filtradas = computed(() => {
  let filas = props.filas || []
  const q = texto.value.trim().toLowerCase()
  if (q) {
    filas = filas.filter((fila) =>
      props.columnas.some((col) => valor(fila, col).toLowerCase().includes(q)),
    )
  }
  if (orden.value.key) {
    const col = props.columnas.find((c) => c.key === orden.value.key)
    const signo = orden.value.asc ? 1 : -1
    filas = [...filas].sort((a, b) => {
      const va = col?.valor ? col.valor(a) : a[orden.value.key]
      const vb = col?.valor ? col.valor(b) : b[orden.value.key]
      if (typeof va === 'number' || typeof vb === 'number')
        return signo * ((Number(va) || 0) - (Number(vb) || 0))
      return signo * String(va ?? '').localeCompare(String(vb ?? ''))
    })
  }
  return filas
})

const pagina = computed(() => filtradas.value.slice(0, visibles.value))

function ordenarPor(key) {
  if (orden.value.key === key) {
    if (!orden.value.asc) orden.value = { key, asc: true }
    else orden.value = { key: '', asc: false }
  } else {
    orden.value = { key, asc: false }
  }
}
</script>
