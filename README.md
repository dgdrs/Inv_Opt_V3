# Inventory Optimizer - Consumer Goods Supply Chain

A Python application for supply chain managers in the consumer goods industry to determine optimal inventory value per product family.

## Latest update: XYZ segmentation, responsive GUI, interactive charts, SKU Inspector

- **XYZ (demand-variability) segmentation** now runs alongside the existing ABC (value) classification. Each SKU's coefficient of variation (CV = std/mean of its Demand Plan) puts it into X (stable, CV ≤ 0.5), Y (variable, ≤ 1.0), or Z (erratic, > 1.0) — thresholds configurable via `xyz_thresholds` in settings. Per Section 6.4 of the methodology doc, the normal-distribution safety-stock model understates risk for erratic demand, so Y/Z-class SKUs get an explicit sigma uplift (`xyz_safety_multiplier`, default 1.0 / 1.15 / 1.3) applied everywhere sigma is used — required safety stock, achieved service level, and the Constraint optimizer's objective all reflect it consistently. XYZ class and CV are now included in every scenario's output and the Excel export.
- **Calculations now run on a background thread with a real progress bar.** Previously "Calculate All Scenarios" froze the whole window for 20-50+ seconds with no feedback. The GUI now stays responsive, shows live progress (As-Is → each family's Constraint optimization → Optimized), and disables just the relevant buttons while a run is in progress instead of locking up entirely.
- **Charts are now interactive.** Hover over any line/bar to see the exact value in a tooltip; click a legend entry to toggle that series on/off — handy once a chart has 6+ families or many SKUs on it. Uses `mplcursors` (new dependency), and degrades gracefully (no tooltips, everything else still works) if it isn't installed.
- **New "SKU Inspector" tab**: search/select any SKU, view and edit its master data (ABC class, lead time, safety days, MOQ, price, current inventory) right in the GUI, and see its As-Is methodology numbers (XYZ class, safety stock, required safety days, reorder point, achieved vs. target service level) plus a rolling 12-month projection chart recompute **instantly** — no Excel round-trip, no waiting for the full optimization pass. "Apply & Recalc This SKU" updates that SKU's As-Is view immediately; click the main Recalculate button afterwards to also flow the change into the budget-optimized Constraint/Optimized scenarios (those re-optimize jointly across the whole family, so a single-SKU shortcut isn't meaningful for them).

## Earlier update: forecast-error-based methodology

The core inventory math follows the standard DRP/MRP-style methodology in
[`inventory_projection_methodology_cpg.md`](inventory_projection_methodology_cpg.md)
(included in this package), instead of ad-hoc formulas. Concretely:

| Before | Now |
|---|---|
| Safety stock = `daily_demand × safety_days` (safety days just a fixed input) | Safety stock derived from **Forecast Accuracy** via the MAPE → MAD-proxy → σ heuristic, then `SS = z × σ` (z from the target service level) |
| No concept of a "risk horizon" | Safety stock and service level use **risk horizon = Lead Time + Review Period** (a commonly-forgotten term that materially undersizes safety stock if left out) |
| Order quantity = `max(MOQ, demand × 2)` (arbitrary) | Order quantity uses proper **MOQ rounding**: below MOQ → round up to MOQ; above MOQ → round up to the next MOQ multiple |
| Reorder point = `daily_demand × lead_time + safety_stock` | Reorder point = **actual planned demand during the lead-time window** (from the Demand Plan) + safety stock |
| "Expected service level" = `forecast_accuracy × (1 + safety_days/30)` (not a real probability) | Expected/achieved **Cycle Service Level** computed properly as `norm.cdf(safety_stock / σ)` |
| Optimized scenario used a hardcoded `CV = 0.5` | Optimized scenario uses the same forecast-error-based σ as everywhere else |
| Demand-over-horizon = `avg(12 months) × horizon_months` | Demand-over-horizon = **actual sum of the forecasted months in the window** (e.g. M, M+1, M+2 for a 3-month horizon), truncated (not inflated) near the end of the 12-month plan |

All three scenarios (As-Is, Constraint, Optimized) still work the same way conceptually — this update only replaces *how* safety stock, reorder points and order quantities are calculated, so the numbers are now statistically grounded instead of rule-of-thumb.

A new setting, **Review Period (days)** (default **7**, i.e. a weekly replenishment review cycle), is exposed in the GUI and in `inventory_settings.json`, and feeds into every scenario's risk horizon.

## Features

### Three Scenario Calculations:

