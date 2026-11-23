<template>
  <div v-if="fila" class="flex flex-col">
    <div class="border-b border-outline-gray-1 px-4 py-3">
      <div class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <div class="text-xs text-ink-gray-5">{{ __('Impuesto') }} {{ fila.idx }}</div>
          <div class="truncate text-base font-medium text-ink-gray-9">
            {{ fila.description || fila.account_head || __('Sin cuenta') }}
          </div>
        </div>
        <div class="text-right">
          <div class="text-xs text-ink-gray-5">{{ __('Cuota') }}</div>
          <div class="text-base font-semibold tabular-nums text-ink-gray-9">
            {{ formatMoney(fila.tax_amount, f.doc.currency) }}
          </div>
        </div>
      </div>
      <div v-if="f.editable" class="mt-2 flex">
        <Button
          size="sm"
          variant="ghost"
          theme="red"
          class="ml-auto"
          :label="__('Quitar')"
          @click="quitar"
        >
          <template #prefix><LucideTrash2 class="size-4" /></template>
        </Button>
      </div>
    </div>

    <Seccion :titulo="__('Cálculo')" :icono="LucideCalculator">
      <GrupoCampos
        :f="f"
        tabla="taxes"
        :fila="fila"
        :campos="[
          { campo: 'charge_type', label: __('Tipo de cálculo') },
          { campo: 'add_deduct_tax', label: __('Suma o resta'), visible: f.tipo.compra },
          { campo: 'category', label: __('Se aplica a'), visible: f.tipo.compra },
          { campo: 'row_id', label: __('Sobre la fila'), visible: String(fila.charge_type || '').startsWith('On Previous Row') },
          { campo: 'account_head', label: __('Cuenta'), filters: { company: f.doc.company, is_group: 0 } },
          { campo: 'description', label: __('Descripción') },
        ]"
      />
      <GrupoCampos
        :f="f"
        tabla="taxes"
        :fila="fila"
        :columnas="2"
        :campos="[
          { campo: 'rate', label: __('Tipo %'), sufijo: '%', visible: fila.charge_type !== 'Actual' },
          { campo: 'tax_amount', label: __('Cuota'), soloLectura: fila.charge_type !== 'Actual' },
          { campo: 'total', label: __('Total acumulado'), soloLectura: true },
          { campo: 'base_tax_amount', soloLectura: true, visible: f.doc.currency !== f.monedaEmpresa },
          { campo: 'included_in_print_rate', label: __('Incluido en el precio'), ancho: true },
          { campo: 'set_by_item_tax_template', soloLectura: true, visible: Boolean(fila.set_by_item_tax_template), ancho: true },
        ]"
      />
    </Seccion>

    <Seccion
      v-if="tieneClasificacion"
      :titulo="__('Clasificación fiscal')"
      :icono="LucideScale"
      :resumen="fila.clave_iva || fila.clave_retencion || ''"
    >
      <GrupoCampos
        :f="f"
        tabla="taxes"
        :fila="fila"
        :campos="[
          'tipo_impuesto',
          { campo: 'clave_iva', visible: fila.tipo_impuesto !== 'Retención IRPF' },
          { campo: 'deducible_iva', visible: f.tipo.compra && fila.tipo_impuesto !== 'Retención IRPF' },
          { campo: 'clave_retencion', visible: fila.tipo_impuesto === 'Retención IRPF' },
        ]"
      />
      <p class="text-p-xs text-ink-gray-5">
        {{ __('Si se deja vacía se copia de la plantilla de impuestos al guardar. Es la que usan el libro de IVA y el SII.') }}
      </p>
    </Seccion>

    <Seccion :titulo="__('Contabilidad')" :icono="LucideBookOpen" :abierta="false">
      <GrupoCampos
        :f="f"
        tabla="taxes"
        :fila="fila"
        :campos="[
          { campo: 'cost_center', label: __('Centro de coste'), filters: { company: f.doc.company, is_group: 0 } },
          ...f.dimensiones,
        ]"
      />
    </Seccion>

    <Seccion
      v-if="personalizados.length"
      :titulo="__('Otros datos')"
      :icono="LucideSlidersHorizontal"
    >
      <GrupoCampos :f="f" tabla="taxes" :fila="fila" :campos="personalizados" />
    </Seccion>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import Seccion from '@/components/factura/Seccion.vue'
import GrupoCampos from '@/components/factura/GrupoCampos.vue'
import { camposPersonalizados } from '@/composables/factura'
import { formatMoney } from '@/composables/informe'
import LucideCalculator from '~icons/lucide/calculator'
import LucideScale from '~icons/lucide/scale'
import LucideBookOpen from '~icons/lucide/book-open'
import LucideSlidersHorizontal from '~icons/lucide/sliders-horizontal'
import LucideTrash2 from '~icons/lucide/trash-2'

const props = defineProps({
  f: { type: Object, required: true },
  clave: { type: String, required: true },
})
const emit = defineEmits(['cerrar'])

const fila = computed(() => props.f.doc?.taxes?.find((r) => props.f.clave(r) === props.clave))

const CLASIFICACION = ['tipo_impuesto', 'clave_iva', 'clave_retencion', 'deducible_iva']

const tieneClasificacion = computed(
  () => Boolean(props.f.config?.tablas?.taxes?.campos?.tipo_impuesto),
)

const personalizados = computed(() =>
  camposPersonalizados(props.f.config, 'taxes', CLASIFICACION),
)

function quitar() {
  props.f.quitarFila('taxes', props.clave)
  emit('cerrar')
}
</script>
