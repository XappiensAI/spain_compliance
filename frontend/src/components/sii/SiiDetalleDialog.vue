<script setup>
/**
 * Detalle SII de una factura — registro, historial de envíos y XML.
 * Uso — <SiiDetalleDialog v-model="open" :registro="name" :documento="{ doctype, name }" @changed="reload" />
 * Con `registro` muestra el registro; sin él (factura aún sin registro) muestra
 * la vista previa del XML y los datos que faltan.
 */
import { ref, computed, watch } from 'vue'
import { Dialog, Badge, Button, LoadingIndicator, call, toast } from 'frappe-ui'
import {
  SII_API,
  siiTheme,
  fmtDate,
  fmtDateTime,
  fmtMoney,
  deskUrl,
  errorMessage,
  resumenResultado,
  enviarSii,
  consultarSii,
} from '@/composables/sii'
import LucideSend from '~icons/lucide/send'
import LucideSearch from '~icons/lucide/search'
import LucideExternalLink from '~icons/lucide/external-link'
import LucideAlertTriangle from '~icons/lucide/alert-triangle'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  registro: { type: String, default: null },
  documento: { type: Object, default: null },
  canSend: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const loading = ref(false)
const busy = ref('')
const detalle = ref(null)
const preview = ref(null)
const error = ref('')
const verXml = ref('')
const registroActual = ref(null)

const doc = computed(() =>
  detalle.value
    ? { doctype: detalle.value.documento_tipo, name: detalle.value.documento }
    : props.documento
)

async function cargar() {
  error.value = ''
  detalle.value = null
  preview.value = null
  verXml.value = ''
  loading.value = true
  try {
    if (registroActual.value) {
      detalle.value = await call(`${SII_API}.registro`, { name: registroActual.value })
    } else if (props.documento) {
      preview.value = await call(`${SII_API}.vista_previa`, {
        doctype: props.documento.doctype,
        name: props.documento.name,
      })
    }
  } catch (e) {
    error.value = errorMessage(e, 'No se pudo cargar el detalle SII')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      registroActual.value = props.registro
      cargar()
    }
  }
)

async function vistaPrevia() {
  if (!doc.value) return
  busy.value = 'preview'
  try {
    preview.value = await call(`${SII_API}.vista_previa`, doc.value)
    verXml.value = 'preview'
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
  }
}

async function enviar(modificar = false) {
  busy.value = modificar ? 'modificar' : 'enviar'
  try {
    const res = registroActual.value
      ? await enviarSii({ registros: [registroActual.value], modificar })
      : await enviarSii({ documentos: [doc.value], modificar })
    ;(res.avisos || []).forEach((a) => toast.warning(a))
    if (res.n) toast.success(resumenResultado(res))
    await refrescarRegistro()
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
  }
}

async function consultar() {
  busy.value = 'consultar'
  try {
    const res = await consultarSii({ documentos: [doc.value] })
    const r = (res.resultados || [])[0]
    if (r && !r.ok) toast.error(`AEAT — ${r.error}`)
    else if (r && r.encontrado) toast.success(`En la AEAT — ${r.encontrado.estado} (${r.entorno})`)
    else toast.warning(`No consta en la AEAT (${r?.entorno || ''})`)
    await refrescarRegistro()
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
  }
}

async function pedirBaja() {
  busy.value = 'baja'
  try {
    await call(`${SII_API}.marcar_baja_pendiente`, { registro: registroActual.value })
    toast.success('Baja pendiente. Use «Enviar» para comunicarla.')
    await refrescarRegistro()
  } catch (e) {
    toast.error(errorMessage(e))
  } finally {
    busy.value = ''
  }
}

async function refrescarRegistro() {
  if (!registroActual.value && doc.value) {
    const estados = await call(`${SII_API}.estado_documentos`, {
      doctype: doc.value.doctype,
      names: [doc.value.name],
    })
    registroActual.value = (estados?.estados || estados)?.[doc.value.name]?.name || null
  }
  emit('changed')
  await cargar()
}

