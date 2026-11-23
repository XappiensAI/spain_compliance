<template>
  <div :class="enLinea ? 'flex items-center gap-3' : 'flex flex-col gap-1.5'">
    <div
      v-if="mostrarEtiqueta"
      class="flex items-center gap-1 text-xs text-ink-gray-5"
      :class="enLinea ? 'w-2/5 shrink-0' : ''"
    >
      <span class="truncate">{{ etiquetaFinal }}</span>
      <span v-if="campo.reqd && editable" class="text-ink-red-4">*</span>
      <Tooltip v-if="campo.description" :text="campo.description">
        <LucideInfo class="size-3 shrink-0 text-ink-gray-4" />
      </Tooltip>
    </div>

    <div class="min-w-0 flex-1">
      <!-- Solo lectura -->
      <div
        v-if="!editable"
        class="min-h-7 truncate py-1 text-base"
        :class="[vacio ? 'text-ink-gray-4' : 'text-ink-gray-8', numerico ? 'tabular-nums' : '']"
        :title="textoLectura"
      >
        {{ textoLectura }}
      </div>

      <CampoLink
        v-else-if="campo.fieldtype === 'Link'"
        :model-value="modelValue || ''"
        :doctype="campo.options"
        :filters="filters"
        :query="query"
        :etiqueta="etiquetaValor"
        :placeholder="placeholder"
        :variant="variant"
        @update:model-value="emitir"
      />

      <Select
        v-else-if="campo.fieldtype === 'Select'"
        :model-value="modelValue ?? ''"
        :options="opcionesSelect"
        :variant="variant"
        size="sm"
        class="w-full"
        @update:model-value="emitir"
      />

      <div v-else-if="campo.fieldtype === 'Check'" class="flex h-7 items-center">
        <Checkbox
          :model-value="Boolean(modelValue)"
          size="sm"
          @update:model-value="(v) => emitir(v ? 1 : 0)"
        />
      </div>

      <DatePicker
        v-else-if="campo.fieldtype === 'Date'"
        :model-value="modelValue || ''"
        :variant="variant"
        format="DD/MM/YYYY"
        size="sm"
        @update:model-value="emitir"
      />

      <Textarea
        v-else-if="textoLargo"
        :model-value="esHtml ? htmlATexto(modelValue) : modelValue || ''"
        :variant="variant"
        :rows="filas"
        size="sm"
        @update:model-value="(v) => emitir(esHtml ? textoAHtml(v) : v)"
      />

      <TextInput
        v-else-if="numerico"
        type="number"
        :model-value="modelValue ?? ''"
        :variant="variant"
        size="sm"
        class="tabular-nums"
        :step="campo.fieldtype === 'Int' ? 1 : 'any'"
        @update:model-value="emitirNumero"
      >
        <template v-if="sufijo" #suffix>
          <span class="text-xs text-ink-gray-5">{{ sufijo }}</span>
        </template>
      </TextInput>

      <TextInput
        v-else
        :type="campo.fieldtype === 'Time' ? 'time' : 'text'"
        :model-value="modelValue ?? ''"
        :variant="variant"
        :placeholder="placeholder"
        size="sm"
        @update:model-value="emitir"
      />
    </div>
  </div>
</template>

<script setup>
/**
 * Un campo de DocType pintado según su `fieldtype` del meta.
 * Sirve para los campos curados de la vista y para los personalizados de cada instalación.
 */
import { computed } from 'vue'
import {
  Checkbox,
  DatePicker,
  Select,
  TextInput,
  Textarea,
  Tooltip,
  dayjs,
} from 'frappe-ui'
import CampoLink from '@/components/factura/CampoLink.vue'
import { htmlATexto, textoAHtml } from '@/composables/factura'
import { formatNumber } from '@/composables/informe'
import LucideInfo from '~icons/lucide/info'

const props = defineProps({
  df: { type: Object, required: true },
  modelValue: { type: [String, Number, Boolean, null], default: null },
  editable: { type: Boolean, default: false },
  label: { type: String, default: '' },
  hideLabel: { type: Boolean, default: false },
  enLinea: { type: Boolean, default: false },
  filters: { type: [Object, Array], default: null },
  query: { type: String, default: null },
  etiquetaValor: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  variant: { type: String, default: 'subtle' },
  filas: { type: Number, default: 3 },
  sufijo: { type: String, default: '' },
  moneda: { type: String, default: 'EUR' },
})

const emit = defineEmits(['update:modelValue'])

const campo = computed(() => props.df || {})
const etiquetaFinal = computed(() => props.label || campo.value.label)
const mostrarEtiqueta = computed(() => !props.hideLabel && etiquetaFinal.value)

const NUMERICOS = new Set(['Int', 'Float', 'Currency', 'Percent'])
const LARGOS = new Set(['Small Text', 'Text', 'Long Text', 'Text Editor', 'Code', 'Markdown Editor'])

const numerico = computed(() => NUMERICOS.has(campo.value.fieldtype))
const textoLargo = computed(() => LARGOS.has(campo.value.fieldtype))
const esHtml = computed(() => campo.value.fieldtype === 'Text Editor')

const vacio = computed(
  () => props.modelValue === null || props.modelValue === undefined || props.modelValue === '',
)

const opcionesSelect = computed(() =>
  String(campo.value.options || '')
    .split('\n')
    .map((o) => ({ label: o ? __(o) : '—', value: o })),
)

const textoLectura = computed(() => {
  const v = props.modelValue
  const t = campo.value.fieldtype
  if (t === 'Check') return v ? __('Sí') : __('No')
  if (vacio.value) return '—'
  if (t === 'Date') return dayjs(v).format('DD/MM/YYYY')
  if (t === 'Currency') return `${formatNumber(v, 2)} ${props.moneda === 'EUR' ? '€' : props.moneda}`
  if (t === 'Percent') return `${formatNumber(v, 2)} %`
  if (t === 'Float') return formatNumber(v, Number.isInteger(Number(v)) ? 0 : 3)
  if (t === 'Link' && props.etiquetaValor) return `${props.etiquetaValor}`
  if (t === 'Select') return __(v)
  return esHtml.value ? htmlATexto(v) : String(v)
})

function emitir(v) {
  emit('update:modelValue', v)
}

function emitirNumero(v) {
  if (v === '' || v === null) return emit('update:modelValue', 0)
  const n = Number(v)
  if (!Number.isNaN(n)) emit('update:modelValue', n)
}
</script>
