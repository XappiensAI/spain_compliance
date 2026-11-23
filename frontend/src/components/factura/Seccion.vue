<template>
  <section class="border-b border-outline-gray-1 last:border-b-0">
    <button
      type="button"
      class="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-gray-1"
      @click="abierta = !abierta"
    >
      <component :is="icono" v-if="icono" class="size-4 shrink-0 text-ink-gray-5" />
      <span class="flex-1 truncate text-sm font-medium text-ink-gray-8">{{ titulo }}</span>
      <span v-if="resumen && !abierta" class="max-w-[50%] truncate text-xs text-ink-gray-5">{{ resumen }}</span>
      <LucideChevronDown
        class="size-4 shrink-0 text-ink-gray-5 transition-transform"
        :class="abierta ? '' : '-rotate-90'"
      />
    </button>
    <div v-if="abierta" class="flex flex-col gap-3 px-4 pb-4 pt-1">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import LucideChevronDown from '~icons/lucide/chevron-down'

const props = defineProps({
  titulo: { type: String, required: true },
  icono: { type: [Object, Function], default: null },
  resumen: { type: String, default: '' },
  abierta: { type: Boolean, default: true },
})

const abierta = ref(props.abierta)
</script>
