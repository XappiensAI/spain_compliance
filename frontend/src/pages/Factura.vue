<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="migas" />
      <Badge v-if="f.doc" :label="__(estado[0])" :theme="estado[1]" variant="subtle" />
      <Badge v-if="f.doc?.is_return && f.doc?.status !== 'Return'" :label="__('Rectificativa')" theme="orange" variant="subtle" />
      <span v-if="f.calculando" class="flex items-center gap-1 text-sm text-ink-gray-5">
        <LoadingIndicator class="size-3" /> {{ __('Recalculando') }}
      </span>
      <span v-else-if="f.sucio" class="text-sm text-ink-amber-7">{{ __('Sin guardar') }}</span>
    </template>
    <template #right-header>
      <template v-if="f.doc">
        <Button
          v-if="puedeGuardar"
          :label="__('Guardar')"
          :variant="f.permisos.submit && !f.sucio ? 'subtle' : 'solid'"
          :loading="f.guardando === 'guardar'"
          @click="guardar"
        >
          <template #prefix><LucideSave class="size-4" /></template>
        </Button>
        <Button
          v-if="f.permisos.submit"
          :label="__('Validar')"
          variant="solid"
          :loading="f.guardando === 'validar'"
          @click="confirmar('validar')"
        >
          <template #prefix><LucideCheck class="size-4" /></template>
        </Button>
        <Button
          v-if="f.permisos.amend"
          :label="__('Modificar')"
          variant="solid"
          :loading="f.guardando === 'modificar'"
          @click="modificar"
        />
        <Dropdown :options="menu" align="end">
          <Button variant="subtle">
            <template #icon><LucideEllipsis class="size-4" /></template>
          </Button>
        </Dropdown>
      </template>
    </template>
  </LayoutHeader>

  <div v-if="f.cargando && !f.doc" class="flex flex-1 items-center justify-center">
    <LoadingIndicator class="size-6 text-ink-gray-5" />
  </div>

  <div v-else-if="f.error && !f.doc" class="p-5">
    <Alert theme="red" :title="__('No se ha podido abrir la factura')" :description="mensajeError(f.error)" />
  </div>

  <div v-else-if="f.doc" class="flex min-h-0 flex-1">
    <!-- Columna principal -->
    <div class="min-w-0 flex-1 overflow-y-auto" @keydown.esc="seleccion = null">
      <div class="mx-auto flex max-w-6xl flex-col gap-4 p-4 sm:p-5">
        <!-- Avisos -->
        <div v-if="f.avisos.length" class="flex flex-col gap-2">
          <Alert
            v-for="(a, i) in f.avisos"
            :key="i"
            theme="yellow"
            dismissible
            :title="a"
          />
        </div>

        <!-- Cabecera -->
        <div class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
          <div
            class="grid grid-cols-3 gap-4 p-4"
            :class="t.compra ? '' : '2xl:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))]'"
          >
            <div class="col-span-3 flex min-w-0 flex-col gap-1.5" :class="t.compra ? '' : '2xl:col-span-1'">
              <Campo
                :df="df(f.config, t.tercero)"
                :model-value="f.doc[t.tercero]"
                :editable="f.editable"
                :label="__(t.terceroLabel)"
                :etiqueta-valor="f.doc[t.terceroNombre]"
                :filters="t.terceroFiltro"
                variant="outline"
                @update:model-value="(v) => f.cambiar(t.tercero, v)"
              />
              <div v-if="f.doc[t.tercero]" class="truncate text-p-sm text-ink-gray-5">
                <span v-if="f.doc.tax_id">{{ f.doc.tax_id }} · </span>{{ direccionCorta }}
              </div>
            </div>
            <template v-if="t.compra">
              <Campo
                :df="df(f.config, 'bill_no')"
                :model-value="f.doc.bill_no"
                :editable="f.editable"
                :label="__('Nº factura del proveedor')"
                variant="outline"
                @update:model-value="(v) => f.cambiar('bill_no', v)"
              />
              <Campo
                :df="df(f.config, 'bill_date')"
                :model-value="f.doc.bill_date"
                :editable="f.editable"
                :label="__('Fecha de la factura')"
                variant="outline"
                @update:model-value="(v) => f.cambiar('bill_date', v)"
              />
            </template>
            <Campo
              :df="df(f.config, 'posting_date')"
              :model-value="f.doc.posting_date"
              :editable="f.editable"
              :label="t.compra ? __('Fecha de registro') : __('Fecha')"
              variant="outline"
              @update:model-value="(v) => f.cambiar('posting_date', v)"
            />
            <Campo
              :df="df(f.config, 'due_date')"
              :model-value="f.doc.due_date"
              :editable="f.editable"
              :label="__('Vencimiento')"
              variant="outline"
              @update:model-value="(v) => f.cambiar('due_date', v)"
            />
            <Campo
              :df="df(f.config, 'taxes_and_charges')"
              :model-value="f.doc.taxes_and_charges"
              :editable="f.editable"
              :label="__('Impuestos')"
              :filters="{ company: f.doc.company, disabled: 0 }"
              variant="outline"
              @update:model-value="(v) => f.cambiar('taxes_and_charges', v)"
            />
          </div>
          <div
            class="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-outline-gray-1 px-4 py-2 text-p-sm text-ink-gray-6"
          >
            <button type="button" class="hover:text-ink-gray-9" @click="seleccion = null">
              <span class="text-ink-gray-5">{{ __('Serie') }}</span> {{ f.doc.naming_series || '—' }}
            </button>
            <button type="button" class="hover:text-ink-gray-9" @click="seleccion = null">
              <span class="text-ink-gray-5">{{ __(t.cuentaLabel) }}</span> {{ cuentaCorta(f.doc[t.cuenta]) || '—' }}
            </button>
            <button type="button" class="hover:text-ink-gray-9" @click="seleccion = null">
              <span class="text-ink-gray-5">{{ __('Centro de coste') }}</span> {{ f.doc.cost_center || '—' }}
            </button>
            <span v-if="f.doc.project"><span class="text-ink-gray-5">{{ __('Proyecto') }}</span> {{ f.doc.project }}</span>
            <span v-if="f.doc.po_no"><span class="text-ink-gray-5">{{ __('Ref. cliente') }}</span> {{ f.doc.po_no }}</span>
            <span v-if="f.doc.on_hold" class="text-ink-amber-7">{{ __('Pago retenido') }}<template v-if="f.doc.release_date"> {{ __('hasta') }} {{ formatDate(f.doc.release_date) }}</template></span>
            <span v-if="f.doc.is_paid" class="text-ink-green-7">{{ __('Pagada al contado') }}</span>
            <span v-if="f.doc.return_against">
              <span class="text-ink-gray-5">{{ __('Rectifica a') }}</span>
              <router-link class="text-ink-blue-7 hover:underline" :to="rutaFactura(f.doc.return_against)">{{ f.doc.return_against }}</router-link>
            </span>
            <button
              v-if="contexto.sii && f.doc.docstatus"
              type="button"
              class="ml-auto flex items-center gap-1.5 hover:text-ink-gray-9"
              @click="siiDialog = true"
            >
              <span class="text-ink-gray-5">SII</span>
              <Badge :label="siiLabel(siiFila)" :theme="siiRowTheme(siiFila)" variant="subtle" size="sm" />
            </button>
          </div>
        </div>

        <!-- Líneas -->
        <div class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
          <div class="flex items-center justify-between gap-2 px-4 py-2.5">
            <h3 class="text-base font-medium text-ink-gray-9">
              {{ __('Líneas') }}
              <span class="text-ink-gray-5">· {{ (f.doc.items || []).length }}</span>
            </h3>
            <Button v-if="f.editable" size="sm" :label="__('Añadir línea')" @click="anadirLinea">
              <template #prefix><LucidePlus class="size-4" /></template>
            </Button>
          </div>
          <div class="overflow-x-auto border-t border-outline-gray-1">
            <table class="w-full min-w-[42rem] table-fixed text-base">
              <thead>
                <tr class="border-b border-outline-gray-1 text-left text-xs text-ink-gray-5">
                  <th class="w-8 py-2 pl-4 font-normal">#</th>
                  <th class="w-32 py-2 pr-2 font-normal">{{ __('Artículo') }}</th>
                  <th class="py-2 pr-2 font-normal">{{ __('Descripción') }}</th>
                  <th class="w-24 py-2 pr-2 text-right font-normal">{{ __('Cantidad') }}</th>
                  <th class="w-24 py-2 pr-2 text-right font-normal">{{ __('Precio') }}</th>
                  <th class="w-16 py-2 pr-2 text-right font-normal">{{ __('Dto. %') }}</th>
                  <th class="w-24 py-2 pr-4 text-right font-normal">{{ __('Importe') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in f.doc.items"
                  :key="f.clave(row)"
                  class="cursor-pointer border-b border-outline-gray-1 align-top last:border-b-0"
                  :class="esSeleccion('items', row) ? 'bg-surface-blue-1' : 'hover:bg-surface-gray-1'"
                  @click="seleccionar('items', row)"
                  @focusin="seleccionar('items', row)"
                >
                  <td class="py-2 pl-4 pt-3 text-sm tabular-nums text-ink-gray-5">{{ row.idx }}</td>
                  <td class="py-2 pr-2" @click.stop="seleccionar('items', row)">
                    <CampoLink
                      v-if="f.editable"
                      :model-value="row.item_code || ''"
                      doctype="Item"
                      query="erpnext.controllers.queries.item_query"
                      :filters="t.articuloFiltro"
                      :etiqueta="row.item_code"
                      :permitir-vacio="false"
                      variant="ghost"
                      :placeholder="__('Artículo…')"
                      @update:model-value="(v) => cambiarFila(row, 'item_code', v)"
                    />
                    <div v-else class="truncate py-1 text-ink-gray-8">{{ row.item_code }}</div>
                  </td>
                  <td class="py-2 pr-2">
                    <textarea
                      v-if="f.editable"
                      :value="htmlATexto(row.description)"
                      rows="1"
                      class="descripcion-linea block w-full resize-none rounded border-0 bg-transparent px-2 py-1 text-base text-ink-gray-9 placeholder-ink-gray-4 hover:bg-surface-gray-2 focus:bg-surface-white focus:ring-1 focus:ring-outline-gray-3"
                      :placeholder="row.item_name || __('Descripción…')"
                      @input="(e) => cambiarFila(row, 'description', textoAHtml(e.target.value))"
                    />
                    <div v-else class="whitespace-pre-line break-words py-1 text-ink-gray-9">
                      {{ htmlATexto(row.description) || row.item_name || '—' }}
                    </div>
                    <div class="flex flex-wrap gap-x-3 gap-y-0.5 px-2 text-xs text-ink-gray-5">
                      <span v-if="row.item_name && row.item_name !== htmlATexto(row.description).trim()">{{ row.item_name }}</span>
                      <span v-if="row[t.cuentaLinea]" :title="row[t.cuentaLinea]">{{ cuentaCorta(row[t.cuentaLinea]) }}</span>
                      <span v-if="row.purchase_order">{{ row.purchase_order }}</span>
                      <span v-if="row.purchase_receipt">{{ row.purchase_receipt }}</span>
                      <span v-if="row.cost_center && row.cost_center !== f.doc.cost_center">{{ row.cost_center }}</span>
                      <span v-if="row.project">{{ row.project }}</span>
                      <span v-if="row.warehouse && f.doc.update_stock">{{ row.warehouse }}</span>
                      <span v-if="row.item_tax_template" class="text-ink-blue-7">{{ row.item_tax_template }}</span>
                      <span v-if="row.sales_order">{{ row.sales_order }}</span>
                      <span v-if="row.delivery_note">{{ row.delivery_note }}</span>
                    </div>
                  </td>
                  <td class="py-2 pr-2">
                    <TextInput
                      v-if="f.editable"
                      type="number"
                      size="sm"
                      variant="ghost"
                      class="text-right tabular-nums"
                      :model-value="row.qty"
                      @update:model-value="(v) => cambiarNumero(row, 'qty', v)"
                    >
                      <template v-if="row.uom" #suffix>
                        <span class="text-xs text-ink-gray-5">{{ row.uom }}</span>
                      </template>
                    </TextInput>
                    <div v-else class="py-1 text-right tabular-nums">
                      {{ num(row.qty) }} <span class="text-xs text-ink-gray-5">{{ row.uom }}</span>
                    </div>
                  </td>
                  <td class="py-2 pr-2">
                    <TextInput
                      v-if="f.editable"
                      type="number"
                      size="sm"
                      variant="ghost"
                      class="text-right tabular-nums"
                      :model-value="row.rate"
                      @update:model-value="(v) => cambiarNumero(row, 'rate', v)"
                    />
                    <div v-else class="py-1 text-right tabular-nums">{{ formatNumber(row.rate, 2) }}</div>
                  </td>
                  <td class="py-2 pr-2">
                    <TextInput
                      v-if="f.editable"
                      type="number"
                      size="sm"
                      variant="ghost"
                      class="text-right tabular-nums"
                      :model-value="row.discount_percentage || ''"
                      @update:model-value="(v) => cambiarNumero(row, 'discount_percentage', v)"
                    />
                    <div v-else class="py-1 text-right tabular-nums text-ink-gray-6">
                      {{ Number(row.discount_percentage) ? num(row.discount_percentage) : '' }}
                    </div>
                  </td>
                  <td class="py-2 pr-4 pt-3 text-right tabular-nums text-ink-gray-9">
                    {{ formatNumber(row.amount, 2) }}
                  </td>
                </tr>
                <tr v-if="!(f.doc.items || []).length">
                  <td colspan="7" class="px-4 py-8 text-center text-p-sm text-ink-gray-5">
                    {{ f.editable ? __('Añade la primera línea de la factura.') : __('Sin líneas') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Impuestos y totales -->
        <div class="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
            <div class="flex items-center justify-between gap-2 px-4 py-2.5">
              <h3 class="text-base font-medium text-ink-gray-9">{{ __('Impuestos') }}</h3>
              <Button v-if="f.editable" size="sm" :label="__('Añadir impuesto')" @click="anadirImpuesto">
                <template #prefix><LucidePlus class="size-4" /></template>
              </Button>
            </div>
            <div class="border-t border-outline-gray-1">
              <button
                v-for="imp in f.doc.taxes"
                :key="f.clave(imp)"
                type="button"
                class="grid w-full grid-cols-[minmax(0,1fr)_4.5rem_7rem] items-center gap-3 border-b border-outline-gray-1 px-4 py-2 text-left last:border-b-0"
                :class="esSeleccion('taxes', imp) ? 'bg-surface-blue-1' : 'hover:bg-surface-gray-1'"
                @click="seleccionar('taxes', imp)"
              >
                <div class="min-w-0">
                  <div class="truncate text-ink-gray-9">{{ imp.description || imp.account_head || __('Sin cuenta') }}</div>
                  <div class="flex gap-3 truncate text-xs text-ink-gray-5">
                    <span>{{ cuentaCorta(imp.account_head) }}</span>
                    <span v-if="imp.clave_iva">{{ String(imp.clave_iva).split(' - ')[0] }}</span>
                    <span v-if="imp.clave_retencion">{{ String(imp.clave_retencion).split(' - ')[0] }}</span>
                    <span v-if="imp.charge_type === 'Actual'">{{ __('Importe fijo') }}</span>
                    <span v-if="imp.add_deduct_tax === 'Deduct'">{{ __('Resta') }}</span>
                    <span v-if="imp.category && imp.category !== 'Total'">{{ imp.category === 'Valuation' ? __('Solo valoración') : __('Valoración y total') }}</span>
                    <span v-if="imp.deducible_iva && imp.deducible_iva !== 'Corriente'">{{ imp.deducible_iva }}</span>
                  </div>
                </div>
                <span class="text-right tabular-nums text-ink-gray-6">
                  {{ imp.charge_type === 'Actual' ? '' : `${num(imp.rate)} %` }}
                </span>
                <span class="text-right tabular-nums text-ink-gray-9">{{ imp.add_deduct_tax === 'Deduct' ? '−' : '' }}{{ formatNumber(imp.tax_amount, 2) }}</span>
              </button>
              <div v-if="!(f.doc.taxes || []).length" class="px-4 py-6 text-center text-p-sm text-ink-gray-5">
                {{ __('Sin impuestos. Elige una plantilla en la cabecera o añade una fila.') }}
              </div>
            </div>
          </div>

          <div class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1 p-4">
            <dl class="flex flex-col gap-1.5 text-base">
              <div class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __('Suma de líneas') }}</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ dinero(f.doc.total) }}</dd>
              </div>
              <div v-if="Number(f.doc.discount_amount)" class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __('Descuento') }}</dt>
                <dd class="tabular-nums text-ink-gray-8">−{{ dinero(f.doc.discount_amount) }}</dd>
              </div>
              <div class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __('Base imponible') }}</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ dinero(f.doc.net_total) }}</dd>
              </div>
              <div class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __('Impuestos') }}</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ dinero(f.doc.total_taxes_and_charges) }}</dd>
              </div>
              <div v-if="Number(f.doc.rounding_adjustment)" class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __('Redondeo') }}</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ dinero(f.doc.rounding_adjustment) }}</dd>
              </div>
              <div class="mt-1 flex justify-between gap-3 border-t border-outline-gray-1 pt-2">
                <dt class="font-medium text-ink-gray-9">{{ __('Total') }}</dt>
                <dd class="text-xl font-semibold tabular-nums text-ink-gray-9">
                  {{ dinero(f.doc.rounded_total || f.doc.grand_total) }}
                </dd>
              </div>
              <div v-if="f.doc.docstatus === 1" class="flex justify-between gap-3">
                <dt class="text-ink-gray-6">{{ __(t.pendiente) }}</dt>
                <dd
                  class="tabular-nums"
                  :class="Number(f.doc.outstanding_amount) > 0.005 ? 'text-ink-amber-7' : 'text-ink-green-7'"
                >
                  {{ dinero(f.doc.outstanding_amount) }}
                </dd>
              </div>
              <div
                v-if="f.doc.currency !== f.monedaEmpresa && f.doc.base_grand_total"
                class="flex justify-between gap-3 text-sm"
              >
                <dt class="text-ink-gray-5">{{ __('En moneda de la empresa') }}</dt>
                <dd class="tabular-nums text-ink-gray-6">{{ formatMoney(f.doc.base_grand_total, f.monedaEmpresa) }}</dd>
              </div>
            </dl>
          </div>
        </div>

        <!-- Observaciones -->
        <div class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
          <h3 class="px-4 py-2.5 text-base font-medium text-ink-gray-9">{{ __('Observaciones') }}</h3>
          <div class="border-t border-outline-gray-1 p-3">
            <Textarea
              v-if="f.editable"
              :model-value="observaciones"
              :rows="3"
              size="sm"
              variant="outline"
              :placeholder="__('Notas de la factura…')"
              @update:model-value="(v) => f.cambiar('remarks', v)"
            />
            <p v-else class="whitespace-pre-line break-words px-1 text-p-base" :class="observaciones ? 'text-ink-gray-8' : 'text-ink-gray-4'">
              {{ observaciones || __('Sin observaciones') }}
            </p>
          </div>
        </div>

        <!-- Contabilización, cobros y documentos relacionados -->
        <div v-if="f.doc.docstatus === 1 || hayRelacionados" class="grid gap-4 2xl:grid-cols-2">
          <div v-if="(contexto.asientos || []).length" class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
            <h3 class="px-4 py-2.5 text-base font-medium text-ink-gray-9">{{ __('Asiento contable') }}</h3>
            <div class="border-t border-outline-gray-1">
              <div
                v-for="(g, i) in contexto.asientos"
                :key="i"
                class="grid grid-cols-[minmax(0,1fr)_6.5rem_6.5rem] gap-3 border-b border-outline-gray-1 px-4 py-1.5 text-sm last:border-b-0"
              >
                <div class="min-w-0">
                  <div class="truncate text-ink-gray-8" :title="g.account">{{ g.account }}</div>
                  <div v-if="g.cost_center || g.project" class="truncate text-xs text-ink-gray-5">
                    {{ [g.cost_center, g.project].filter(Boolean).join(' · ') }}
                  </div>
                </div>
                <span class="text-right tabular-nums text-ink-gray-8">{{ formatImporte(g.debit) }}</span>
                <span class="text-right tabular-nums text-ink-gray-8">{{ formatImporte(g.credit) }}</span>
              </div>
            </div>
          </div>

          <div class="flex flex-col gap-4">
            <div v-if="f.doc.docstatus === 1" class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
              <h3 class="px-4 py-2.5 text-base font-medium text-ink-gray-9">{{ __(t.cobros) }}</h3>
              <div class="border-t border-outline-gray-1">
                <component
                  :is="TIPOS[c.voucher_type] ? 'router-link' : 'a'"
                  v-for="c in contexto.cobros || []"
                  :key="c.voucher_no"
                  v-bind="enlaceDocumento(c.voucher_type, c.voucher_no)"
                  class="flex items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-1.5 text-sm last:border-b-0 hover:bg-surface-gray-1"
                >
                  <span class="truncate text-ink-gray-8">
                    {{ formatDate(c.posting_date) }} · {{ c.voucher_no }}
                    <span class="text-ink-gray-5">· {{ __(c.voucher_type) }}</span>
                  </span>
                  <span class="tabular-nums text-ink-gray-9">{{ formatNumber(-c.amount, 2) }}</span>
                </component>
                <div v-if="!(contexto.cobros || []).length" class="px-4 py-4 text-p-sm text-ink-gray-5">
                  {{ t.compra ? __('Sin pagos registrados') : __('Sin cobros registrados') }}
                </div>
              </div>
            </div>

            <div v-if="(contexto.rectificativas || []).length" class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
              <h3 class="px-4 py-2.5 text-base font-medium text-ink-gray-9">{{ __('Rectificativas') }}</h3>
              <div class="border-t border-outline-gray-1">
                <router-link
                  v-for="r in contexto.rectificativas"
                  :key="r.name"
                  :to="rutaFactura(r.name)"
                  class="flex items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-1.5 text-sm last:border-b-0 hover:bg-surface-gray-1"
                >
                  <span class="text-ink-gray-8">{{ r.name }} · {{ formatDate(r.posting_date) }}</span>
                  <span class="tabular-nums text-ink-gray-9">{{ formatNumber(r.grand_total, 2) }}</span>
                </router-link>
              </div>
            </div>

            <div v-if="(contexto.adjuntos || []).length" class="rounded-lg border border-outline-gray-1 bg-surface-elevation-1">
              <h3 class="px-4 py-2.5 text-base font-medium text-ink-gray-9">{{ __('Adjuntos') }}</h3>
              <div class="border-t border-outline-gray-1">
                <a
                  v-for="a in contexto.adjuntos"
                  :key="a.name"
                  :href="a.file_url"
                  target="_blank"
                  class="flex items-center gap-2 border-b border-outline-gray-1 px-4 py-1.5 text-sm text-ink-gray-8 last:border-b-0 hover:bg-surface-gray-1"
                >
                  <LucidePaperclip class="size-4 shrink-0 text-ink-gray-5" />
                  <span class="truncate">{{ a.file_name }}</span>
                </a>
              </div>
            </div>
          </div>
        </div>

        <p v-if="contexto.actividad" class="text-p-xs text-ink-gray-5">
          {{ __('Creada por') }} {{ contexto.actividad.owner }} · {{ fmtDateTime(contexto.actividad.creation) }}
          — {{ __('modificada por') }} {{ contexto.actividad.modified_by }} · {{ fmtDateTime(contexto.actividad.modified) }}
        </p>
      </div>
    </div>

    <!-- Panel derecho -->
    <aside
      class="hidden w-[22rem] shrink-0 xl:w-[26rem] overflow-y-auto border-l border-outline-gray-1 bg-surface-base md:block"
    >
      <div
        class="sticky top-0 z-10 flex items-center gap-1 border-b border-outline-gray-1 bg-surface-base px-2 py-1.5"
      >
        <Button
          size="sm"
          :variant="!seleccion ? 'subtle' : 'ghost'"
          :label="__('Factura')"
          @click="seleccion = null"
        >
          <template #prefix><LucideFileText class="size-4" /></template>
        </Button>
        <template v-if="seleccion">
          <LucideChevronRight class="size-4 text-ink-gray-4" />
          <Button size="sm" variant="subtle" :label="tituloSeleccion" />
          <Button class="ml-auto" size="sm" variant="ghost" :tooltip="__('Cerrar (Esc)')" @click="seleccion = null">
            <template #icon><LucideX class="size-4" /></template>
          </Button>
        </template>
      </div>
      <PanelLinea
        v-if="seleccion?.tabla === 'items'"
        :key="seleccion.clave"
        :f="f"
        :clave="seleccion.clave"
        @seleccionar="(k) => (seleccion = { tabla: 'items', clave: k })"
        @cerrar="seleccion = null"
      />
      <PanelImpuesto
        v-else-if="seleccion?.tabla === 'taxes'"
        :key="seleccion.clave"
        :f="f"
        :clave="seleccion.clave"
        @cerrar="seleccion = null"
      />
      <PanelFactura v-else :f="f" />
    </aside>
  </div>

  <SiiDetalleDialog
    v-if="f.doc && !f.esNuevo"
    v-model="siiDialog"
    :registro="contexto.sii?.name || null"
    :documento="{ doctype: f.doctype, name: f.doc.name }"
    :can-send="Boolean(contexto.sii_puede_enviar)"
    @changed="f.recargar()"
  />

  <Dialog v-model="dialogo.abierto" :options="{ title: dialogo.titulo, message: dialogo.mensaje, size: 'md' }">
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Volver')" @click="dialogo.abierto = false" />
        <Button
          :label="dialogo.boton"
          variant="solid"
          :theme="dialogo.tema"
          :loading="Boolean(f.guardando)"
          @click="dialogo.accion"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, h, markRaw, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  Dialog,
  Dropdown,
  LoadingIndicator,
  TextInput,
  Textarea,
  call,
  toast,
} from 'frappe-ui'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Campo from '@/components/factura/Campo.vue'
import CampoLink from '@/components/factura/CampoLink.vue'
import PanelLinea from '@/components/factura/PanelLinea.vue'
import PanelImpuesto from '@/components/factura/PanelImpuesto.vue'
import PanelFactura from '@/components/factura/PanelFactura.vue'
import SiiDetalleDialog from '@/components/sii/SiiDetalleDialog.vue'
import { deskUrl, fmtDateTime, siiLabel, siiRowTheme } from '@/composables/sii'
import {
  useFactura,
  TIPOS,
  df,
  estadoFactura,
  mensajeError,
  cuentaCorta,
  htmlATexto,
  textoAHtml,
} from '@/composables/factura'
import {
  formatDate,
  formatImporte,
  formatMoney,
  formatNumber,
} from '@/composables/informe'
import LucidePlus from '~icons/lucide/plus'
import LucideSave from '~icons/lucide/save'
import LucideCheck from '~icons/lucide/check'
import LucideEllipsis from '~icons/lucide/ellipsis'
import LucideFileText from '~icons/lucide/file-text'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideX from '~icons/lucide/x'
import LucidePaperclip from '~icons/lucide/paperclip'
import LucideCopy from '~icons/lucide/copy'
import LucideUndo2 from '~icons/lucide/undo-2'
import LucidePrinter from '~icons/lucide/printer'
import LucideFileDown from '~icons/lucide/file-down'
import LucideExternalLink from '~icons/lucide/external-link'
import LucideBan from '~icons/lucide/ban'
import LucideTrash2 from '~icons/lucide/trash-2'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideRotateCcw from '~icons/lucide/rotate-ccw'

