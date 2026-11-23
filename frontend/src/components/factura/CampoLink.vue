<template>
  <Combobox
    v-model="seleccion"
    v-model:query="consulta"
    :options="opciones"
    :loading="cargando"
    :filterable="false"
    :disabled="disabled"
    :placeholder="placeholder || __('Buscar…')"
    :empty-text="__('Sin resultados')"
    :variant="variant"
    size="sm"
    trigger="button"
    class="w-full"
    @update:query="buscarConRetardo"
    @update:open="alAbrir"
  >
    <template #item-label="{ item }">
      <div class="flex min-w-0 flex-col">
        <span class="truncate">{{ item.etiqueta || item.label }}</span>
        <span
          v-if="item.description && item.description !== item.label"
          class="truncate text-xs text-ink-gray-5"
          >{{ item.description }}</span
        >
      </div>
    </template>
  </Combobox>
</template>

<script setup>
/**
 * Campo de enlace con búsqueda en el servidor (`frappe.desk.search.search_link`).
 * Respeta `filters` y la `query` de ERPNext (artículos, clientes, cuentas…).
 */
import { computed, inject, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { Combobox, call } from 'frappe-ui'

const VACIO = '__vacio__'

const modelo = defineModel({ type: String, default: '' })

const props = defineProps({
  doctype: { type: String, required: true },
  filters: { type: [Object, Array], default: null },
  query: { type: String, default: null },
  // Por defecto, el DocType de la factura abierta (lo da Factura.vue con provide).
  referenceDoctype: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  variant: { type: String, default: 'subtle' },
  // Texto que se enseña para el valor actual (p. ej. el nombre del cliente).
  etiqueta: { type: String, default: '' },
  permitirVacio: { type: Boolean, default: true },
})

const doctypeFactura = inject('doctypeFactura', 'Sales Invoice')

const consulta = ref('')
const resultados = ref([])
const cargando = ref(false)
let peticion = 0

const seleccion = computed({
  get: () => modelo.value || null,
  set: (v) => {
    modelo.value = !v || v === VACIO ? '' : String(v)
  },
})

// search_link devuelve la descripción con HTML (direcciones con <br>): se deja en una línea.
function textoPlano(html) {
  return String(html || '')
    .replace(/<br\s*\/?>/gi, ', ')
    .replace(/<[^>]*>/g, '')
    .replace(/\s*,(\s*,)+/g, ',')
    .replace(/\s+/g, ' ')
    .replace(/^[\s,]+|[\s,]+$/g, '')
}

function opcion(r) {
  const label = r.label || r.value
  return { label, value: r.value, description: textoPlano(r.description) }
}

const opciones = computed(() => {
  const lista = []
  if (props.permitirVacio && modelo.value && !consulta.value) {
    lista.push({ label: __('— Vaciar —'), value: VACIO })
  }
  const vistos = new Set()
  for (const r of resultados.value) {
    vistos.add(r.value)
    lista.push(opcion(r))
  }
  if (modelo.value && !vistos.has(modelo.value)) {
    lista.push({
      label: props.etiqueta ? `${props.etiqueta}` : modelo.value,
      etiqueta: props.etiqueta || modelo.value,
      description: props.etiqueta ? modelo.value : '',
      value: modelo.value,
    })
  }
  return lista
})

async function buscar(texto) {
  const id = ++peticion
  cargando.value = true
  try {
    const filas = await call('frappe.desk.search.search_link', {
      doctype: props.doctype,
      txt: texto || '',
      filters: props.filters || undefined,
      query: props.query || undefined,
      reference_doctype: props.referenceDoctype || doctypeFactura,
      page_length: 25,
    })
    if (id !== peticion) return
    resultados.value = filas || []
  } catch {
    if (id === peticion) resultados.value = []
  } finally {
    if (id === peticion) cargando.value = false
  }
}

const buscarDebounced = useDebounceFn(buscar, 250)

// Mientras se espera a que el usuario pare de teclear se muestra «cargando», no «Sin resultados».
function buscarConRetardo(texto) {
  cargando.value = true
  buscarDebounced(texto)
}

function alAbrir(abierto) {
  if (abierto) buscar(consulta.value)
}

watch(
  () => JSON.stringify(props.filters),
  () => (resultados.value = []),
)
</script>
