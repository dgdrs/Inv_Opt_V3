# How SKU_001's Numbers Were Calculated (Regenerated)

This replaces the earlier walkthrough. Two things changed in the app since that version:
1. **Demand-over-horizon now uses the actual forecasted months** (e.g. M + M+1 + M+2), not the 12-month average scaled up.
2. **Review Period default is now 7 days** (1 week) instead of 30, and is a global, changeable setting.

Every number below comes from re-running the actual calculator code against SKU_001's real inputs. Section references (e.g. "Section 6.3") point to `inventory_projection_methodology_cpg.md`.

---

## 1. Raw inputs for SKU_001 (unchanged)

| Field | Value |
|---|---|
| Product Family | Beverages |
| ABC Classification | B → target Cycle Service Level = **95%** |
| Production Lead Time | 38 days |
| Safety Days of Supply (given/current policy) | 22 days |
| Min Order Qty (MOQ) | 889 units |
| Price | €2.25 |
| Current Inventory (starting point) | 758 units |

**Demand Plan** (units/month)

| M_01 | M_02 | M_03 | M_04 | M_05 | M_06 | M_07 | M_08 | M_09 | M_10 | M_11 | M_12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 499 | 421 | 522 | 357 | 263 | 327 | 416 | 503 | 327 | 400 | 393 | 317 |

12-month average = 395.42 units/month → average daily demand = 13.18 units/day (this average is still used for converting the *given* 22 safety-days policy into units — see Step 4 — and is unrelated to the fix below).

**Forecast Accuracy** (past 12 months, average) = **85.6%**

---

## 2. Risk horizon (Section 5) — now uses the 7-day default

```
review_period_days = 7   (was 30; now a global default, changeable in Settings)
risk_horizon_months = round((38 + 7) / 30) = round(1.5) = 2 months
```
For SKU_001 this happens to still round to 2 months (same as the old 30-day default gave) — but for shorter-lead-time SKUs the shorter review period now produces a tighter (smaller) horizon across the board; see the table in the app-update summary.

## 3. The fix: actual demand over the horizon, not an average (Sections 4.2 & 6.3)

**Old (incorrect) approach:**
```
demand_over_horizon = avg_demand(all 12 months) × horizon_months = 395.42 × 2 = 790.83
```

**New approach — sum the REAL forecasted months in the window:**
```
horizon window = the next 2 months starting now = [M_01, M_02] = [499, 421]
demand_over_horizon = 499 + 421 = 920
```
Because M_01 and M_02 both happen to be above-average months, the real near-term signal (920) is noticeably higher than the flat annual estimate (790.83) would have implied — exactly the kind of gap this fix was meant to close.

## 4. Forecast-error sigma (Section 4.2 & 6.3)

```
MAPE        = 1 - avg_FA = 1 - 0.8563 = 0.1437  (14.4%)
MAD_proxy   = MAPE × demand_over_horizon = 0.1437 × 920 = 132.17
sigma_proxy = MAD_proxy × 1.25 = 165.22
```
(Previously, with the old averaging approach: MAD_proxy = 0.1437×790.83 = 113.62, sigma = 142.02 — noticeably smaller.)

## 5. z-factor (Section 6.1) — unchanged

```
target_CSL (class B) = 95%  →  z = norm.ppf(0.95) = 1.6449
```

## 6. Safety Stock actually used ("As-Is": from the given 22 safety days) — unchanged

This conversion doesn't involve the horizon/sigma fix at all — it's just `days × daily demand`:
```
asis_safety_stock = 13.18 × 22 = 289.97 units
```

## 7. Service level the current policy actually delivers (Section 10) — **now more honest**

```
achieved_z   = asis_safety_stock / sigma_proxy = 289.97 / 165.22 = 1.7551
achieved_CSL = norm.cdf(1.7551) = 0.9604  →  96.0%
```
This dropped from the old value of **97.9%** to **96.0%**. That's a real improvement, not a regression: the old number was inflated because it measured the 289.97-unit buffer against an artificially-smoothed annual-average demand uncertainty. Measured against the SKU's actual near-term demand (which is running above its own annual average right now), the same buffer covers less risk — 96.0% is the more trustworthy figure. It's still above the 95% target, so no service-level hint is raised for this SKU.

## 8. What Safety Stock *should* be, to hit 95% exactly

```
required_safety_stock = z × sigma_proxy = 1.6449 × 165.22 = 271.76 units
required_safety_days  = 271.76 / 13.18  = 20.62 days
```
(Old value: 17.72 days.) The given policy (22 days) still comfortably clears this — consistent with the 96.0% achieved vs. 95% target.

## 9. Reorder Point (Section 9) — unchanged

The Reorder Point was never affected by this bug; it already summed actual demand over its own (shorter) lead-time-only window:
```
lead_time_months = round(38/30) = 1 month  →  window = [M_01] = 499
reorder_point = 499 + 289.97 = 788.97
```

---

## 10. The 12-month rolling projection (Sections 3 & 12) — unchanged

The rolling order-trigger logic compares projected inventory against `asis_safety_stock` (289.97), which didn't change — so this table is identical to before:

| Month | Demand | Inventory before order | Order triggered? | Order Qty (MOQ-rounded) | Inventory after |
|---|---:|---:|:---:|---:|---:|
| Start | – | – | – | – | **758** |
| M_01 | 499 | 259.0 | ✅ Yes | 889 | 1,148.0 |
| M_02 | 421 | 727.0 | No | 0 | 727.0 |
| M_03 | 522 | 205.0 | ✅ Yes | 889 | 1,094.0 |
| M_04 | 357 | 737.0 | No | 0 | 737.0 |
| M_05 | 263 | 474.0 | No | 0 | 474.0 |
| M_06 | 327 | 147.0 | ✅ Yes | 889 | 1,036.0 *(⚠ Overstock alert)* |
| M_07 | 416 | 620.0 | No | 0 | 620.0 |
| M_08 | 503 | 117.0 | ✅ Yes | 889 | 1,006.0 |
| M_09 | 327 | 679.0 | No | 0 | 679.0 |
| M_10 | 400 | 279.0 | ✅ Yes | 889 | 1,168.0 |
| M_11 | 393 | 775.0 | No | 0 | 775.0 |
| M_12 | 317 | 458.0 | No | 0 | 458.0 |

---

## 11. Constraint scenario (budget-optimized safety days)

Beverages still has ~46% budget headroom (M_01: actual €108,297 vs. budget €201,663), so the optimizer pushes SKU_001's safety days up — now to **45 days** (was 39 before this fix, within the same 5–60 day bound), because the optimizer's own service-level objective now also uses the corrected, windowed sigma:

```
safety_stock  = 13.18 × 45           = 593.12 units
reorder_point = 499 + 593.12         = 1,092.12 units
achieved_CSL  = norm.cdf(593.12/165.22) ≈ 0.9998  → 99.98%
```

## 12. Optimized scenario — required days now vary month to month

Unlike the As-Is snapshot above (evaluated once, "as of now"), the Optimized scenario recomputes Safety Stock **every month**, each time using the actual demand in that month's own forward-looking window:

| Month | Demand | Horizon window | Demand over horizon | σ | Required SS | Required days* |
|---|---:|---|---:|---:|---:|---:|
| M_01 | 499 | [M_01, M_02] | 920 | 165.22 | 271.76 | 16.3 |
| M_02 | 421 | [M_02, M_03] | 943 | 169.35 | 278.55 | 19.9 |
| M_03 | 522 | [M_03, M_04] | 879 | 157.85 | 259.65 | 14.9 |
| M_04 | 357 | [M_04, M_05] | 620 | 111.34 | 183.14 | 15.4 |
| M_05 | 263 | [M_05, M_06] | 590 | 105.95 | 174.28 | 19.9 |
| M_06 | 327 | [M_06, M_07] | 743 | 133.43 | 219.47 | 20.1 |
| M_07 | 416 | [M_07, M_08] | 919 | 165.04 | 271.46 | 19.6 |
| M_08 | 503 | [M_08, M_09] | 830 | 149.05 | 245.17 | 14.6 |
| M_09 | 327 | [M_09, M_10] | 727 | 130.56 | 214.75 | 19.7 |
| M_10 | 400 | [M_10, M_11] | 793 | 142.41 | 234.24 | 17.6 |
| M_11 | 393 | [M_11, M_12] | 710 | 127.50 | 209.73 | 16.0 |
| M_12 | 317 | **[M_12] only** | **317** | 56.93 | 93.64 | **8.9** |

*\*"Required days" here divides by that month's **own** daily demand (Optimized scenario's convention), while the As-Is figure in Step 8 divides by the **12-month average** daily demand — a minor inconsistency between the two scenarios' unit-conversion choice, which is why M_01's 16.3 days here doesn't exactly match Step 8's 20.62 days even though both months use the identical 271.76-unit Required Safety Stock. Worth knowing if you compare the two side by side.*

The visible drop at M_12 (8.9 days) is an edge effect, not a genuine best-practice recommendation for that month: the Demand Plan only runs 12 months, so by M_12 there's only 1 real forecasted month left inside the (nominally 2-month) risk-horizon window — the window gets truncated rather than filled, so the uncertainty estimate for that last month is necessarily incomplete. In a live system this would be resolved once month 13's demand plan becomes available (rolling-horizon planning); it's a natural limitation of evaluating the last few periods of any fixed 12-month plan.

Family-wide, hitting every Beverages SKU's target service level this way now needs **€17,508/month** (was €21,918) — still far below the ~€200k nominal Beverages budget.

---

## Summary: SKU_001 across all three scenarios (regenerated)

| | As-Is (given policy) | Constraint (budget-optimized) | Optimized (M_01 snapshot) |
|---|---:|---:|---:|
| Safety Days | 22 (given) | 45 (optimizer) | ~16–20 (varies by month; 8.9 at the M_12 tail edge-effect) |
| Safety Stock (units) | 289.97 | 593.12 | 271.76 (M_01) |
| Reorder Point (units) | 788.97 | 1,092.12 | — |
| Achieved / Target CSL | 96.0% / 95% | 99.98% / 95% | 95% / 95% (by construction) |