const props = defineProps({
  name: { type: String, required: true },
  doctype: { type: String, default: 'Sales Invoice' },
})

const route = useRoute()
const router = useRouter()
const f = useFactura(props.doctype)
const t = TIPOS[props.doctype]
// Las búsquedas de enlaces (CampoLink) se hacen en nombre de este DocType.
provide('doctypeFactura', props.doctype)
const seleccion = ref(null)
const siiDialog = ref(false)
const dialogo = reactive({ abierto: false, titulo: '', mensaje: '', boton: '', tema: 'gray', accion: () => {} })

const contexto = computed(() => f.contexto || {})
const estado = computed(() => estadoFactura(f.doc))

const migas = computed(() => [
  { label: __(t.titulo), route: { name: t.lista } },
  { label: props.name === 'new' || f.esNuevo ? __('Nueva factura') : props.name, route: route.fullPath },
])

const puedeGuardar = computed(
  () =>
    (f.editable && (f.sucio || f.esNuevo)) ||
    (f.doc?.docstatus === 1 && f.permisos.write_on_submit && f.sucio),
)

// ERPNext guarda «No Remarks» cuando no hay observaciones.
const observaciones = computed(() => {
  const r = f.doc?.remarks || ''
  return r === 'No Remarks' ? '' : r
})