1. **As-Is Scenario**: Projects inventory for the next 12 months using each SKU's *current* master-data safety days, lead time and MOQ — nothing is changed. Provides:
   - Alerts for stockouts/understock/overstock
   - The Cycle Service Level the current safety-days policy actually delivers, vs. target
   - Deviations from budget
   - Hints with a concrete recommended safety-days value per SKU where the target service level isn't met

2. **Constraint Scenario**: Optimizes safety days per SKU under a fixed budget constraint to maximize the average Cycle Service Level per family (via `scipy.optimize.minimize`, SLSQP).

3. **Optimized Scenario**: No budget constraint — shows the inventory (and required budget) needed per family to hit each SKU's target service level.

### Key Features:

- **Data Input**: Excel file with a separate tab per data type
- **Realistic Sample Data**: 100 SKUs with realistic consumer-goods parameters
- **Visualization**: All scenarios visualized (including stacked-by-family views) for the past 12 and future 12 months, right on each scenario's own tab plus a Comparison tab
- **Settings Management**: Settings saved in `inventory_settings.json`, editable via the GUI, with a "Recalculate" button for instant what-if changes
- **Export**: Main output visible in the GUI; full detail exportable to Excel

## Data Requirements

The application expects an Excel file with the following tabs:

1. **SKU_Master**: SKU, ABC_Classification, Production_Leadtime_Days, Safety_Days_of_Supply, Min_Order_Qty, Price_EUR
2. **Inventory_History**: SKU, Month, Inventory (past 12 months + Current)
3. **Demand_Plan**: SKU, Month, Demand (next 12 months, named `M_01` ... `M_12`)
4. **Forecast_Accuracy**: SKU, Month, Accuracy (past 12 months, 0-1)
5. **Product_Families**: SKU, Product_Family
6. **Budget**: Product_Family, Month, Budget_EUR (next 12 months)

`Min_Order_Qty` also doubles as the lot-size increment for order rounding above the MOQ (the data model doesn't carry a separate case/pallet size).

## Installation

```bash
pip install -r requirements.txt
python run_inventory_optimizer.py
```

On Windows you can instead just double-click **`run_inventory_optimizer.bat`** — it checks for Python and the required packages, installs anything missing, and opens the GUI directly.

## Usage

1. **Load Data**: Click "Browse" to select your Excel file, or "Load Sample Data" for the built-in 100-SKU sample
2. **Adjust Settings**: Service level targets per ABC class, and the review period (days between replenishment decisions)
3. **Calculate Scenarios**: Click "Calculate All Scenarios" — runs in the background with a progress bar, so the GUI stays responsive
4. **View Results**: Each scenario tab has its own interactive charts (hover for values, click a legend entry to toggle a series); the Comparison tab lines them all up
5. **Inspect/Edit a SKU**: Use the "SKU Inspector" tab to search for any SKU, tweak its master data, and see its As-Is numbers + chart update instantly
6. **Export Results**: Detailed SKU- and family-level output to Excel (includes ABC and XYZ classification)
7. **Recalculate**: Change a setting (or apply a SKU Inspector edit), click "Recalculate" to flow it through all three scenarios

## Settings (`inventory_settings.json`)

- `default_service_levels`: target Cycle Service Level per ABC class (A/B/C)
- `safety_days_range`: min/max bounds used by the Constraint scenario's optimizer
- `review_period_days`: time between replenishment decisions (default **7**, one week) — combined with each SKU's lead time to form the safety-stock "risk horizon". Change this in the GUI or in the JSON file to match how often the business actually reviews/reorders (e.g. 30 for a monthly cycle).
- `xyz_thresholds`: `{"x_max": 0.5, "y_max": 1.0}` — coefficient-of-variation cutoffs for X/Y/Z demand-variability classification
- `xyz_safety_multiplier`: `{"X": 1.0, "Y": 1.15, "Z": 1.3}` — extra safety-stock margin applied for less predictable (Y/Z) demand classes
- `optimization_tolerance`, `max_iterations`: optimizer settings
- `currency`: display currency symbol

## Testing

```bash
python test_application.py   # assertion-based checks on all three scenarios
python run_test.py           # full narrative run with sample output tables
```

Both run headlessly (no GUI/tkinter required) against the built-in sample data generator.

## Technical Details

### Architecture:
- **app.py**: GUI (tkinter)
- **calculator.py**: scenario calculations — the methodology-based engine described above
- **visualizer.py**: matplotlib plotting
- **data_generator.py**: sample data generation

### Dependencies:
pandas, numpy, matplotlib, scipy, openpyxl, tkinter, mplcursors (interactive chart tooltips — optional, degrades gracefully if missing)

## License

This application is provided as-is for supply chain management purposes.
