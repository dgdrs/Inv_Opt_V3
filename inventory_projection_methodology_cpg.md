# Inventory Projection Methodology for Consumer Goods
## A Reference Specification for Given-Demand-Plan Inventory Projection (Designed for AI/Model Consumption)

**Scope note:** This document assumes a **Demand Plan is already provided** (period-by-period volume, with a stated forecast accuracy metric). It intentionally excludes demand forecasting methodology itself. It focuses on everything that happens *after* the demand number exists: turning that demand plan plus lead time, MOQ, safety stock, service level and demand-uncertainty inputs into a projected, period-by-period inventory balance and a replenishment plan.

---

## 1. Purpose and Framing

Inventory projection is the supply-side translation of a demand plan into:
1. A **time-phased projected inventory balance** (how much stock will be on hand/in transit at each future point in time).
2. A **replenishment/order plan** (when and how much to order, constrained by lead time and MOQ).
3. A **risk buffer** (safety stock) sized to the combination of demand uncertainty, forecast inaccuracy, and supply (lead time) uncertainty, calibrated to a target service level.

This is structurally the same logic used in **Distribution Requirements Planning (DRP)** and **MRP-style time-phased planning**: <cite index="63-1,63-2">it uses a time-phased approach to project inventory depletion dates and plan replenishment orders, reducing the costs of ordering, transporting, and holding stock, applying the same explosion logic that MRP uses for materials but to distribution nodes.</cite> <cite index="68-1">The core mechanic is a projected-on-hand calculation that rolls forward on-hand inventory plus scheduled receipts and planned order receipts minus requirements period by period.</cite>

---

## 2. Core Data Model / Input Variables

This is the variable dictionary an AI model should expect as structured input. Naming is kept consistent throughout this document.

| Variable | Definition | Typical unit | Source |
|---|---|---|---|
| `t` | Time bucket index (day/week/month) | period | planning calendar |
| `D_t` | Demand Plan quantity for period t (**given, external input**) | units | Demand Plan |
| `FA` or `FA_t` | Forecast Accuracy for the plan (e.g., 1 − MAPE), overall or per period/horizon | % | given |
| `MAPE`, `WMAPE`, `MAD`, `RMSE`, `Bias` | Forecast error metrics (see Section 4) | % or units | historical forecast-vs-actual |
| `σ_D` | Standard deviation of demand or of forecast error | units/period | historical data or derived from FA |
| `LT` | Replenishment lead time (order placement → goods available) | periods (days/weeks) | supplier/plant master data |
| `σ_LT` | Standard deviation (variability) of lead time | periods | historical PO performance |
| `R` | Review period / order interval (time between replenishment decisions) | periods | planning policy |
| `CSL` | Target Cycle Service Level | % | policy (by SKU/segment) |
| `FR` | Target Fill Rate | % | policy (often contractual with retail customers) |
| `z` | Service-level (safety) factor derived from CSL, standard normal | dimensionless | lookup / NORM.INV |
| `SS` | Safety Stock | units | calculated |
| `OH_t` | On-hand inventory at start of period t | units | inventory master/ERP |
| `IT_t` | Stock in Transit / pipeline inventory at period t (open POs, not yet received) | units | ERP open-PO table |
| `SR_t` | Scheduled Receipts in period t (open POs due to arrive) | units | ERP |
| `PAB_t` | Projected Available Balance at end of period t | units | calculated |
| `ROP` | Reorder Point | units | calculated |
| `MOQ` | Minimum Order Quantity | units or cases | supplier contract |
| `LotSize` | Case pack / production batch increment | units | supplier/plant master data |
| `NR_t` | Net Requirement in period t | units | calculated |
| `POR_t` | Planned Order Receipt in period t | units | calculated |
| `POL_t` | Planned Order Release (= POR shifted back by LT) | units | calculated |
| `DOS_t` / `WOS_t` | Days/Weeks of Supply at period t | days/weeks | calculated |

---

## 3. Core Rolling Inventory Projection Formula (the "engine")

This is the central equation. It is the same logic used in DRP/MRP time-phased planning: <cite index="68-1">Projected on-hand for period t equals on-hand from the prior period plus scheduled receipts in period t plus planned order receipts in period t, minus requirements for that period.</cite>

**Formula (period-by-period):**

```
PAB_t = PAB_(t-1) + SR_t + POR_t − D_t
```

Where, if `PAB_t` (before adding any new planned order) is projected to fall **below the Safety Stock threshold**, the logic triggers a new planned order:

```
IF (PAB_(t-1) + SR_t − D_t) < SS  THEN
    NR_t = SS + D_t − PAB_(t-1) − SR_t        (Net Requirement)
    POR_t = round_to_MOQ_and_LotSize(NR_t)     (see Section 7)
    POL_t = POR_t placed at period (t − LT)    (Planned Order Release, offset by lead time)
```

This mirrors formal DRP logic: <cite index="67-1">scheduled receipts (inbound shipments already in transit) and the projected available balance (current inventory) offset gross requirements; when projected inventory falls below the safety stock threshold, the system generates a planned order.</cite> <cite index="65-1,65-2,65-3">DRP lets the planner set inventory control parameters such as safety stock and then calculates the time-phased inventory requirements, consolidating demand across periods with the available sources of supply.</cite>

**Time bucket granularity:** <cite index="67-2">weekly buckets suit most distribution environments, balancing planning precision with computational efficiency; daily buckets may be necessary for high-velocity or perishable products, while monthly buckets are sufficient for slow-moving items with stable demand.</cite> This is a relevant design choice for consumer goods, where fresh/short-shelf-life SKUs need finer granularity than slow-moving pantry items.

**Total inventory position** (used for reorder-point triggering, not the same as physical on-hand) should include stock in transit:

```
Inventory_Position_t = OH_t + IT_t − Backorders_t
```

---

## 4. Forecast Accuracy: Translating a Given Accuracy into a Usable Error Term

The Demand Plan arrives with a stated forecast accuracy. This section defines how to turn that into the statistical inputs the safety-stock formulas need. <cite index="29-3,29-4">Forecast error for a period is defined as actual minus forecast; the recommended practice is to calculate the variance of demand used in safety-stock formulas from this forecast error rather than from raw historical demand variability, so that safety stock rises and falls in step with actual forecast performance.</cite> <cite index="29-6">This is grounded in the fact that standard deviation is mathematically related to Mean Absolute Deviation (MAD), and MAD is in turn related to WMAPE, one common way of measuring forecast error.</cite>

### 4.1 Standard error metrics

- **MAPE** (Mean Absolute Percentage Error): <cite index="33-2">average of |Actual − Forecast| / Actual, expressed as a percentage.</cite>
- **WMAPE / WAPE** (weighted / volume-weighted MAPE): <cite index="34-1,34-2">sum of |Actual − Forecast| divided by the sum of Actual, expressed as a percentage — preferred over plain MAPE when a catalog is skewed toward a few high-volume SKUs, since it avoids the distortion low-volume SKUs cause in plain MAPE.</cite>
- **MAD** (Mean Absolute Deviation, in units): <cite index="34-3">the average absolute difference between forecast and actual values, expressed in units rather than percentage — useful directly for setting safety stock or reorder buffers.</cite>
- **RMSE** (Root Mean Square Error): <cite index="34-4">emphasizes larger forecast errors by squaring the deviations before averaging.</cite>
- **Forecast Bias**: <cite index="28-1,28-2">the difference between forecast and sales; a positive bias comes from overestimating sales, a negative bias from underestimating sales — this shows directional skew but not the magnitude of the error when reviewing many items or long periods.</cite>

**Recommended default for consumer goods reference targets**: <cite index="33-3">for CPG brands at SKU level, 80–85% accuracy is typical for the most important products, 70–80% overall, and accuracy has diminishing returns — moving from 60% to 80% materially improves operations, while moving from 85% to 90% is expensive and may not be worth it.</cite>

### 4.2 Converting a single "Forecast Accuracy %" into an error magnitude

If the Demand Plan only carries a single blended accuracy figure (e.g., "FA = 82%", i.e., MAPE ≈ 18%) rather than a full historical error distribution, use this heuristic proxy so the number is directly usable in the safety-stock formulas of Section 6:

```
MAPE = 1 − FA
MAD_proxy_t  = MAPE × D_t              (period error in units)
σ_proxy      ≈ MAD_proxy × 1.25        (normal-distribution relation between MAD and standard deviation, σ ≈ MAD × √(π/2))
```

This is explicitly an approximation for when a full historical error series is not available; <cite index="32-1,32-2">one accepted heuristic is to use the forecasted demand rather than the mean demand inside the variance expression, since the forecast error is very often correlated with the amount of upcoming variation — the greater the expected variation, the greater the typical forecast error.</cite> Where an actual historical forecast-vs-actual series exists, prefer computing **RMSE or MAD directly** over this proxy (see Section 6.3).