const direccionCorta = computed(() =>
  String(f.doc?.address_display || '')
    .replace(/<br\s*\/?>/gi, ', ')
    .replace(/<[^>]+>/g, '')
    .replace(/(,\s*)+/g, ', ')
    .replace(/^,\s*|,\s*$/g, ''),
)

const hayRelacionados = computed(
  () => (contexto.value.rectificativas || []).length || (contexto.value.adjuntos || []).length,
)

// Misma etiqueta y color que la columna SII de las listas.
const siiFila = computed(() => ({
  sii_estado: contexto.value.sii?.estado,
  sii_aplica: contexto.value.sii?.aplica,
  docstatus: f.doc?.docstatus,
}))

const tituloSeleccion = computed(() => {
  const s = seleccion.value
  if (!s) return ''
  const row = f.doc?.[s.tabla]?.find((r) => f.clave(r) === s.clave)
  return s.tabla === 'items'
    ? `${__('Línea')} ${row?.idx ?? ''}`
    : `${__('Impuesto')} ${row?.idx ?? ''}`
})

const num = (v) => formatNumber(v, Number.isInteger(Number(v) || 0) ? 0 : 2)
const dinero = (v) => formatMoney(v, f.doc?.currency)

/** Enlace a un documento: las facturas se abren en esta vista, el resto en el Desk. */
function enlaceDocumento(doctype, name) {
  if (TIPOS[doctype]) return { to: { name: TIPOS[doctype].ruta, params: { name } } }
  return { href: deskUrl(doctype, name), target: '_blank' }
}