function abrirFactura() {
  if (doc.value) window.open(deskUrl(doc.value.doctype, doc.value.name), '_blank')
}

const d = computed(() => detalle.value || {})
const comunicado = computed(() => ['Aceptado', 'Aceptado con errores'].includes(d.value.estado))
</script>

<template>
  <Dialog
    :model-value="modelValue"
    :options="{ size: '3xl' }"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <template #body-title>
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-lg font-semibold text-ink-gray-9">SII · {{ doc?.name }}</h3>
        <Badge v-if="d.estado" :theme="siiTheme(d.estado)" variant="subtle" :label="d.estado" />
        <Badge v-if="d.entorno" :theme="d.entorno === 'Producción' ? 'blue' : 'gray'" variant="outline" :label="d.entorno" />
      </div>
    </template>
    <template #body-content>
      <div v-if="loading" class="flex justify-center py-10">
        <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
      </div>
      <div v-else-if="error" class="rounded-md bg-surface-red-1 px-3 py-2 text-sm text-ink-red-7">{{ error }}</div>

      <div v-else class="space-y-4 text-sm">
        <!-- Registro -->
        <template v-if="detalle">
          <div class="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            <div>
              <div class="text-xs text-ink-gray-5">Libro</div>
              <div class="text-ink-gray-9">{{ d.libro }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Nº comunicado</div>
              <div class="text-ink-gray-9">{{ d.numero_factura || '—' }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Periodo</div>
              <div class="text-ink-gray-9">{{ d.periodo }}/{{ d.ejercicio }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Importe total</div>
              <div class="tabular-nums text-ink-gray-9">{{ fmtMoney(d.importe_total) }}</div>
            </div>
            <div class="col-span-2">
              <div class="text-xs text-ink-gray-5">Tercero</div>
              <div class="text-ink-gray-9">{{ d.tercero }} <span class="text-ink-gray-5">· {{ d.nif || 'sin NIF' }}</span></div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Fecha límite</div>
              <div class="text-ink-gray-9">{{ fmtDate(d.fecha_limite) }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Comunicación</div>
              <div class="text-ink-gray-9">{{ d.tipo_comunicacion }} · {{ d.origen }}</div>
            </div>
            <div class="col-span-2">
              <div class="text-xs text-ink-gray-5">CSV</div>
              <div class="font-mono text-ink-gray-9">{{ d.csv || '—' }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">Último envío</div>
              <div class="text-ink-gray-9">{{ fmtDateTime(d.fecha_envio) }}</div>
            </div>
            <div>
              <div class="text-xs text-ink-gray-5">En la AEAT</div>
              <div class="text-ink-gray-9">
                {{ d.estado_aeat || '—' }}
                <span v-if="d.estado_cuadre" class="text-ink-gray-5">· cuadre {{ d.estado_cuadre }}</span>
              </div>
            </div>
          </div>

          <div
            v-if="d.descripcion_error"
            class="flex items-start gap-2 rounded-md border px-3 py-2"
            :class="comunicado ? 'border-outline-gray-2 bg-surface-gray-1 text-ink-gray-7' : 'border-outline-red-2 bg-surface-red-1 text-ink-red-7'"
          >
            <LucideAlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <span class="whitespace-pre-line">
              <span v-if="d.codigo_error" class="font-medium">[{{ d.codigo_error }}] </span>{{ d.descripcion_error }}
            </span>
          </div>

          <div>
            <h4 class="mb-1 text-sm font-medium text-ink-gray-8">Historial</h4>
            <div class="max-h-56 overflow-auto rounded-md border border-outline-gray-2">
              <table class="w-full text-xs">
                <thead class="bg-surface-gray-1 text-left text-ink-gray-5">
                  <tr>
                    <th class="px-2 py-1.5 font-medium">Fecha</th>
                    <th class="px-2 py-1.5 font-medium">Acción</th>
                    <th class="px-2 py-1.5 font-medium">Entorno</th>
                    <th class="px-2 py-1.5 font-medium">Resultado</th>
                    <th class="px-2 py-1.5 font-medium">Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(e, i) in d.eventos" :key="i" class="border-t border-outline-gray-1 align-top">
                    <td class="whitespace-nowrap px-2 py-1.5 text-ink-gray-6">{{ fmtDateTime(e.fecha) }}</td>
                    <td class="px-2 py-1.5 text-ink-gray-8">{{ e.accion }}</td>
                    <td class="px-2 py-1.5 text-ink-gray-6">{{ e.entorno }}</td>
                    <td class="px-2 py-1.5">
                      <Badge :theme="siiTheme(e.resultado)" variant="subtle" size="sm" :label="e.resultado" />
                    </td>
                    <td class="px-2 py-1.5 text-ink-gray-6">
                      <span v-if="e.csv" class="font-mono">{{ e.csv }} </span>{{ e.mensaje }}
                    </td>
                  </tr>
                  <tr v-if="!d.eventos?.length">
                    <td colspan="5" class="px-2 py-3 text-center text-ink-gray-5">Sin envíos todavía</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- Sin registro: vista previa -->
        <template v-else-if="preview && !verXml">
          <p class="text-ink-gray-7">
            Esta factura todavía no tiene registro SII. Así quedaría la comunicación.
          </p>
        </template>

        <div v-if="preview && (preview.errores?.length || preview.no_aplica)" class="space-y-1">
          <div
            v-for="(err, i) in preview.errores"
            :key="i"
            class="flex items-start gap-2 rounded-md border border-outline-red-2 bg-surface-red-1 px-3 py-2 text-ink-red-7"
          >
            <LucideAlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ err }}</span>
          </div>
          <div v-if="preview.no_aplica" class="rounded-md bg-surface-gray-2 px-3 py-2 text-ink-gray-7">
            Solo tiene operaciones no sujetas — no se comunica al SII.
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <Button size="sm" :variant="verXml === 'preview' ? 'solid' : 'subtle'" :loading="busy === 'preview'" @click="verXml === 'preview' ? (verXml = '') : vistaPrevia()">
            XML que se enviaría
          </Button>
          <Button v-if="d.xml_enviado" size="sm" :variant="verXml === 'enviado' ? 'solid' : 'subtle'" @click="verXml = verXml === 'enviado' ? '' : 'enviado'">
            Último XML enviado
          </Button>
          <Button v-if="d.respuesta" size="sm" :variant="verXml === 'respuesta' ? 'solid' : 'subtle'" @click="verXml = verXml === 'respuesta' ? '' : 'respuesta'">
            Respuesta de la AEAT
          </Button>
        </div>
        <pre
          v-if="verXml"
          class="max-h-80 overflow-auto rounded-md bg-surface-gray-1 p-3 font-mono text-[11px] leading-snug text-ink-gray-8"
        >{{ verXml === 'preview' ? (preview?.xml || 'No se puede generar — revise los errores.') : verXml === 'enviado' ? d.xml_enviado : d.respuesta }}</pre>
      </div>
    </template>
    <template #actions>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" @click="abrirFactura">
          <template #prefix><LucideExternalLink class="h-4 w-4" /></template>
          Abrir factura
        </Button>
        <div v-if="canSend" class="flex flex-wrap gap-2">
          <Button v-if="comunicado" variant="subtle" theme="red" :loading="busy === 'baja'" @click="pedirBaja">
            Pedir baja
          </Button>
          <Button variant="subtle" :loading="busy === 'consultar'" @click="consultar">
            <template #prefix><LucideSearch class="h-4 w-4" /></template>
            Consultar en la AEAT
          </Button>
          <Button v-if="comunicado" variant="subtle" :loading="busy === 'modificar'" @click="enviar(true)">
            Reenviar (A1)
          </Button>
          <Button v-else variant="solid" :loading="busy === 'enviar'" @click="enviar(false)">
            <template #prefix><LucideSend class="h-4 w-4" /></template>
            {{ d.estado === 'Baja pendiente' ? 'Enviar baja' : 'Enviar al SII' }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>