### 4.3 Important distinction: demand variability ≠ forecasting accuracy

These are frequently conflated, but they are different quantities and should not both be labeled "σ" in downstream formulas: <cite index="30-3,30-4">demand variability measures how demand deviates from its own ex-post average, while forecasting accuracy measures how a forecast deviates from actual demand — these are drastically different concepts, especially for seasonal, promotion-driven, or mid/long-term forecasts, and safety stock should in principle be tied to forecast error, not to raw demand variability.</cite>

---

## 5. Lead Time, Review Period, and the "Risk Horizon"

**Lead time (LT)**: <cite index="19-2">the full order-to-availability window, including not just supplier transit time but also internal delays such as order approval and receiving/put-away processing, and any "reorder delay" imposed by supplier order-acceptance schedules (e.g., a supplier only accepting orders on specific days).</cite> All of these components should be measured from **actual** historical performance, not quoted/nominal supplier lead times, because <cite index="19-2">suppliers often quote ideal lead times, but real-world delays from shipping, customs, or supplier capacity issues can significantly extend delivery windows.</cite>

**Review period (R)**: the interval between replenishment decisions (e.g., weekly planning cycle). This is frequently omitted from safety-stock formulas, which is a common and material error: <cite index="96-4">forgetting to include the review period in the risk calculation is one of the most common mistakes, because the review period has exactly the same effect as lead time — it expands the total exposure window ("risk-horizon") against which the buffer must protect.</cite>

**Risk horizon** = LT + R. All variability-based safety stock formulas in Section 6 should use this combined horizon, not lead time alone, whenever the process is periodic-review (which almost all CPG replenishment planning is, as opposed to true continuous review).

**Lead time variability (σ_LT)**: should be estimated from actual PO receipt data (quoted vs. actual delivery dates), but treated cautiously: <cite index="96-8,96-9,96-10">lead times are typically even less normally distributed than demand, and past lead-time performance is often a poor predictor of future performance — for example, a one-off logistics disruption or a newly installed supplier production line can make historical variability irrelevant going forward.</cite> A pragmatic alternative used in practice is a judgment-based **Supplier Reliability Rating** feeding a scenario/simulation approach rather than a pure statistical estimate.

---

## 6. Safety Stock — Formula Library (Increasing Sophistication)

Multiple formulas exist depending on which variability sources are present and how much data quality is available. Present them in order of increasing rigor; an AI system should default to the most rigorous one the available data supports.

### 6.1 z-Factor Reference Table (Cycle Service Level → z)

<cite index="10-3">Common Z-score values: 1.28 for a 90% service level, 1.65 for 95%, 1.96 for 97.5%, and 2.33 for 99%.</cite> (99.9% ≈ 3.09, standard normal table value.) <cite index="10-4">Most inventory planning software converts service level to Z automatically, but it can also be computed with the NORMSINV/NORM.INV function.</cite>

### 6.2 Basic variants (choose based on which side is more variable)

**A. Demand-variability only, fixed lead time:**
```
SS = z × σ_D × √(LT + R)
```
<cite index="15-2">Z is the z-score for the target cycle service level, σ_D is the demand standard deviation, and L is the lead time; when exposure spans multiple periods, volatility is scaled by the square root of the exposure length.</cite>

**B. Lead-time-variability only, stable demand:**
```
SS = z × D_avg × σ_LT
```
<cite index="13-1,13-2">This form is used when demand is stable but lead time fluctuates; Z represents the desired service level and σ_LT the standard deviation of lead time.</cite>

