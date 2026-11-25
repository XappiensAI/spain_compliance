<div align="center">
  <img src="spain_compliance/public/images/logo.svg" width="72" alt="Spain Compliance" />
  <h1>Spain Compliance</h1>
  <p>Spanish accounting and compliance for <a href="https://github.com/frappe/erpnext">ERPNext</a>.</p>
  <p><i>Contabilidad española para ERPNext: Plan General Contable, correlatividad de facturas, series de facturas rectificativas, estados de cobro e interfaz de contabilidad.</i></p>
</div>

---

## Features

### Plan General Contable (PGC) tree
ERPNext organises the chart of accounts by `root_type` (Asset, Liability, Equity, Income, Expense). The Spanish PGC organises it by **nature** into groups 1–9, and a single group mixes asset and liability accounts (430 *Clientes* vs 438 *Anticipos de clientes*, 470 vs 475 *Hacienda Pública*, 570 *Caja* vs 521 *Deudas a corto plazo*).

Spain Compliance lets each account keep **its own** `root_type` regardless of its parent group, and patches ERPNext's Balance Sheet / Profit and Loss so they still balance:

- Company checkbox **Plan General Contable (árbol de 9 grupos)**.
- One-click conversion of an existing company chart to the 9-group tree (*Company → Contabilidad España → Convertir plan a PGC*): creates groups 1–9 and the two-digit subgroups, re-parents numbered accounts by prefix, deletes (or disables and re-parents) the leftover ERPNext standard accounts.
- Financial statements include the full PGC hierarchy for PGC companies; non-PGC companies are untouched.
- Each account's `root_type` comes from its **PGC nature** (`root_type_pgc`, longest prefix up to three digits): 470–474 asset and 475–479 liability, 438 liability, 407 asset, 50–52 liability, 53–54 asset… The bundled chart and new groups follow it. Companies loaded with an earlier chart can be checked and fixed with `spain_compliance.contabilidad.arbol_pgc.corregir_tipos_raiz` (dry run by default; it does not touch ledger entries).

### One ledger account per customer and supplier
In the PGC each customer gets its own 430 sub-account and each supplier its own 400/410 sub-account. When enabled on a PGC company, Spain Compliance creates that account with the next free number (`43000001`, `43000002`…) when the party is created, and assigns it on the party's *Accounts* table. Parties created before enabling it get their account on their next invoice, or in bulk from the Company form. Off by default. Details: [docs/cuentas-tercero.md](docs/cuentas-tercero.md).

### Invoice correlativity (series + date)
Spanish invoicing rules require consecutive numbering within each series, in chronological order. Spain Compliance enforces this on every Sales Invoice save: posting date cannot be in the future (the number is reserved on save, not on submit), and a higher number cannot have an earlier posting date than a lower number in the same company and naming series (drafts, submitted and cancelled all count). Details: [docs/correlatividad-facturas.md](docs/correlatividad-facturas.md).

### Dedicated series for credit notes (facturas rectificativas)
Spanish invoicing rules require rectifying invoices to use their own series. ERPNext copies the original invoice's series when creating a return. Configure **Serie de facturas rectificativas** on the Company (e.g. `{company_abbr}.R.YY.{#####}`) and every credit note created from the ordinary series is moved to it automatically, both server-side and in the form.

`{company_abbr}` resolves to the Company abbreviation when the invoice is named, so you can also use it in the ordinary series (e.g. `{company_abbr}.F.YY.{#####}`). It is not a stored field: ERPNext already uses that name internally.

### VAT book from the ledger

The VAT book, the VAT settlement draft and SII are computed **from the ledger's VAT entries** (no separate register). Each line is a GL movement on a tax account, enriched with the tax row's classification (type, VAT key, deductibility, withholding key), its taxable base and the invoice header. Exempt and 0 % invoices are added from their zero-quota tax rows, so the book covers every invoice and its quota total equals the tax accounts' movement. Tax rows are classified on the tax template; invoices copy that classification when their own row is empty. Unclassified taxes do not block posting unless the company asks for it. Details: [docs/libro-iva.md](docs/libro-iva.md).

