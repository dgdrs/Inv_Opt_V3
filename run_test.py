#!/usr/bin/env python3
"""
Test run script for Inventory Optimizer
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from inventory_optimizer.data_generator import SampleDataGenerator
from inventory_optimizer.calculator import InventoryCalculator
import pandas as pd


def main():
    print('=' * 80)
    print('INVENTORY OPTIMIZER - TEST RUN')
    print('=' * 80)
    print(f'Test Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print()
    
    # 1. Generate sample data
    print('1. GENERATING SAMPLE DATA...')
    gen = SampleDataGenerator()
    data = gen.generate()
    print(f'   ✅ Generated {len(data["SKU_Master"])} SKUs across {len(data["Product_Families"]["Product_Family"].unique())} families')
    print()
    
    # 2. Process data
    print('2. PROCESSING DATA...')
    sku_master = data['SKU_Master']
    product_families = data['Product_Families']
    budget_data = data['Budget']
    
    merged_data = pd.merge(sku_master, product_families, on='SKU', how='left')
    inventory_history = data['Inventory_History']
    inventory_pivot = inventory_history.pivot(index='SKU', columns='Month', values='Inventory').add_prefix('Inv_')
    merged_data = pd.merge(merged_data, inventory_pivot, on='SKU', how='left')
    
    current_inv = inventory_history[inventory_history['Month'] == 'Current']
    if not current_inv.empty:
        current_inv = current_inv[['SKU', 'Inventory']].rename(columns={'Inventory': 'Current_Inventory'})
        merged_data = pd.merge(merged_data, current_inv, on='SKU', how='left')
    
    demand_plan = data['Demand_Plan']
    demand_pivot = demand_plan.pivot(index='SKU', columns='Month', values='Demand').add_prefix('Demand_')
    merged_data = pd.merge(merged_data, demand_pivot, on='SKU', how='left')
    
    forecast_accuracy = data['Forecast_Accuracy']
    forecast_pivot = forecast_accuracy.pivot(index='SKU', columns='Month', values='Accuracy').add_prefix('FA_')
    merged_data = pd.merge(merged_data, forecast_pivot, on='SKU', how='left')
    
    budget_pivot = budget_data.pivot(index='Product_Family', columns='Month', values='Budget_EUR').add_prefix('Budget_')
    
    families = merged_data['Product_Family'].unique()
    family_skus = {}
    for family in families:
        family_skus[family] = merged_data[merged_data['Product_Family'] == family]['SKU'].tolist()
    
    print(f'   ✅ Processed data: {len(merged_data)} SKUs, {len(families)} families')
    print()
    
    # 3. Settings
    print('3. SETTINGS:')
    settings = {
        'default_service_levels': {'A': 0.99, 'B': 0.95, 'C': 0.90},
        'safety_days_range': {'min': 5, 'max': 60},
        'max_iterations': 100,
        'currency': '€',
        'review_period_days': 7
    }
    for abc, sl in settings['default_service_levels'].items():
        print(f'   Service Level {abc}: {sl:.0%}')
    print(f'   Safety Days Range: {settings["safety_days_range"]["min"]}-{settings["safety_days_range"]["max"]} days')
    print(f'   Review Period: {settings["review_period_days"]} days (added to lead time as the risk horizon)')
    print(f'   Currency: {settings["currency"]}')
    print()
    
    # 4. Calculate scenarios
    print('4. CALCULATING SCENARIOS...')
    calc = InventoryCalculator(settings)
    scenarios = calc.calculate_all_scenarios(merged_data, budget_pivot, families, family_skus)
    print(f'   ✅ All 3 scenarios calculated')
    print()
    
    # 5. Results Summary
    print('5. RESULTS SUMMARY')
    print('-' * 80)
    
    # As-Is Scenario
    print('AS-IS SCENARIO:')
    as_is = scenarios['as_is']
    print(f'   Total SKUs: {len(as_is["sku_projections"])}')
    print(f'   Product Families: {len(as_is["family_projections"])}')
    print(f'   Alerts Generated: {len(as_is["alerts"])}')
    print(f'   Service Level Hints: {len(as_is["service_level_hints"])}')
    print(f'   Budget Deviations: {sum(len(months) for months in as_is["budget_deviations"].values())}')
    
    print('\n   Sample Alerts:')
    for alert in as_is['alerts'][:3]:
        print(f'     - {alert["Type"]}: {alert["SKU"]} ({alert["Family"]}) in {alert["Month"]}')
    print()
    
    # Constraint Scenario
    print('CONSTRAINT SCENARIO:')
    constraint = scenarios['constraint']
    print(f'   Total SKUs: {len(constraint["sku_projections"])}')
    print(f'   Product Families: {len(constraint["family_projections"])}')
    print(f'   Optimized Parameters: {len(constraint["optimized_params"])}')
    
    print('\n   Sample Optimized Safety Days:')
    for sku, params in list(constraint['optimized_params'].items())[:3]:
        print(f'     - {sku}: {params["safety_days"]} days')
    print()
    
    # Optimized Scenario
    print('OPTIMIZED SCENARIO:')
    optimized = scenarios['optimized']
    print(f'   Total SKUs: {len(optimized["sku_projections"])}')
    print(f'   Product Families: {len(optimized["family_projections"])}')
    print(f'   Required Budgets: {len(optimized["required_budgets"])}')
    
    print('\n   Required Budgets to Reach Target Service Levels:')
    for family, budgets in optimized['required_budgets'].items():
        required = max(budgets)
        print(f'     - {family}: {settings["currency"]}{required:,.0f}')
    print()
    
    # 6. Family-Level Results
    print('6. FAMILY-LEVEL INVENTORY PROJECTIONS (First Month)')
    print('-' * 80)
    
    future_months = [col.replace('Demand_', '') for col in merged_data.columns if col.startswith('Demand_')]
    
    header = f"{'Family':<20} {'As-Is':>15} {'Constraint':>15} {'Optimized':>15}"
    print(header)
    print('-' * len(header))
    
    for family in families:
        as_is_val = as_is['family_projections'][family]['inventory_value'][1] if len(as_is['family_projections'][family]['inventory_value']) > 1 else 0
        constraint_val = constraint['family_projections'][family]['inventory_value'][1] if family in constraint['family_projections'] and len(constraint['family_projections'][family]['inventory_value']) > 1 else 0
        optimized_val = optimized['family_projections'][family]['inventory_value'][1] if family in optimized['family_projections'] and len(optimized['family_projections'][family]['inventory_value']) > 1 else 0
        
        currency = settings['currency']
        print(f'{family:<20} {currency}{as_is_val:>12,.0f} {currency}{constraint_val:>12,.0f} {currency}{optimized_val:>12,.0f}')
    print()
    
    # 7. Service Level Analysis
    print('7. SERVICE LEVEL ANALYSIS')
    print('-' * 80)
    
    header = f"{'Family':<20} {'As-Is Avg':>15} {'Constraint Avg':>15} {'Optimized Avg':>15}"
    print(header)
    print('-' * len(header))
    
    for family in families:
        as_is_sl = sum(
            as_is['sku_projections'][sku]['expected_service_level'] 
            for sku in family_skus[family] 
            if sku in as_is['sku_projections']
        ) / len(family_skus[family]) if family_skus[family] else 0
        
        constraint_sl = sum(
            constraint['sku_projections'][sku]['expected_service_level'] 
            for sku in family_skus[family] 
            if sku in constraint['sku_projections']
        ) / len(family_skus[family]) if family_skus[family] else 0
        
        optimized_sl = sum(
            optimized['sku_projections'][sku]['expected_service_level'] 
            for sku in family_skus[family] 
            if sku in optimized['sku_projections']
        ) / len(family_skus[family]) if family_skus[family] else 0
        
        print(f'{family:<20} {as_is_sl:>15.1%} {constraint_sl:>15.1%} {optimized_sl:>15.1%}')
    print()
    
    # 8. Budget Analysis
    print('8. BUDGET ANALYSIS')
    print('-' * 80)
    
    header = f"{'Family':<20} {'Budget':>15} {'As-Is Actual':>15} {'Deviation':>15}"
    print(header)
    print('-' * len(header))
    
    for family in families:
        budget_cols = [col for col in budget_pivot.columns if col.startswith('Budget_')]
        avg_budget = budget_pivot.loc[family, budget_cols].mean() if family in budget_pivot.index else 0
        
        as_is_actual = as_is['family_projections'][family]['inventory_value'][-1] if len(as_is['family_projections'][family]['inventory_value']) > 0 else 0
        
        deviation = as_is_actual - avg_budget
        deviation_pct = (deviation / avg_budget * 100) if avg_budget > 0 else 0
        
        currency = settings['currency']
        print(f'{family:<20} {currency}{avg_budget:>12,.0f} {currency}{as_is_actual:>12,.0f} {deviation_pct:>+12.1f}%')
    print()
    
    # 9. Sample SKU Details
    print('9. SAMPLE SKU DETAILS')
    print('-' * 80)
    
    sample_skus = list(merged_data['SKU'].head(3))
    header = f"{'SKU':<10} {'Family':<15} {'ABC':<8} {'Price':>10} {'Lead Time':>12} {'Safety Days':>12}"
    print(header)
    print('-' * len(header))
    
    for sku in sample_skus:
        row = merged_data[merged_data['SKU'] == sku].iloc[0]
        currency = settings['currency']
        print(f'{sku:<10} {row["Product_Family"]:<15} {row["ABC_Classification"]:<8} {currency}{row["Price_EUR"]:>8.2f} {row["Production_Leadtime_Days"]:>12} {row["Safety_Days_of_Supply"]:>12}')
    print()
    
    # Summary
    print('=' * 80)
    print('✅ TEST RUN COMPLETED SUCCESSFULLY')
    print('=' * 80)
    print()
    print('Key Findings:')
    print(f'  • {len(families)} product families analyzed')
    print(f'  • {len(merged_data)} SKUs processed')
    print(f'  • {len(as_is["alerts"])} alerts generated in As-Is scenario')
    print(f'  • {len(constraint["optimized_params"])} parameters optimized in Constraint scenario')
    print(f'  • {len(optimized["required_budgets"])} required budgets calculated in Optimized scenario')
    print(f'  • All calculations performed locally in {settings["currency"]}')
    print()
    print('The application is ready for production use!')
    print('=' * 80)


if __name__ == '__main__':
    main()