**C. Combined variability, independent (King's formula):**
```
SS = z × √[ (LT × σ_D²) + (D_avg² × σ_LT²) ]
```
<cite index="81-2">This combined-uncertainty formula generally produces a larger buffer than either demand-only or lead-time-only cases, reflecting the joint risk of both sources.</cite> <cite index="79-2,79-3">This is the definition most companies use, or a simplification of it: Z is the Gaussian z-factor translating a service-level target into a numeric factor; if lead-time variability is ignored, the formula collapses to the simpler demand-only version. The implicit assumption is that supply variability and demand variability are 100% independent — in practice this is often not valid, since supply lead times frequently lengthen exactly when demand is high.</cite>

**D. Combined variability, dependent (conservative, additive form):**
```
SS = z × σ_D × √LT  +  z × D_avg × σ_LT
```
<cite index="79-4">This alternative sums the two components directly rather than combining them via square-root-of-sum-of-squares, and is used when demand and lead-time variability move together (e.g., a supplier delays longer specifically during periods of high demand); it assumes the two sources are 100% dependent, so the true buffer typically lies somewhere between the King's-formula value and this more conservative sum.</cite>

### 6.3 Forecast-error-based safety stock (recommended default when a Demand Plan + accuracy is given)

Since a Demand Plan and its accuracy are explicitly given in this use case, the safety stock should be tied to **forecast error**, not raw historical demand variability:

```
SS = z × RMSE_(risk horizon)          (theoretically preferred replacement for σ_D)
   or
SS = k × MAE_(risk horizon)           (more robust in practice; k tuned via simulation, see 6.4)
```

<cite index="96-5">Replacing σ with RMSE is a straightforward, theoretically correct fix that ties the formula to actual forecasting accuracy instead of raw demand variability.</cite> Two refinements matter for consumer goods planning:

1. **Use the cumulative error over the full risk horizon, not the per-period error scaled by √(LT+R).** <cite index="96-6,96-7">The classical square-root-of-time scaling assumes each period's error is independent and identically distributed, which is often wrong; instead, the cumulative forecast error can be computed directly over the risk horizon without that independence assumption.</cite>
2. **Prefer MAE/MAD over RMSE in practice**, despite RMSE being the "textbook-correct" substitute for σ: <cite index="96-13">using MAE rather than RMSE typically yields a better inventory/service trade-off in practice, because MAE does not overreact to extreme forecast errors the way RMSE does — this avoids artificial safety-stock spikes that RMSE would trigger after one unusually large forecast miss.</cite>

### 6.4 Known limitations of the z-factor / normal-distribution assumption

Two structural weaknesses of every formula in 6.1–6.3 should be flagged when this methodology is fed into an AI system, since they materially affect reliability of the output:

- **z does not actually guarantee the stated Cycle Service Level in practice**, and CSL itself is a weak business metric: <cite index="96-16,96-18">the cycle service level is mathematically what z connects to — not fill rate, not order fill rate — and in practice these are not aligned: a policy could deliver a 60% cycle service level while still achieving a 90%+ fill rate; the cycle service level is also the most counter-intuitive service metric to use because different product-lead-time combinations get measured on different "cycles."</cite>
- **Demand and forecast-error distributions are usually not normal.** <cite index="96-20,96-21">Most demand distributions in practice are right-skewed, with many low-value observations and occasional large spikes — this fits a gamma-type shape much better than a normal curve; cumulative forecast error over the risk horizon looks closer to normal but is still not truly normal.</cite> For low-volume / intermittent-demand SKUs, <cite index="15-2">Poisson, Gamma, or Binomial distributions are recommended over the normal-curve approach, since a normal-curve model can meaningfully underestimate risk for spiky or zero-inflated demand patterns.</cite>
- **Best-practice remediation** (for a mature/AI-driven planning system): <cite index="96-22,96-23">rather than solving for a service-factor analytically, run historical simulations — using actual historical demand and forecast values rather than sampled theoretical distributions — to see how different safety-stock/buffer levels affect cost, inventory, and realized service, then pick the level that yields the best trade-off; this approach is more robust because it can directly incorporate real-world constraints such as MOQs, variable lead times, and production calendars.</cite>

---

## 7. MOQ and Lot-Size Rounding Logic

MOQs are a **hard supply-side constraint** applied *after* the net requirement is calculated; they do not change the underlying safety-stock or reorder-point math, but they change what actually gets ordered and therefore what the projected balance looks like.

**Rounding logic:**
```
IF NR_t <= 0:                Order_Qty_t = 0
ELSE IF NR_t <= MOQ:          Order_Qty_t = MOQ
ELSE:                         Order_Qty_t = ceiling(NR_t / LotSize) × LotSize   (rounded up to next case/pallet/batch multiple, and never below MOQ)
```

Two consequences to model explicitly in the rolling projection:

1. **MOQ-driven overstock**: whenever `MOQ > NR_t`, the excess (`MOQ − NR_t`) is carried forward into future periods' `PAB`, effectively acting as *unplanned* extra safety stock. <cite index="40-3">If the MOQ is significantly higher than demand over a given planning period, this materially inflates the resulting inventory level</cite> — this should be tracked as a distinct "MOQ excess" component so it isn't confused with intentional safety stock in reporting.
2. **MOQ interacts with review period and safety stock**: <cite index="96-19">the magnitude of the forecast errors, the risk-horizon, and the MOQ all jointly determine how far realized fill rate diverges from the nominal cycle service level target</cite> — so MOQ should be a required input to any fill-rate estimation or simulation, not treated as a separate downstream step.

**MOQ types to capture in the data model**: <cite index="43-1,43-2">fixed MOQ (a constant, stable order quantity, common where production or supplier agreements require consistent batch sizes, but prone to excess inventory if demand falls) versus variable MOQ (adjusted based on demand levels, production capacity, or supplier capability, reducing over/understocking risk but requiring more dynamic supplier coordination).</cite>

---

## 8. Stock in Transit / Pipeline Inventory

Pipeline (in-transit) inventory is purchased/produced stock that has left the source but not yet arrived — it is **owned but not yet available to sell/consume**, and must be included in the inventory *position* used for reorder decisions even though it is excluded from the *on-hand* balance used for days-of-supply-to-customer calculations.

**Standard formula:**
```
Pipeline_Inventory = Lead_Time × Demand_Rate
```
<cite index="47-1,47-2">For example, a 10-day lead time with 500 units/day of demand implies roughly 5,000 units of pipeline inventory in transit at any given time — this shows how much stock is moving through the supply chain and helps balance supply with demand.</cite>

In an actual planning system, prefer the **exact sum of open PO quantities with their expected receipt dates** (`SR_t` in Section 3) over this theoretical average, since real shipments are lumpy rather than continuous; the formula above is best used for high-level network/cash-tied-up estimates, not for period-by-period projection, where scheduled receipts by exact date should drive `SR_t`.

**Why it matters operationally:** <cite index="45-3">it's important to order new stock with enough lead time so that products can be shelved, manufactured, and shipped without delays, and average pipeline inventory scales directly with both order quantity and lead time.</cite> <cite index="51-3">Pipeline inventory sits alongside — but is distinct from — decoupling/safety stock, which exists specifically to protect against disruptions such as supplier shortages, production delays, or sudden demand increases that pipeline visibility alone cannot cover.</cite>

---

## 9. Reorder Point (Trigger Logic)

When a Demand Plan is available (as opposed to only an average historical demand rate), the reorder point should be computed from the **actual planned demand during the lead time window**, not a flat average:

```
Demand_During_LT = Σ (t = t0 to t0+LT) D_t            (sum of Demand Plan across the lead-time window)
ROP = Demand_During_LT + SS
```

This is the demand-plan-aware version of the standard formula: <cite index="18-1,18-2">Reorder Point = (delivery time in days × forecast demand for those days) + safety stock, where the demand forecast is the expected demand for the item over the relevant days/weeks/months.</cite> <cite index="24-4,24-5">A per-SKU reorder point should reflect each item's own demand velocity, lead-time variability, and risk tolerance rather than a single blanket threshold — using one threshold for all items causes stockouts on some and excess on others.</cite> In multi-node consumer-goods networks, <cite index="24-5">location-specific reorder points combined with in-transit visibility inside the ERP system prevent double-counting of pipeline stock and refine reorder timing.</cite>

---

## 10. Service Level Definitions — Cycle Service Level vs. Fill Rate

These two metrics are frequently used interchangeably in practice but are mathematically different, and mixing them up leads to mis-sized safety stock. Both should be carried as separate, explicitly-labeled fields in any planning data model.

| | Cycle Service Level (CSL) | Fill Rate (FR) |
|---|---|---|
| Definition | <cite index="58-1">the probability of NOT stocking out during a replenishment cycle</cite> | <cite index="58-1">the proportion of demand actually satisfied from stock</cite> |
| Formula | z-based, from normal-distribution safety-stock math | <cite index="58-2">units shipped from stock ÷ total units demanded × 100</cite> |
| Nature | <cite index="57-3">measures future probability (forward-looking planning metric)</cite> | <cite index="57-3">measures past performance (an actual, realized outcome)</cite> |
| Relationship | generally lower / more conservative | <cite index="59-2">fill rate is always higher than or equal to service level for the same inventory policy</cite> |
| Typical relationship magnitude | — | <cite index="58-3">a 95% cycle service level typically yields a 99%+ fill rate, because a stockout only affects the tail end of demand within a cycle — most units in that cycle are still fulfilled even when a stockout technically occurs</cite> |
| Common usage | supply-chain engineering / safety-stock sizing (ties directly to the z-score) | executive/customer reporting; retailer scorecards |

**A frequent and costly planning error**: <cite index="61-3">policies tuned to a 95% cycle service level and policies tuned to a 95% fill rate require dramatically different inventory levels, yet most ERP systems report only one of the two metrics — generically labeled "service level" — without specifying which; auditing which formula is actually configured is essential before trusting the number.</cite> <cite index="59-4">Fill rate also depends on order quantity in a way cycle service level does not, which matters when jointly optimizing reorder point and order quantity.</cite>

**CPG practice on segmentation**: <cite index="15-2">large consumer-goods and retail companies typically anchor safety-stock policy by SKU class rather than applying one uniform service level company-wide.</cite> Typical practice combines an **ABC (value/volume) × XYZ (demand volatility) matrix** to assign differentiated service-level targets — reserve higher CSL/FR targets (95–99%) for high-value, high-velocity, low-variability items, and accept lower targets for low-value or highly volatile tail SKUs.

---

## 11. Key Metrics & Formula Summary Table

A consolidated reference table, intended as the canonical lookup for an AI system generating or validating inventory-projection calculations.

| Metric | Formula | Notes |
|---|---|---|
| Forecast error (period) | `e_t = Actual_t − Forecast_t` | <cite index="29-3">basis for all downstream error metrics</cite> |
| MAPE | `avg( |Actual_t − Forecast_t| / Actual_t ) × 100` | <cite index="33-2">sensitive to low-volume/near-zero actuals</cite> |
| WMAPE / WAPE | `Σ|Actual_t − Forecast_t| / ΣActual_t × 100` | <cite index="34-2">preferred for skewed SKU portfolios</cite> |
| MAD | `avg( |Actual_t − Forecast_t| )` | in units; direct input to safety stock |
| RMSE | `sqrt( avg( (Actual_t − Forecast_t)^2 ) )` | penalizes large misses |
| Forecast Bias | `avg( Forecast_t − Actual_t )` | directional, not magnitude |
| Pipeline / Transit Inventory | `LT × Demand_Rate` (theoretical) or `Σ open PO qty` (actual) | <cite index="47-1">owned, not yet available</cite> |
| Safety Stock (basic) | `z × σ_D × √(LT+R)` | Section 6.2.A |
| Safety Stock (King's, combined) | `z × √(LT·σ_D² + D_avg²·σ_LT²)` | Section 6.2.C |
| Safety Stock (forecast-error based) | `k × MAE_(LT+R)` or `z × RMSE_(LT+R)` | Section 6.3, recommended default |
| Reorder Point | `Σ D_t (over LT) + SS` | Section 9 |
| Order Quantity (after MOQ/lot logic) | `max(MOQ, ceil(NR/LotSize) × LotSize)` | Section 7 |
| Projected Available Balance | `PAB_t = PAB_(t-1) + SR_t + POR_t − D_t` | Section 3 |
| Days/Weeks of Supply | `OH_t / avg_forward_daily(or weekly)_demand` | forward-looking coverage |
| Inventory Turnover | `COGS / Average_Inventory` | <cite index="76-2">standard financial efficiency ratio</cite> |
| Days Inventory Outstanding (DIO) | `(Average_Inventory / COGS) × Days_in_Period` or `Days_in_Period / Inventory_Turnover` | <cite index="70-1,70-3">alternative equivalent formulas</cite>; <cite index="71-4">retail benchmark ≈ 30–60 days, automotive ≈ 15–25 days (industry-specific)</cite> |
| Cycle Service Level | probability of no stockout in a cycle, tied to `z` | Section 10 |
| Fill Rate | `Units shipped from stock / Units demanded × 100` | Section 10 |

---

## 12. End-to-End Algorithm (Pseudocode for Implementation / AI Consumption)

```
INPUTS (per SKU-location):
    demand_plan[t]                  # given, external
    forecast_accuracy (or MAPE, or historical actual/forecast series)
    lead_time, lead_time_std
    review_period
    target_CSL  (or target_fill_rate)
    MOQ, lot_size
    on_hand, open_POs[ ] with receipt dates
    unit_cost, COGS (for DIO/turnover reporting)

STEP 1 — Derive error inputs
    IF historical actual-vs-forecast series available:
        compute MAD / RMSE / WMAPE directly (Section 4.1)
    ELSE:
        MAPE = 1 - forecast_accuracy
        MAD_proxy[t] = MAPE * demand_plan[t]
        sigma_proxy = MAD_proxy * 1.25                     # normal-distribution approximation

STEP 2 — Determine risk horizon
    risk_horizon = lead_time + review_period

STEP 3 — Compute Safety Stock
    z = lookup_z(target_CSL)                                # Section 6.1
    SS = choose_formula(available_data):
            - forecast-error based (preferred): k * MAE(risk_horizon) or z * RMSE(risk_horizon)
            - King's combined formula if only demand & LT variability known
            - basic demand-only formula as fallback
    # Optionally: validate/tune k via historical simulation (Section 6.4) instead of using z directly

STEP 4 — Compute Reorder Point
    demand_during_LT = sum(demand_plan[t0 : t0+lead_time])
    ROP = demand_during_LT + SS

STEP 5 — Roll the projection forward, period by period
    PAB[0] = on_hand
    FOR t in planning horizon:
        SR[t] = sum of open POs due to arrive in t
        projected_before_order = PAB[t-1] + SR[t] - demand_plan[t]
        IF projected_before_order < SS:
            NR[t] = SS + demand_plan[t] - PAB[t-1] - SR[t]
            order_qty = apply_MOQ_and_lotsize(NR[t], MOQ, lot_size)     # Section 7
            POR[t] = order_qty
            POL[t - lead_time] = order_qty                              # planned release, offset by LT
        ELSE:
            POR[t] = 0
        PAB[t] = PAB[t-1] + SR[t] + POR[t] - demand_plan[t]
        DOS[t] = PAB[t] / avg(demand_plan[t : t+30])                     # forward coverage

STEP 6 — Report KPIs
    inventory_turnover = COGS / average(PAB)
    DIO = days_in_period / inventory_turnover
    projected_fill_rate ≈ simulate or estimate from PAB vs demand_plan shortfall periods
    flag SKUs where DOS exceeds shelf-life or excess/obsolescence thresholds
```

---

## 13. Suggested Structured Output Schema (for downstream AI/optimization consumption)

```json
{
  "sku": "string",
  "location": "string",
  "period": "YYYY-WW or YYYY-MM-DD",
  "demand_plan": 0,
  "forecast_accuracy_input": 0.0,
  "derived_error_metrics": {
    "mape": 0.0, "wmape": 0.0, "mad": 0.0, "rmse": 0.0, "bias": 0.0
  },
  "lead_time_days": 0,
  "lead_time_std_days": 0,
  "review_period_days": 0,
  "safety_stock": 0,
  "safety_stock_method": "forecast_error_MAE | forecast_error_RMSE | kings_formula | demand_only | lead_time_only",
  "reorder_point": 0,
  "moq": 0,
  "lot_size": 0,
  "on_hand": 0,
  "stock_in_transit": 0,
  "scheduled_receipts": [{"date": "YYYY-MM-DD", "qty": 0}],
  "planned_order_receipts": [{"date": "YYYY-MM-DD", "qty": 0}],
  "planned_order_releases": [{"date": "YYYY-MM-DD", "qty": 0}],
  "projected_available_balance": [{"period": "", "value": 0}],
  "days_of_supply": 0,
  "target_cycle_service_level": 0.0,
  "target_fill_rate": 0.0,
  "projected_fill_rate": 0.0,
  "excess_obsolescence_flag": false
}
```

---

## 14. Excess, Obsolescence, and Working-Capital Considerations (Consumer Goods Specific)

Because MOQ rounding, safety stock, and forecast error all push inventory **above** the theoretical minimum, a consumer-goods inventory projection should also report the **downside risk** of that buffer, not just the stockout-protection side:

- <cite index="88-2,88-3">Working capital targets should be set explicitly (e.g., a target Days Inventory Outstanding derived from cash-flow capacity), and forecasting/production planning should be built to that constraint rather than allowing inventory to creep upward over time as a brand grows.</cite>
- <cite index="88-4">When finance sets a working-capital target that requires reducing inventory, operations and sales need to understand the resulting service-level and stockout-risk implications — this is a cross-functional trade-off, not a purely operational one.</cite>
- **Perishable / short-shelf-life buffers**: <cite index="87-3">redesigning safety stock and replenishment logic for temperature-controlled and shelf-life-constrained products is a distinct discipline aimed at improving fill rate while reducing spoilage and write-offs</cite> — a Days-of-Supply value that exceeds a SKU's shelf life should be flagged automatically (see the `excess_obsolescence_flag` field in Section 13).
- **The bullwhip effect** should be considered in any multi-echelon (DC → regional hub → store) consumer-goods network: <cite index="66-3">small changes in end-consumer demand can generate large swings in demand further up the distribution network as each node re-orders independently</cite> — this is a reason to drive replenishment planning off a single shared Demand Plan signal rather than letting each node forecast independently.

---

## 15. Summary of Method Selection Guidance

| Situation | Recommended Safety Stock Formula |
|---|---|
| Only a blended Forecast Accuracy % is given, no historical error series | MAD-proxy heuristic (Section 4.2) → basic or forecast-error formula |
| Full historical forecast-vs-actual series available | Forecast-error based: `k × MAE(risk horizon)` (Section 6.3), tuned via simulation if possible |
| Demand stable, lead time unreliable | Lead-time-only formula (6.2.B) |
| Both demand and lead time vary, independently | King's formula (6.2.C) |
| Both vary and are correlated (e.g., supplier slower exactly when demand spikes) | Additive/dependent formula (6.2.D) |
| Low-volume, intermittent, or spiky demand | Avoid normal-distribution z-based formulas; use Poisson/Gamma-based or simulation-based sizing |
| High-value / mature planning capability | Simulation-based / forecast-coverage-based dynamic safety stock (Section 6.4), rather than any static formula |

---

## Sources

- Netstock — Safety stock formula & standard deviation: https://www.netstock.com/blog/safety-stock-meaning-formula-how-to-calculate/
- Fishbowl — Safety stock formula variations: https://www.fishbowlinventory.com/blog/calculating-the-safety-stock-formula-6-variations-key-use-cases
- Slimstock — Safety stock formula & reorder point: https://www.slimstock.com/blog/safety-stock-inventory-qa/ ; https://www.slimstock.com/blog/reorder-point/ ; https://www.slimstock.com/blog/minimum-order-quantity/
- NetSuite — Safety stock & reorder point: https://www.netsuite.com/portal/resource/articles/inventory-management/safety-stock.shtml ; https://www.netsuite.com/portal/resource/articles/inventory-management/reorder-point-rop.shtml
- Linnworks — Safety stock formula: https://www.linnworks.com/blog/safety-stock-formula/
- ISM — Safety stock & reorder point: https://www.ism.ws/logistics/how-to-calculate-safety-stock/ ; https://www.ism.ws/logistics/reorder-point-formula-and-examples/
- Arkieva — Forecast accuracy and safety stock relationship: https://blog.arkieva.com/forecast-accuracy-safety-stocks/ ; cycle service level vs. fill rate: https://blog.arkieva.com/cycle-service-level-versus-fill-rate-service-level-part-two/
- Nicolas Vandeput — "Outgrowing the Safety Stock Formula": https://nicolas-vandeput.medium.com/outgrowing-the-safety-stock-formula-112e4efb9bf5
- Lokad — Safety stock and forecast-error variance heuristic: https://www.lokad.com/calculate-safety-stocks-with-sales-forecasting/ ; MOQ: https://www.lokad.com/minimum-order-quantity-moq/
- Planster — Forecast accuracy benchmarks: https://www.planster.io/blog/forecast-accuracy-benchmarks ; Service level vs fill rate: https://www.planster.io/blog/service-level-vs-fill-rate
- EasyReplenish — Demand forecast accuracy metrics: https://www.easyreplenish.com/blog/demand-forecast-accuracy-metrics-tools-industry-benchmarks
- EazyStock — Forecast accuracy & error: https://www.eazystock.com/blog/calculating-forecast-accuracy-forecast-error/
- Bloomreach / ShipBob / NetSuite / ISM / Bloom Group / Agrinventory — Reorder point formula guides (various)
- Descartes Finale / Inbound Logistics / DCL / Netstock / ShipBob — MOQ definition, formula, and inventory impact (various)
- BlueCart / QuickBooks / Inbound Logistics / Deskera / iGPS / Flowspace / Shipbots / Megaventory — Pipeline / in-transit inventory formula (various)
- Netstock / Planster / DCL Logistics / LineNow / GAINSystems / MetricGate — Fill rate vs. cycle service level (various)
- NetSuite / SoftEngine / TechTarget / sedApta / Wikipedia (Distribution resource planning) — DRP methodology
- ResearchGate — DRP case study (food company), Projected-On-Hand formula: https://www.researchgate.net/publication/343185416
- Wall Street Prep / Corporate Finance Institute / Tacto / WallStreetMojo / Agrinventory / Cleverence / Taulia / Eightx — Days Inventory Outstanding / Inventory Turnover (various)
- Doss / Abacum / Umbrex / Settle / NetSuite / Datarails — CPG working-capital and inventory-budgeting practice (various)
- Wikipedia — Inventory planning: https://en.wikipedia.org/wiki/Inventory_planning

*Note: this document synthesizes and paraphrases publicly available industry sources; formulas are standard operations-management/supply-chain formulas widely published across the sources above, not the copyrighted expression of any single source.*