function rutaFactura(name) {
  return { name: t.ruta, params: { name } }
}

// --- selección ---------------------------------------------------------------

function seleccionar(tabla, row) {
  const clave = f.clave(row)
  if (seleccion.value?.tabla === tabla && seleccion.value?.clave === clave) return
  seleccion.value = { tabla, clave }
}

function esSeleccion(tabla, row) {
  return seleccion.value?.tabla === tabla && seleccion.value?.clave === f.clave(row)
}

// La selección sobrevive a los recálculos (las filas nuevas toman `name` al guardar).
watch(
  () => f.doc,
  (doc) => {
    const s = seleccion.value
    if (!s || !doc) return
    const filas = doc[s.tabla] || []
    if (!filas.some((r) => f.clave(r) === s.clave)) seleccion.value = null
  },
)

// --- edición -------------------------------------------------------------------

function cambiarFila(row, campo, valor) {
  f.cambiar(campo, valor, { tabla: 'items', fila: f.clave(row) })
}

function cambiarNumero(row, campo, v) {
  const n = v === '' || v === null ? 0 : Number(v)
  if (Number.isNaN(n)) return
  cambiarFila(row, campo, n)
}

function anadirLinea() {
  const clave = f.anadirFila('items', { qty: f.doc.is_return ? -1 : 1 })
  seleccion.value = { tabla: 'items', clave }
}

