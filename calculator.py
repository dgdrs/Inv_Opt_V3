#!/usr/bin/env python3
"""
Calculator Module for Inventory Optimization Application
Handles all scenario calculations with proper inventory logic:
- Demand subtracts from inventory (sales)
- Supply adds to inventory after lead time (replenishment)
- Minimum Order Quantity per SKU

METHODOLOGY NOTE
-----------------
The core inventory-projection math (safety stock, reorder point, MOQ rounding,
risk horizon) follows "Inventory Projection Methodology for Consumer Goods"
(inventory_projection_methodology_cpg.md). Section references below point back
to that document:

  - Section 3  : Rolling PAB engine (PAB_t = PAB_(t-1) + SR_t + POR_t - D_t)
  - Section 4.2: Forecast Accuracy -> MAPE -> MAD-proxy -> sigma-proxy heuristic
  - Section 5  : Risk horizon = Lead Time + Review Period
  - Section 6.1: z-factor from target Cycle Service Level (via norm.ppf)
  - Section 6.3: Forecast-error based Safety Stock, cumulative over risk horizon
                 (not scaled by sqrt(horizon), per the methodology's guidance)
  - Section 7  : MOQ / lot-size rounding of the net requirement
  - Section 9  : Reorder Point = demand during the lead-time window + Safety Stock
  - Section 10 : Cycle Service Level, computed via norm.cdf(SS / sigma)

We only have a single blended "Forecast Accuracy" per SKU (not a full historical
forecast-vs-actual series), so Section 4.2's MAPE/MAD-proxy heuristic is used
throughout rather than directly-computed RMSE/MAD.
"""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from scipy.optimize import minimize, Bounds
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')


