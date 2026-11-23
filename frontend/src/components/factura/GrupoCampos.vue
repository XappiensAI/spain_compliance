<template>
  <div class="grid gap-3" :class="columnas === 2 ? 'grid-cols-2' : 'grid-cols-1'">
    <template v-for="c in visibles" :key="c.campo">
      <Campo
        :class="c.ancho ? 'col-span-2' : ''"
        :df="c.df"
        :model-value="valor(c.campo)"
        :editable="editable(c)"
        :label="c.label"
        :filters="c.filters"
        :query="c.query"
        :etiqueta-valor="c.etiquetaValor"
        :sufijo="c.sufijo"
        :filas="c.filas || 3"
        :moneda="f.doc?.currency"
        @update:model-value="(v) => cambiar(c.campo, v)"
      />
    </template>
  </div>
</template>

<script setup>
/**
 * Lista de campos de la cabecera o de una fila. Cada entrada es el nombre del
 * campo o `{ campo, label, filters, query, soloLectura, mostrar, ancho }`.
 * Los campos que no existen en el meta (otra versión de ERPNext) no se pintan.
 */
import { computed } from 'vue'
import Campo from '@/components/factura/Campo.vue'
import { df as dfDe } from '@/composables/factura'

const props = defineProps({
  f: { type: Object, required: true },
  campos: { type: Array, required: true },
  tabla: { type: String, default: null },
  fila: { type: Object, default: null },
  columnas: { type: Number, default: 1 },
})

const visibles = computed(() =>
  props.campos
    .map((c) => (typeof c === 'string' ? { campo: c } : c))
    .filter((c) => c.visible !== false)
    .map((c) => {
      const meta = props.f.config?.[props.tabla ? 'tablas' : 'campos']
      const existe = props.tabla
        ? meta?.[props.tabla]?.campos?.[c.campo]
        : meta?.[c.campo]
      return existe ? { ...c, df: dfDe(props.f.config, c.campo, props.tabla) } : null
    })
    .filter(Boolean),
)

function valor(campo) {
  return props.fila ? props.fila[campo] : props.f.doc?.[campo]
}

function editable(c) {
  if (c.soloLectura || c.df.read_only) return false
  const d = props.f.doc
  if (!d) return false
  if (d.docstatus === 0) return Boolean(props.f.editable)
  // Validada: solo cabecera con «permitir al validar».
  return (
    !props.f.guardando &&
    d.docstatus === 1 &&
    !props.tabla &&
    Boolean(c.df.allow_on_submit) &&
    Boolean(props.f.permisos?.write_on_submit)
  )
}

function cambiar(campo, v) {
  if (props.fila) {
    props.f.cambiar(campo, v, { tabla: props.tabla, fila: props.f.clave(props.fila) })
  } else {
    props.f.cambiar(campo, v)
  }
}
</script>