function anadirImpuesto() {
  const clave = f.anadirFila('taxes', {
    charge_type: 'On Net Total',
    rate: 0,
    ...(t.compra ? { category: 'Total', add_deduct_tax: 'Add' } : {}),
  })
  seleccion.value = { tabla: 'taxes', clave }
}

// --- acciones --------------------------------------------------------------------

async function ejecutar(fn, ok) {
  try {
    const res = await fn()
    if (ok) toast.success(ok)
    if (res?.doc?.name && res.doc.name !== props.name && !res.doc.__islocal) {
      await router.replace(rutaFactura(res.doc.name))
    }
    return res
  } catch (e) {
    toast.error(mensajeError(e))
  } finally {
    dialogo.abierto = false
  }
}

const guardar = () => ejecutar(() => f.guardar(), __('Factura guardada'))
const modificar = () => ejecutar(() => f.modificar())

function confirmar(tipo) {
  const textos = {
    validar: {
      titulo: __('Validar la factura'),
      mensaje: __('Se contabiliza, recibe número definitivo y, si aplica, queda pendiente de enviar al SII. Después solo podrá anularse con una rectificativa o cancelándola.'),
      boton: __('Validar'),
      tema: 'gray',
      accion: () => ejecutar(() => f.validar(), __('Factura validada')),
    },
    cancelar: {
      titulo: __('Cancelar la factura'),
      mensaje: __('Se anula el asiento contable y, si estaba en el SII, queda una baja pendiente. La factura no se borra.'),
      boton: __('Cancelar factura'),
      tema: 'red',
      accion: () => ejecutar(() => f.cancelar(), __('Factura cancelada')),
    },
    eliminar: {
      titulo: __('Eliminar el borrador'),
      mensaje: __('El borrador se borra definitivamente.'),
      boton: __('Eliminar'),
      tema: 'red',
      accion: async () => {
        try {
          await f.eliminar()
          f.sucio = false
          toast.success(__('Borrador eliminado'))
          router.push({ name: t.lista })
        } catch (e) {
          toast.error(mensajeError(e))
        } finally {
          dialogo.abierto = false
        }
      },
    },
  }
  Object.assign(dialogo, textos[tipo], { abierto: true })
}