### SII (Suministro Inmediato de Información)
Facturas emitidas and received are sent to the AEAT SII (schema 1.1) from the VAT book on the ledger, per company (*SII Configuracion*: test or production environment, start date, optional 15-minute automatic sending). Each invoice gets an *SII Registro* with status, CSV, errors, deadline (4 business days) and history. Supports A0, A1, cancellation (baja), per-invoice queries and whole-period reconciliation with the AEAT. Details: [docs/sii.md](docs/sii.md).

### Collection statuses: *Dudoso Cobro* and *Pérdida*
Two extra values on the native `Sales Invoice.status` field (no custom column), with buttons on the invoice form and preserved across ERPNext's automatic status recalculation while the invoice is outstanding. Optionally, invoices overdue by *N* months (Company → **Meses hasta Dudoso Cobro**) are moved to *Dudoso Cobro* by a daily job. Disabled (0) by default.

### Digital certificates
DocType **Certificado Digital** stores each company's PKCS#12 certificate (`.p12` / `.pfx`) for SII, Veri*factu and document signing. The file is a private attachment and the password an encrypted `Password` field. On save the certificate is opened with that password and its holder, NIFs, issuer, serial number and validity dates are filled in automatically. A daily job flags certificates as *Próximo a caducar* / *Caducado* and notifies System and Accounts Managers 60, 30, 15, 7 and 1 days before expiry. Integrations get the certificate with `get_certificado(company, uso)` or temporary PEM files with `archivos_pem(company, uso)`. Details: [docs/certificados-digitales.md](docs/certificados-digitales.md).