class InventoryCalculator:
    def __init__(self, settings):
        self.settings = settings

    # ------------------------------------------------------------------
    # Methodology helpers (see module docstring for section references)
    # ------------------------------------------------------------------

    def _review_period_days(self):
        """Time between replenishment decisions. Forgetting this is flagged in
        the methodology (Section 5) as one of the most common safety-stock
        mistakes, since it expands the risk horizon just like lead time does.
        Global setting, changeable in the GUI / inventory_settings.json;
        defaults to 1 week (7 days)."""
        return self.settings.get('review_period_days', 7)

    @staticmethod
    def _risk_horizon_months(lead_time_days, review_period_days):
        """Risk horizon = Lead Time + Review Period (Section 5), in whole months."""
        return max(1, round((lead_time_days + review_period_days) / 30))

    @staticmethod
    def _lead_time_months(lead_time_days):
        return max(1, round(lead_time_days / 30))

    @staticmethod
    def _lookup_z(target_service_level):
        """Convert a target Cycle Service Level into a z-factor (Section 6.1).
        Uses the standard-normal inverse CDF, which is what the z-table in the
        methodology (1.28/1.65/1.96/2.33 for 90/95/97.5/99%) is derived from."""
        sl = min(max(target_service_level, 0.5), 0.999)
        return norm.ppf(sl)

    @staticmethod
    def _demand_over_window(demand_plan, start_index, window_months):
        """Sum of the ACTUAL forecasted Demand Plan values for a forward-looking
        window (e.g. a 3-month window starting at M is M + M+1 + M+2) -- not an
        average month scaled up by the window length. Truncated to whatever the
        Demand Plan actually covers if the window runs past the end of it."""
        end_index = min(start_index + window_months, len(demand_plan))
        return sum(demand_plan[start_index:end_index])

    def _classify_xyz(self, demand_plan):
        """Demand-variability segmentation (X/Y/Z) via coefficient of variation
        (CV = std/mean of the Demand Plan), to run alongside the existing
        value-based ABC classification -- standard ABC x XYZ segmentation
        practice. Thresholds are a global setting (default X <= 0.5, Y <= 1.0,
        Z > 1.0), changeable in inventory_settings.json."""
        arr = np.array(demand_plan, dtype=float)
        mean = arr.mean() if len(arr) else 0
        if mean <= 0:
            return 'Z', float('inf')
        cv = float(arr.std() / mean)
        thresholds = self.settings.get('xyz_thresholds', {'x_max': 0.5, 'y_max': 1.0})
        if cv <= thresholds.get('x_max', 0.5):
            return 'X', cv
        elif cv <= thresholds.get('y_max', 1.0):
            return 'Y', cv
        return 'Z', cv

    def _xyz_multiplier(self, xyz_class):
        """Extra safety-stock margin for less-predictable demand classes.
        Section 6.4 of the methodology flags that the normal-distribution
        safety-stock model understates risk for erratic/spiky demand -- rather
        than silently absorbing that bias, Y/Z-class SKUs get an explicit,
        configurable uplift applied to sigma (and therefore to every formula
        derived from it: required safety stock, achieved service level, and
        the Constraint optimizer's objective)."""
        mult = self.settings.get('xyz_safety_multiplier', {'X': 1.0, 'Y': 1.15, 'Z': 1.3})
        return mult.get(xyz_class, 1.0)

    @staticmethod
    def _forecast_error_sigma(demand_over_horizon, forecast_accuracy, xyz_multiplier=1.0):
        """Forecast-error-based demand uncertainty over the risk horizon
        (Sections 4.2 & 6.3). Forecast Accuracy is treated as a MAPE proxy
        (MAPE = 1 - FA), applied to the *actual* summed Demand Plan across the
        risk horizon (not a single period's average demand scaled by
        sqrt(horizon) or multiplied out by the horizon length -- the
        methodology flags that independence assumption as often wrong), then
        MAD -> sigma via the standard relation sigma ~= MAD * 1.25. An XYZ
        safety multiplier (Section 6.4) can widen this for erratic demand."""
        fa = min(max(forecast_accuracy, 0.01), 0.999)
        mape = 1 - fa
        mad_proxy = mape * max(demand_over_horizon, 0)
        return mad_proxy * 1.25 * xyz_multiplier

    def _safety_stock(self, demand_plan, start_index, forecast_accuracy, lead_time_days, target_service_level, xyz_multiplier=1.0):
        """Forecast-error based Safety Stock (Section 6.3, recommended default
        when a Demand Plan + a Forecast Accuracy figure is given, as is the
        case here). demand_plan/start_index give the actual forecasted demand
        for the risk-horizon window (e.g. M, M+1, M+2 for a 3-month horizon),
        rather than an average month multiplied by the horizon length."""
        horizon = self._risk_horizon_months(lead_time_days, self._review_period_days())
        demand_over_horizon = self._demand_over_window(demand_plan, start_index, horizon)
        sigma = self._forecast_error_sigma(demand_over_horizon, forecast_accuracy, xyz_multiplier)
        z = self._lookup_z(target_service_level)
        return z * sigma

    @staticmethod
    def _reorder_point(demand_plan, start_index, lead_time_months, safety_stock):
        """Reorder Point = demand during the lead-time window + Safety Stock
        (Section 9), using the actual planned demand rather than a flat average."""
        end_index = min(start_index + lead_time_months, len(demand_plan))
        demand_during_lt = sum(demand_plan[start_index:end_index])
        return demand_during_lt + safety_stock

    @staticmethod
    def _apply_moq(net_requirement, moq):
        """MOQ rounding logic (Section 7). Orders below the MOQ are rounded up
        to the MOQ; larger orders are rounded up to the next MOQ multiple (used
        here as a simple stand-in for a separate case/lot size, since the data
        model doesn't carry one)."""
        if net_requirement <= 0:
            return 0
        if moq is None or moq <= 0:
            return net_requirement
        if net_requirement <= moq:
            return moq
        return math.ceil(net_requirement / moq) * moq

    def _achieved_service_level(self, safety_stock, demand_plan, start_index, forecast_accuracy, lead_time_days, xyz_multiplier=1.0):
        """Cycle Service Level actually delivered by a given Safety Stock
        (inverse of Section 6.3 / Section 10: CSL = norm.cdf(SS / sigma)),
        using the actual demand-plan window (see _safety_stock)."""
        horizon = self._risk_horizon_months(lead_time_days, self._review_period_days())
        demand_over_horizon = self._demand_over_window(demand_plan, start_index, horizon)
        sigma = self._forecast_error_sigma(demand_over_horizon, forecast_accuracy, xyz_multiplier)
        if sigma <= 0:
            return 1.0
        return float(norm.cdf(safety_stock / sigma))

    # ------------------------------------------------------------------
    # Scenario orchestration
    # ------------------------------------------------------------------

    def calculate_all_scenarios(self, processed_data, budget_data, families, family_skus, progress_callback=None):
        """Calculate all three scenarios.

        progress_callback(fraction: float, message: str), if given, is called
        at coarse checkpoints so a caller (e.g. a GUI running this on a
        background thread) can show progress instead of freezing."""
        def _report(fraction, message):
            if progress_callback:
                progress_callback(fraction, message)

        scenarios = {}

        _report(0.02, "Calculating As-Is scenario...")
        scenarios['as_is'] = self.calculate_as_is_scenario(
            processed_data, budget_data, families, family_skus
        )

        _report(0.35, "As-Is done. Optimizing Constraint scenario...")
        scenarios['constraint'] = self.calculate_constraint_scenario(
            processed_data, budget_data, families, family_skus, scenarios['as_is'],
            progress_callback=progress_callback
        )

        _report(0.85, "Constraint done. Calculating Optimized scenario...")
        scenarios['optimized'] = self.calculate_optimized_scenario(
            processed_data, families, family_skus
        )

        _report(1.0, "All scenarios complete.")
        return scenarios
    
    def calculate_sku_as_is(self, sku, family, price, abc, lead_time, safety_day, min_order,
                             current, monthly_demand, future_months_sorted, avg_fa, target_sl):
        """Per-SKU As-Is projection + methodology diagnostics: XYZ class,
        safety stock (current policy + what it should be), achieved Cycle
        Service Level, Reorder Point, and the 12-month rolling MOQ-rounded
        replenishment projection with any alerts for this one SKU.

        This is the actual per-SKU engine behind calculate_as_is_scenario
        below -- pulled out on its own so the GUI's SKU Inspector tab can
        call it directly for an instant single-SKU what-if recompute without
        re-running the full scenario (and its Constraint-scenario budget
        optimization) for every keystroke.
        """
        xyz_class, demand_cv = self._classify_xyz(monthly_demand)
        xyz_mult = self._xyz_multiplier(xyz_class)

        avg_demand = np.mean(monthly_demand) if monthly_demand else 0
        daily_demand_avg = avg_demand / 30
        lead_time_months = self._lead_time_months(lead_time)

        # Safety stock implied by the SKU's CURRENT (given) safety-days policy
        asis_safety_stock = daily_demand_avg * safety_day

        # What Safety Stock *should* be to hit the target service level (uses
        # the actual forecasted demand for the risk-horizon window starting
        # at "now", not the 12-month average multiplied by the horizon length)
        required_safety_stock = self._safety_stock(monthly_demand, 0, avg_fa, lead_time, target_sl, xyz_mult)
        required_safety_days = required_safety_stock / daily_demand_avg if daily_demand_avg > 0 else safety_day

        # Cycle Service Level actually delivered by the current policy
        expected_sl = self._achieved_service_level(asis_safety_stock, monthly_demand, 0, avg_fa, lead_time, xyz_mult)

        reorder_point = self._reorder_point(monthly_demand, 0, lead_time_months, asis_safety_stock)

        service_level_hint = None
        if expected_sl < target_sl * 0.95:
            service_level_hint = {
                'SKU': sku,
                'Family': family,
                'Current_SL': expected_sl,
                'Target_SL': target_sl,
                'Suggestion': (
                    f"Increase safety days from {safety_day:.0f} to "
                    f"~{required_safety_days:.0f} to reach the target service level"
                )
            }

        # --- Rolling projection (Section 3 / Section 12) ---
        inventory = [current]
        inventory_value = [current * price]
        supply_orders = []
        sku_alerts = []

        for i, month in enumerate(future_months_sorted):
            demand = monthly_demand[i] if i < len(monthly_demand) else 0

            projected_before_order = inventory[-1] - demand

            order_qty = 0
            if projected_before_order < asis_safety_stock:
                net_requirement = asis_safety_stock + demand - inventory[-1]
                order_qty = self._apply_moq(net_requirement, min_order)
                supply_orders.append({
                    'Month': month,
                    'Order_Qty': order_qty,
                    'Lead_Time_Days': lead_time
                })

            inventory_after = projected_before_order + order_qty

            if inventory_after < 0:
                sku_alerts.append({
                    'SKU': sku, 'Family': family, 'Month': month, 'Type': 'Stockout',
                    'Message': f"Stockout! Inventory ({inventory_after:.0f}) below 0"
                })
            elif inventory_after < asis_safety_stock:
                sku_alerts.append({
                    'SKU': sku, 'Family': family, 'Month': month, 'Type': 'Understock',
                    'Message': f"Inventory ({inventory_after:.0f}) below safety stock ({asis_safety_stock:.0f})"
                })

            if inventory_after > demand * 3:
                sku_alerts.append({
                    'SKU': sku, 'Family': family, 'Month': month, 'Type': 'Overstock',
                    'Message': f"Inventory ({inventory_after:.0f}) exceeds 3 months demand ({demand * 3:.0f})"
                })

            inventory.append(inventory_after)
            inventory_value.append(inventory_after * price)

        return {
            'inventory': inventory,
            'inventory_value': inventory_value,
            'demand': monthly_demand,
            'supply_orders': supply_orders,
            'safety_stock': asis_safety_stock,
            'required_safety_stock': required_safety_stock,
            'reorder_point': reorder_point,
            'expected_service_level': expected_sl,
            'target_service_level': target_sl,
            'price': price,
            'family': family,
            'abc': abc,
            'xyz': xyz_class,
            'demand_cv': demand_cv,
            'min_order_qty': min_order,
            'lead_time': lead_time,
            'safety_days': safety_day,
            'alerts': sku_alerts,
            'service_level_hint': service_level_hint
        }

    def calculate_as_is_scenario(self, data, budget_data, families, family_skus):
        """
        As-Is Scenario: project inventory using the CURRENT master-data safety
        days, lead time and MOQ, unchanged. Demand subtracts from inventory
        each month; whenever projected inventory would drop below the SKU's
        (given) safety stock, a replenishment order is planned, sized via MOQ
        rounding (Section 7), and received in the same rolling step (Section 3
        / Section 12: the engine has full demand-plan visibility, so planned
        receipts are timed to exactly cover the shortfall).

        The scenario also reports the Cycle Service Level the CURRENT safety
        days actually deliver (Section 10), compared to the SKU's target, so
        gaps can be flagged as hints/alerts. Per-SKU math lives in
        calculate_sku_as_is() above; this method just loops over every SKU
        and aggregates the results (budget deviations, family totals).
        """
        # Get future months (should be M_01, M_02, ..., M_12)
        demand_columns = [col for col in data.columns if col.startswith('Demand_')]
        future_months = [col.replace('Demand_', '') for col in demand_columns]
        
        # Sort months properly
        future_months_sorted = sorted(future_months, key=lambda x: int(x.replace('M_', '')))
        
        # Get forecast accuracy (use average of past months)
        fa_columns = [col for col in data.columns if col.startswith('FA_')]
        
        # Calculate inventory projection for each SKU
        sku_projections = {}
        alerts = []
        budget_deviations = {}
        service_level_hints = []
        
        # Initialize budget tracking
        for family in families:
            budget_deviations[family] = {}
        
        for _, row in data.iterrows():
            sku = row['SKU']
            family = row['Product_Family']
            price = row.get('Price_EUR', 0)
            abc = row.get('ABC_Classification', 'C')
            lead_time = row.get('Production_Leadtime_Days', 0)
            safety_day = row.get('Safety_Days_of_Supply', 0)
            min_order = row.get('Min_Order_Qty', 0)
            target_sl = self.settings['default_service_levels'].get(abc, 0.95)
            current = row.get('Current_Inventory', 0)
            
            monthly_demand = [row.get(col, 0) for col in demand_columns]
            
            fa_values = [row.get(col, 0) for col in fa_columns if row.get(col, 0) > 0]
            avg_fa = np.mean(fa_values) if fa_values else 0.9
            
            result = self.calculate_sku_as_is(
                sku, family, price, abc, lead_time, safety_day, min_order,
                current, monthly_demand, future_months_sorted, avg_fa, target_sl
            )
            
            sku_projections[sku] = result
            alerts.extend(result['alerts'])
            if result['service_level_hint']:
                service_level_hints.append(result['service_level_hint'])
        
        # Calculate budget deviations
        for family in families:
            family_skus_list = family_skus.get(family, [])
            
            for i, month in enumerate(future_months_sorted):
                total_value = sum(
                    sku_projections[sku]['inventory_value'][i+1] 
                    for sku in family_skus_list 
                    if sku in sku_projections
                )
                budget = budget_data.loc[family, f'Budget_{month}'] if f'Budget_{month}' in budget_data.columns else 0
                deviation = total_value - budget
                deviation_pct = (deviation / budget * 100) if budget > 0 else 0
                
                budget_deviations[family][month] = {
                    'Actual': total_value,
                    'Budget': budget,
                    'Deviation': deviation,
                    'Deviation_Pct': deviation_pct
                }
        
        # Aggregate by family
        family_projections = {}
        for family in families:
            family_skus_list = family_skus.get(family, [])
            
            aggregated_inv = []
            aggregated_value = []
            for i in range(len(future_months_sorted) + 1):
                total_inv = sum(
                    sku_projections[sku]['inventory'][i] 
                    for sku in family_skus_list 
                    if sku in sku_projections
                )
                total_value = sum(
                    sku_projections[sku]['inventory_value'][i] 
                    for sku in family_skus_list 
                    if sku in sku_projections
                )
                aggregated_inv.append(total_inv)
                aggregated_value.append(total_value)
            
            family_projections[family] = {
                'inventory': aggregated_inv,
                'inventory_value': aggregated_value,
                'skus': family_skus_list
            }
        
        return {
            'sku_projections': sku_projections,
            'family_projections': family_projections,
            'alerts': alerts,
            'budget_deviations': budget_deviations,
            'service_level_hints': service_level_hints,
            'future_months': future_months_sorted,
            'type': 'as_is'
        }
    
    def calculate_constraint_scenario(self, data, budget_data, families, family_skus, as_is_scenario, progress_callback=None):
        """
        Constraint Scenario: Optimize safety days per SKU under a fixed budget
        constraint to maximize the average Cycle Service Level per family.
        The service level for a given safety-days value x is evaluated the
        same way as in the As-Is scenario: CSL = norm.cdf(safety_stock / sigma),
        with sigma coming from the forecast-error-based methodology
        (Sections 4.2 & 6.3 + the XYZ safety multiplier, Section 6.4),
        instead of an arbitrary fixed accuracy/CV.

        progress_callback(fraction, message), if given, is called after each
        family's optimization completes (scaled into the 0.35-0.85 range so it
        composes with calculate_all_scenarios' overall progress reporting).
        """
        fa_columns = [col for col in data.columns if col.startswith('FA_')]
        future_months = as_is_scenario.get('future_months', [])
        
        # Get current parameters + per-SKU forecast accuracy / demand plan / risk horizon / XYZ
        sku_params = {}
        sku_fa = {}
        sku_demand_plan = {}
        sku_horizon_months = {}
        sku_xyz = {}
        sku_xyz_mult = {}
        for _, row in data.iterrows():
            sku = row['SKU']
            sku_params[sku] = {
                'family': row['Product_Family'],
                'price': row['Price_EUR'],
                'abc': row['ABC_Classification'],
                'lead_time': row['Production_Leadtime_Days'],
                'safety_days': row['Safety_Days_of_Supply'],
                'min_order_qty': row.get('Min_Order_Qty', 0),
                'target_sl': self.settings['default_service_levels'].get(row['ABC_Classification'], 0.95)
            }
            
            fa_values = [row.get(c, 0) for c in fa_columns if row.get(c, 0) > 0]
            sku_fa[sku] = np.mean(fa_values) if fa_values else 0.9
            
            demand_plan = [row.get(f'Demand_{m}', 0) for m in future_months]
            sku_demand_plan[sku] = demand_plan
            
            sku_horizon_months[sku] = self._risk_horizon_months(row['Production_Leadtime_Days'], self._review_period_days())
            xyz_class, _ = self._classify_xyz(demand_plan)
            sku_xyz[sku] = xyz_class
            sku_xyz_mult[sku] = self._xyz_multiplier(xyz_class)
        
        # Optimization: For each family, optimize safety days
        optimized_params = {}
        family_results = {}
        num_families = len(families) or 1
        
        for family_idx, family in enumerate(families):
            family_skus_list = family_skus.get(family, [])
            
            if not family_skus_list:
                continue
            
            # Get budget for this family (average across months)
            family_budget = 0
            for month in future_months:
                budget_col = f'Budget_{month}'
                if budget_col in budget_data.columns and family in budget_data.index:
                    family_budget += budget_data.loc[family, budget_col]
            family_budget /= len(future_months)
            
            # Initial safety days
            initial_safety_days = [sku_params[sku]['safety_days'] for sku in family_skus_list]
            
            # Bounds for safety days
            bounds = Bounds(
                [self.settings['safety_days_range']['min']] * len(family_skus_list),
                [self.settings['safety_days_range']['max']] * len(family_skus_list)
            )
            
            # Optimization objective and constraints
            def budget_constraint(x, month_idx=0):
                """Calculate total inventory value for a given month"""
                total_value = 0
                for i, sku in enumerate(family_skus_list):
                    demand_col = f'Demand_{future_months[month_idx]}'
                    demand = data[data['SKU'] == sku][demand_col].iloc[0] if demand_col in data.columns else 0
                    
                    daily_demand = demand / 30
                    safety_stock = daily_demand * x[i]
                    cycle_stock = demand / 2
                    
                    total_inv = safety_stock + cycle_stock
                    total_value += total_inv * sku_params[sku]['price']
                
                return family_budget - total_value
            
            def objective(x):
                """Calculate negative average Cycle Service Level (Sections 6.3, 6.4 & 10)"""
                total_sl = 0
                for i, sku in enumerate(family_skus_list):
                    demand_plan = sku_demand_plan[sku]
                    # x[i] is a safety-DAYS decision variable; converting it to units
                    # uses the SKU's average daily demand (a plain unit conversion,
                    # unrelated to the forecast-error window used for sigma below)
                    daily_demand = np.mean(demand_plan) / 30 if demand_plan else 0
                    safety_stock = daily_demand * x[i]
                    
                    demand_over_horizon = self._demand_over_window(demand_plan, 0, sku_horizon_months[sku])
                    sigma = self._forecast_error_sigma(demand_over_horizon, sku_fa[sku], sku_xyz_mult[sku])
                    
                    if sigma > 0:
                        z = safety_stock / sigma
                        sl = norm.cdf(z)
                    else:
                        sl = 1.0
                    
                    total_sl += sl
                
                return -total_sl / len(family_skus_list)
            
            # Solve optimization
            try:
                result = minimize(
                    objective,
                    initial_safety_days,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=[
                        {'type': 'ineq', 'fun': lambda x: budget_constraint(x, 0)},
                        {'type': 'ineq', 'fun': lambda x: budget_constraint(x, len(future_months)//2)},
                        {'type': 'ineq', 'fun': lambda x: budget_constraint(x, -1)}
                    ],
                    options={'maxiter': self.settings['max_iterations']}
                )
                
                if result.success:
                    optimized_safety_days = result.x
                else:
                    optimized_safety_days = initial_safety_days
                    
            except Exception as e:
                print(f"Optimization failed for family {family}: {e}")
                optimized_safety_days = initial_safety_days
            
            # Store optimized parameters
            for i, sku in enumerate(family_skus_list):
                optimized_params[sku] = {
                    'safety_days': int(round(optimized_safety_days[i])),
                    'family': family
                }
            
            # Calculate projections with optimized parameters
            family_projection = self.calculate_family_projection(
                family, family_skus_list, optimized_params, data, future_months
            )
            family_results[family] = family_projection
            
            if progress_callback:
                fraction = 0.35 + 0.5 * ((family_idx + 1) / num_families)
                progress_callback(fraction, f"Optimized {family} ({family_idx + 1}/{num_families} families)")
        
        # Calculate SKU-level projections
        sku_projections = {}
        for sku in data['SKU']:
            family = sku_params[sku]['family']
            if family in family_results:
                sku_projections[sku] = self.extract_sku_projection(
                    sku, family_results[family], data, future_months, optimized_params,
                    sku_xyz.get(sku), sku_xyz_mult.get(sku, 1.0)
                )
        
        return {
            'sku_projections': sku_projections,
            'family_projections': family_results,
            'optimized_params': optimized_params,
            'future_months': future_months,
            'type': 'constraint'
        }
    
    def calculate_family_projection(self, family, family_skus_list, optimized_params, data, future_months):
        """Calculate projection for a family with optimized parameters"""
        demand_data = {}
        for sku in family_skus_list:
            row = data[data['SKU'] == sku].iloc[0]
            demand_data[sku] = [row.get(f'Demand_{m}', 0) for m in future_months]
        
        inventory = []
        inventory_value = []
        
        # Initial inventory
        initial_inv = 0
        initial_value = 0
        for sku in family_skus_list:
            row = data[data['SKU'] == sku].iloc[0]
            initial_inv += row.get('Current_Inventory', 0)
            initial_value += row.get('Current_Inventory', 0) * row['Price_EUR']
        
        inventory.append(initial_inv)
        inventory_value.append(initial_value)
        
        # Simplified projection
        for i, month in enumerate(future_months):
            total_inv = 0
            total_value = 0
            
            for sku in family_skus_list:
                row = data[data['SKU'] == sku].iloc[0]
                demand = demand_data[sku][i]
                price = row['Price_EUR']
                
                safety_days = optimized_params.get(sku, {}).get('safety_days', row['Safety_Days_of_Supply'])
                
                daily_demand = demand / 30
                safety_stock = daily_demand * safety_days
                cycle_stock = demand / 2
                
                total_inv += safety_stock + cycle_stock
                total_value += (safety_stock + cycle_stock) * price
            
            inventory.append(total_inv)
            inventory_value.append(total_value)
        
        return {
            'inventory': inventory,
            'inventory_value': inventory_value,
            'skus': family_skus_list
        }
    
    def extract_sku_projection(self, sku, family_projection, data, future_months, optimized_params, xyz_class=None, xyz_multiplier=1.0):
        """Extract SKU-level projection from family projection"""
        row = data[data['SKU'] == sku].iloc[0]
        family = row['Product_Family']
        price = row['Price_EUR']
        lead_time = row['Production_Leadtime_Days']
        
        demand = [row.get(f'Demand_{m}', 0) for m in future_months]
        avg_demand = np.mean(demand) if demand else 0
        
        fa_columns = [c for c in data.columns if c.startswith('FA_')]
        fa_values = [row.get(c, 0) for c in fa_columns if row.get(c, 0) > 0]
        avg_fa = np.mean(fa_values) if fa_values else 0.9
        
        if xyz_class is None:
            xyz_class, _ = self._classify_xyz(demand)
            xyz_multiplier = self._xyz_multiplier(xyz_class)
        
        safety_days = optimized_params.get(sku, {}).get('safety_days', row['Safety_Days_of_Supply'])
        min_order = row.get('Min_Order_Qty', 0)
        
        inventory = []
        inventory_value = []
        
        current_inv = row.get('Current_Inventory', 0)
        inventory.append(current_inv)
        inventory_value.append(current_inv * price)
        
        daily_demand = 0
        for i, month in enumerate(future_months):
            daily_demand = demand[i] / 30
            safety_stock = daily_demand * safety_days
            cycle_stock = demand[i] / 2
            
            total_inv = safety_stock + cycle_stock
            inventory.append(total_inv)
            inventory_value.append(total_inv * price)
        
        avg_daily_demand = avg_demand / 30
        safety_stock_units = avg_daily_demand * safety_days
        lead_time_months = self._lead_time_months(lead_time)
        
        return {
            'inventory': inventory,
            'inventory_value': inventory_value,
            'demand': demand,
            'safety_stock': safety_stock_units,
            'reorder_point': self._reorder_point(demand, 0, lead_time_months, safety_stock_units),
            'expected_service_level': self._achieved_service_level(safety_stock_units, demand, 0, avg_fa, lead_time, xyz_multiplier),
            'target_service_level': self.settings['default_service_levels'].get(row['ABC_Classification'], 0.95),
            'price': price,
            'family': family,
            'abc': row['ABC_Classification'],
            'xyz': xyz_class,
            'min_order_qty': min_order,
            'lead_time': lead_time,
            'safety_days': safety_days
        }
    
    def calculate_optimized_scenario(self, data, families, family_skus):
        """
        Optimized Scenario: No budget constraint - shows the inventory (and
        therefore budget) required to hit each SKU's target Cycle Service
        Level, using the forecast-error-based Safety Stock formula (Section
        6.3) over the SKU's own risk horizon (lead time + review period,
        Section 5) instead of an arbitrary fixed coefficient of variation.
        """
        demand_columns = [col for col in data.columns if col.startswith('Demand_')]
        future_months = [col.replace('Demand_', '') for col in demand_columns]
        future_months_sorted = sorted(future_months, key=lambda x: int(x.replace('M_', '')))
        
        fa_columns = [col for col in data.columns if col.startswith('FA_')]
        
        sku_projections = {}
        family_projections = {}
        required_budgets = {}
        
        for _, row in data.iterrows():
            sku = row['SKU']
            family = row['Product_Family']
            price = row['Price_EUR']
            abc = row['ABC_Classification']
            lead_time = row['Production_Leadtime_Days']
            safety_day = row['Safety_Days_of_Supply']
            min_order = row.get('Min_Order_Qty', 0)
            target_sl = self.settings['default_service_levels'].get(abc, 0.95)
            
            demand = [row.get(f'Demand_{m}', 0) for m in future_months_sorted]
            
            fa_values = [row.get(col, 0) for col in fa_columns if row.get(col, 0) > 0]
            avg_fa = np.mean(fa_values) if fa_values else 0.9
            
            horizon_months = self._risk_horizon_months(lead_time, self._review_period_days())
            z_score = self._lookup_z(target_sl)
            xyz_class, demand_cv = self._classify_xyz(demand)
            xyz_mult = self._xyz_multiplier(xyz_class)
            
            inventory = []
            inventory_value = []
            
            current_inv = row.get('Current_Inventory', 0)
            inventory.append(current_inv)
            inventory_value.append(current_inv * price)
            
            required_safety_stock = 0
            daily_demand = 0
            for i, month in enumerate(future_months_sorted):
                monthly_demand = demand[i]
                daily_demand = monthly_demand / 30
                
                # Actual forecasted demand over the upcoming risk horizon
                # (Section 6.3): the sum of the real Demand Plan values for
                # this window (e.g. M, M+1, M+2 for a 3-month horizon), not an
                # average month scaled up -- and truncated, not inflated, if
                # the window runs past the end of the 12-month plan.
                demand_over_horizon = self._demand_over_window(demand, i, horizon_months)
                
                sigma_demand = self._forecast_error_sigma(demand_over_horizon, avg_fa, xyz_mult)
                required_safety_stock = z_score * sigma_demand
                cycle_stock = monthly_demand / 2
                
                total_inv = required_safety_stock + cycle_stock
                total_inv = max(total_inv, current_inv)
                
                inventory.append(total_inv)
                inventory_value.append(total_inv * price)
                current_inv = total_inv
            
            lead_time_months = self._lead_time_months(lead_time)
            
            sku_projections[sku] = {
                'inventory': inventory,
                'inventory_value': inventory_value,
                'demand': demand,
                'safety_stock': required_safety_stock,
                'reorder_point': self._reorder_point(demand, 0, lead_time_months, required_safety_stock),
                'expected_service_level': target_sl,
                'target_service_level': target_sl,
                'price': price,
                'family': family,
                'abc': abc,
                'xyz': xyz_class,
                'demand_cv': demand_cv,
                'min_order_qty': min_order,
                'lead_time': lead_time,
                'safety_days': safety_day,
                'required_safety_days': required_safety_stock / daily_demand if daily_demand > 0 else 0
            }
            
            if family not in required_budgets:
                required_budgets[family] = []
            required_budgets[family].append(inventory_value[-1])
        
        # Aggregate by family
        for family in families:
            family_skus_list = family_skus.get(family, [])
            
            aggregated_inv = []
            aggregated_value = []
            for i in range(len(future_months_sorted) + 1):
                total_inv = sum(
                    sku_projections[sku]['inventory'][i] 
                    for sku in family_skus_list 
                    if sku in sku_projections
                )
                total_value = sum(
                    sku_projections[sku]['inventory_value'][i] 
                    for sku in family_skus_list 
                    if sku in sku_projections
                )
                aggregated_inv.append(total_inv)
                aggregated_value.append(total_value)
            
            family_projections[family] = {
                'inventory': aggregated_inv,
                'inventory_value': aggregated_value,
                'skus': family_skus_list,
                'required_budget': max(required_budgets.get(family, [0]))
            }
        
        return {
            'sku_projections': sku_projections,
            'family_projections': family_projections,
            'required_budgets': required_budgets,
            'future_months': future_months_sorted,
            'type': 'optimized'
        }