async function estadoCobro(status) {
  try {
    await call('spain_compliance.overrides.sales_invoice.set_cobro_status', {
      name: f.doc.name,
      status,
    })
    toast.success(__('Estado de cobro actualizado'))
    f.recargar()
  } catch (e) {
    toast.error(mensajeError(e))
  }
}

function abrir(url) {
  window.open(url, '_blank')
}

const icono = (c) => () => h(markRaw(c), { class: 'size-4' })

const menu = computed(() => {
  const d = f.doc
  if (!d) return []
  const nombre = encodeURIComponent(d.name || '')
  const guardada = !f.esNuevo
  const grupos = []

  const documento = []
  if (guardada) {
    documento.push(
      {
        label: __('Imprimir'),
        icon: icono(LucidePrinter),
        onClick: () => abrir(`/printview?doctype=${encodeURIComponent(f.doctype)}&name=${nombre}&trigger_print=1`),
      },
      {
        label: __('Descargar PDF'),
        icon: icono(LucideFileDown),
        onClick: () =>
          abrir(`/api/method/frappe.utils.print_format.download_pdf?doctype=${encodeURIComponent(f.doctype)}&name=${nombre}`),
      },
    )
  }
  if (f.permisos.create && guardada) {
    documento.push({
      label: __('Duplicar'),
      icon: icono(LucideCopy),
      onClick: () => router.push({ name: t.ruta, params: { name: 'new' }, query: { duplicar: d.name } }),
    })
  }
  if (f.permisos.create && d.docstatus === 1 && !d.is_return) {
    documento.push({
      label: t.compra ? __('Crear rectificativa (abono del proveedor)') : __('Crear rectificativa'),
      icon: icono(LucideUndo2),
      onClick: () => router.push({ name: t.ruta, params: { name: 'new' }, query: { rectificar: d.name } }),
    })
  }
  if (documento.length) grupos.push({ group: __('Documento'), items: documento })

  const cobro = []
  if (!t.compra && d.docstatus === 1 && !d.is_return && f.permisos.write_on_submit) {
    const perdida = ['Dudoso Cobro', 'Pérdida'].includes(d.status)
    if (!perdida && Number(d.outstanding_amount) > 0.01) {
      cobro.push(
        { label: __('Marcar dudoso cobro'), icon: icono(LucideTriangleAlert), onClick: () => estadoCobro('Dudoso Cobro') },
        { label: __('Marcar pérdida'), icon: icono(LucideTriangleAlert), onClick: () => estadoCobro('Pérdida') },
      )
    }
    if (perdida) {
      cobro.push({ label: __('Restaurar estado de cobro'), icon: icono(LucideRotateCcw), onClick: () => estadoCobro('clear') })
    }
  }
  if (cobro.length) grupos.push({ group: __('Estado de cobro'), items: cobro })

  const otros = []
  if (guardada) {
    otros.push({ label: __('Recargar'), icon: icono(LucideRefreshCw), onClick: () => f.recargar() })
    otros.push({
      label: __('Abrir en el escritorio'),
      icon: icono(LucideExternalLink),
      onClick: () => abrir(deskUrl(f.doctype, d.name)),
    })
  }
  if (f.permisos.cancel) {
    otros.push({ label: __('Cancelar factura'), icon: icono(LucideBan), theme: 'red', onClick: () => confirmar('cancelar') })
  }
  if (f.permisos.delete) {
    otros.push({ label: __('Eliminar borrador'), icon: icono(LucideTrash2), theme: 'red', onClick: () => confirmar('eliminar') })
  }
  if (otros.length) grupos.push({ group: __('Más'), items: otros })
  return grupos
})