### Contabilidad UI
A [frappe-ui](https://github.com/frappe/frappe-ui) single-page app at `/contabilidad` (Apps screen → *Contabilidad*): dashboard with billing, cash-flow and receivables, and list views for invoices, payments, journal entries, parties, items and tax templates built on ERPNext DocTypes. Reports in the same app: libro diario (entry numbers for the fiscal year, filters and pagination), libro mayor (per account, running balance and balance chart), pérdidas y ganancias and balance laid out as the PGC *modelo normal* (masses, headings and line items down to sub-account, with prior-year comparison, waterfall, Sankey, balance-sheet masses and ratio checks), sumas y saldos by PGC level, libro de IVA and liquidación de IVA. Accounts are mapped to PGC headings by account number, not by the Desk tree. Verifactu remains a placeholder.

### Financial management
Treasury, costs and KPIs in the same app, computed live from ERPNext documents and the ledger: receivables and payables with ageing and supplier payment schedule (plus the ICAC average payment period), a weekly or monthly cash-flow forecast from invoices, unbilled orders and recurring cash movements, the PGC cash flow statement (indirect method, reconciled to the change in cash), production costs per work order (materials, labour and overheads, standard vs actual with quantity and price variances), stock valuation by PGC class (30–36), profitability by item, customer, project or any accounting dimension, and management KPIs (EBITDA, operating margin, liquidity, revenue per employee…). Details: [docs/gestion-financiera.md](docs/gestion-financiera.md).

## Compatibility

| Branch       | Frappe / ERPNext |
|--------------|------------------|
| `version-15` | v15              |
| `version-16` | v16              |

Requires **ERPNext** (installed automatically as a dependency). Building the UI requires **Node.js ≥ 20.11** (frappe-ui / Vite 5). On Frappe Cloud, select Node 20 or 22 in your bench *Dependencies*.

## Installation

### Frappe Cloud
Install from the Marketplace, or add `https://github.com/XappiensAI/spain_compliance` as a custom app and pick the branch that matches your Frappe version (`version-15` or `version-16`).

### Self-hosted bench

```bash
# Frappe / ERPNext 16 (use version-15 on v15)
bench get-app --branch version-16 https://github.com/XappiensAI/spain_compliance.git
bench --site <site> install-app spain_compliance
```

La plantilla **Spain - PGCE con números** queda disponible al crear o reemplazar el plan de una Company (España). Desde Company → *Contabilidad España* puedes **Reemplazar plan por PGC (borrar y cargar)** si vas a reimportar el mayor.

`bench build` runs the frontend build through the root `package.json` (`yarn build`).

## Configuration

Everything is configured per **Company**, section *Contabilidad España*:

| Field | Purpose |
|-------|---------|
| Plan General Contable (árbol de 9 grupos) | Enable per-account `root_type` and the PGC-aware financial statements. Set automatically by the conversion button. |
| Serie de facturas rectificativas | Naming series forced on credit notes. Empty = ERPNext default behaviour. |
| Meses hasta Dudoso Cobro | Months after due date before an unpaid invoice becomes *Dudoso Cobro*. 0 = off. |
| Régimen de IVA / Periodicidad del 303 / Prorrata / Modelo de cuentas anuales | Used by the VAT register and, later, by the tax forms. |
| Exigir clasificación fiscal | Block submitting invoices whose taxes are not classified. Drafts can still be saved. Off by default: the invoice posts and the VAT row is flagged as pending. |
| Crear cuenta contable al dar de alta clientes / proveedores | Per-party ledger accounts (PGC companies only). Off by default. |
| Prefijo / Dígitos de las cuentas | Account number prefix (`4300`, `4000`, `4100`…) and total length (8). |
| Plantilla media (section *Indicadores*) | Average headcount for revenue per employee. Empty = computed from Employee records. |

Warehouses and item groups have an optional *Clase de existencias* (PGC stock class) and workstation operating components a *Naturaleza del coste* (labour or overhead); see [docs/gestion-financiera.md](docs/gestion-financiera.md).

Access to `/contabilidad` is granted to *Accounts User*, *Accounts Manager* and *System Manager*.

## Documentation (Spanish)

- [docs/alcance.md](docs/alcance.md) — qué cubre ERPNext, Spain Compliance, Non Profit y qué queda fuera (PGC, partida doble, socios, presupuestos, proyectos)
- [docs/esfl.md](docs/esfl.md) — ESFL (RD 1491/2011), cuotas, certificados de donación y Modelo 182 (spec de implementación)
- [docs/correlatividad-facturas.md](docs/correlatividad-facturas.md) — correlatividad serie + fecha y Auto Repeat
- [docs/series-facturas-abono.md](docs/series-facturas-abono.md) — series de facturas y rectificativas
- [docs/cuentas-tercero.md](docs/cuentas-tercero.md) — cuentas 430/400 automáticas por cliente y proveedor
- [docs/libro-iva.md](docs/libro-iva.md) — libro de IVA sobre el mayor y clasificación fiscal
- [docs/gestion-financiera.md](docs/gestion-financiera.md) — tesorería, previsión, flujos de efectivo, costes de producción, existencias, rentabilidad e indicadores
- [docs/desarrollo.md](docs/desarrollo.md) — arquitectura y directrices de desarrollo
- [docs/publicacion.md](docs/publicacion.md) — cómo se mantiene y publica la app (GitLab canónico, GitHub público)

## Development

```bash
# Frontend (Node 22 recommended, see .nvmrc)
cd apps/spain_compliance/frontend
yarn
yarn dev      # Vite dev server proxied to your bench
yarn build    # → spain_compliance/public/frontend + www/contabilidad.html (both gitignored)

# Backend
bench --site <site> migrate
bench --site <site> clear-cache && bench restart

# Tests (use a disposable site with allow_tests, never production)
bench --site <test-site> set-config allow_tests true
bench --site <test-site> run-tests --app spain_compliance
```

Pre-commit (ruff, prettier, eslint): `pre-commit install`.

## Maintenance and publishing

The app is developed by [Xappiens](https://xappiens.com) against a production ERPNext and versioned in Xappiens' internal GitLab; this GitHub repository is the public distribution channel and receives the same code on every release. Details in [docs/publicacion.md](docs/publicacion.md).

## Contributing

Issues and pull requests are welcome. Please keep changes generic (no site-specific account names, series or credentials) and follow [docs/desarrollo.md](docs/desarrollo.md).

## License

[MIT](license.txt) © Xappiens and contributors.
