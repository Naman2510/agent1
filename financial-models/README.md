# Financial Modeling Suite — Three Institutional-Grade Models

Built during a live research session (Sept 2026). Every model is a fully
formula-driven Excel workbook (`.xlsx`) — no hardcoded outputs — grounded in
real, sourced financial data with every assumption explicitly flagged and
cited on a dedicated **Sources & Assumptions** tab inside each file.

| # | Model | File | Real company / companies |
|---|---|---|---|
| 1 | Full 3-statement operating model + DCF | [`01_three_statement_dcf/NIKE_3-Statement_DCF_Model.xlsx`](01_three_statement_dcf/NIKE_3-Statement_DCF_Model.xlsx) | NIKE, Inc. (NYSE: NKE) |
| 2 | Hypothetical sponsor LBO | [`02_lbo_model/CrackerBarrel_LBO_Model.xlsx`](02_lbo_model/CrackerBarrel_LBO_Model.xlsx) | Cracker Barrel Old Country Store, Inc. (NASDAQ: CBRL) |
| 3 | Hypothetical M&A accretion/dilution | [`03_ma_accretion_dilution/VFC_UAA_MA_Model.xlsx`](03_ma_accretion_dilution/VFC_UAA_MA_Model.xlsx) | VF Corporation (NYSE: VFC) acquiring Under Armour, Inc. (NYSE: UAA) |

See **[AUDIT_REPORT.md](AUDIT_REPORT.md)** for the full self-audit: the
scoring rubric, every bug found and fixed during verification, and the
final grade for each model.

## What's inside each workbook

### 1. NIKE — 3-Statement Model + DCF
- **Income Statement, Balance Sheet, Cash Flow Statement**, fully linked:
  FY2024A-FY2025A actuals + FY2026E-FY2030E projections.
- **Debt Schedule** with a revolving credit facility: a dynamic draw/paydown
  and cash-sweep mechanic against a minimum-cash policy.
- **DCF Valuation**: CAPM-based WACC build-up, 5-year unlevered FCF,
  Gordon Growth + Exit Multiple terminal value, and two 5×5 sensitivity
  grids (WACC × terminal growth; WACC × exit multiple).
- **Football Field** valuation chart across four methodologies (DCF ×2,
  trading comparables, 52-week range).
- Balance sheet balances to floating-point-zero in every single period.

### 2. Cracker Barrel — Hypothetical Sponsor LBO
- **Sources & Uses** with an entry multiple derived from an offer premium.
- **4-tranche debt stack** (Revolver / Term Loan A / Term Loan B / Senior
  Notes) with mandatory amortization and a TLB-then-TLA cash-flow sweep.
- **5-year operating model** and free-cash-flow build.
- **Returns Analysis**: exit waterfall, IRR/MOIC, and two sensitivity
  tables (exit year × exit multiple; entry premium × exit multiple).
- Base case: ~9.2x entry EV/EBITDA, 4.5x opening leverage, **14.4% IRR /
  1.96x MOIC** over a 5-year hold — a realistic, moderate-leverage outcome,
  not an engineered "home run."

### 3. VF Corp / Under Armour — Hypothetical Strategic Combination
- **Standalone financials** for both companies, side by side.
- **Purchase price allocation & goodwill**: fair-value intangible step-up,
  deferred tax liability, goodwill as the balancing plug.
- **Pro forma combined income statement** with synergy phase-in and
  financing adjustments (new acquisition debt, foregone items).
- **Accretion/(dilution) analysis** vs. VFC's standalone EPS, 3 years out.
- **Sensitivity**: cash/stock mix × synergy realization; offer premium ×
  cash mix.
- Base case is **dilutive** (-19.9% Year 1, improving to -5.9% by Year 3) —
  a realistic outcome for a partly stock-funded deal with phasing synergies,
  not forced to look artificially accretive.

## Conventions used throughout

- **Blue** text = hardcoded input / sourced actual. **Black** = same-sheet
  formula. **Green** = cross-sheet formula link. **Yellow fill** = a key
  output or the single most important assumption cell on a tab.
- Every hardcoded number is either cited (with the real source) or flagged
  `ESTIMATE`/`ASSUMPTION` with a rationale, visible as a cell comment or in
  an adjacent notes column and consolidated on each workbook's
  **Sources & Assumptions** tab.
- A `Cover` tab in every workbook explains the model's purpose, is marked
  clearly as **hypothetical** where applicable, and states it is not
  investment advice.

## A known, disclosed environment limitation

This session's sandboxed container could not get LibreOffice's headless
recalculation to complete (confirmed via isolated testing down to a
2-cell trivial file — a hang unrelated to model complexity or circularity).
Every formula in all three workbooks was instead independently verified
using the `formulas` Python library (a from-scratch Excel formula
evaluation engine), and every cell's computed value was then written back
into the `.xlsx` as a cached value alongside its formula — so the numbers
display immediately on open, and every formula recalculates normally the
moment the file is opened in Excel, Google Sheets, or LibreOffice Desktop.