// --- carga y salida ----------------------------------------------------------------

function iniciar() {
  if (props.name === 'new') {
    if (route.query.duplicar) return f.duplicar(String(route.query.duplicar))
    if (route.query.rectificar) return f.rectificar(String(route.query.rectificar))
    if (route.query.hito && route.query.pedido && !t.compra) {
      return f.desdeHito(String(route.query.pedido), String(route.query.hito))
    }
    return f.nueva({
      [t.tercero]: route.query[t.tercero] || undefined,
      company: route.query.company || undefined,
    })
  }
  return f.cargar(props.name)
}

function atajo(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    if (puedeGuardar.value) guardar()
  }
}

function alSalir(e) {
  if (!f.sucio) return
  e.preventDefault()
  e.returnValue = ''
}

onMounted(() => {
  iniciar()
  window.addEventListener('keydown', atajo)
  window.addEventListener('beforeunload', alSalir)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', atajo)
  window.removeEventListener('beforeunload', alSalir)
})

onBeforeRouteLeave(() => {
  if (f.sucio && !window.confirm(__('Hay cambios sin guardar. ¿Salir sin guardarlos?'))) return false
})
</script>

<style scoped>
/* La descripción de la línea crece con el texto. */
.descripcion-linea {
  field-sizing: content;
  min-height: 1.75rem;
}
</style>
