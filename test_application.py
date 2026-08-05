#!/usr/bin/env python3
"""
Test script for Inventory Optimizer Application
Runs all core functionality without GUI
"""

import sys
import os
import json
import pandas as pd

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from inventory_optimizer.data_generator import SampleDataGenerator
from inventory_optimizer.calculator import InventoryCalculator


def test_data_generation():
    """Test sample data generation"""
    print("Testing data generation...")
    gen = SampleDataGenerator()
    data = gen.generate()
    
    # Verify all required sheets exist
    required_sheets = ['SKU_Master', 'Inventory_History', 'Demand_Plan', 
                     'Forecast_Accuracy', 'Product_Families', 'Budget']
    
    for sheet in required_sheets:
        assert sheet in data, f"Missing sheet: {sheet}"
    
    # Verify SKU count
    assert len(data['SKU_Master']) == 100, "Expected 100 SKUs"
    
    # Verify families
    families = data['Product_Families']['Product_Family'].unique()
    assert len(families) == 6, f"Expected 6 families, got {len(families)}"
    
    print("✅ Data generation test PASSED")
    return data


def test_data_processing(data):
    """Test data processing"""
    print("Testing data processing...")
    
    # Process data like the app would
    sku_master = data['SKU_Master']
    product_families = data['Product_Families']
    budget_data = data['Budget']
    
    # Merge data
    merged_data = pd.merge(sku_master, product_families, on='SKU', how='left')
    
    # Add inventory history
    inventory_history = data['Inventory_History']
    inventory_pivot = inventory_history.pivot(index='SKU', columns='Month', values='Inventory').add_prefix('Inv_')
    merged_data = pd.merge(merged_data, inventory_pivot, on='SKU', how='left')
    
    # Add current inventory
    current_inv = inventory_history[inventory_history['Month'] == 'Current']
    if not current_inv.empty:
        current_inv = current_inv[['SKU', 'Inventory']].rename(columns={'Inventory': 'Current_Inventory'})
        merged_data = pd.merge(merged_data, current_inv, on='SKU', how='left')
    
    # Add demand plan
    demand_plan = data['Demand_Plan']
    demand_pivot = demand_plan.pivot(index='SKU', columns='Month', values='Demand').add_prefix('Demand_')
    merged_data = pd.merge(merged_data, demand_pivot, on='SKU', how='left')
    
    # Add forecast accuracy
    forecast_accuracy = data['Forecast_Accuracy']
    forecast_pivot = forecast_accuracy.pivot(index='SKU', columns='Month', values='Accuracy').add_prefix('FA_')
    merged_data = pd.merge(merged_data, forecast_pivot, on='SKU', how='left')
    
    # Process budget data
    budget_pivot = budget_data.pivot(index='Product_Family', columns='Month', values='Budget_EUR').add_prefix('Budget_')
    
    # Get families
    families = merged_data['Product_Family'].unique()
    family_skus = {}
    for family in families:
        family_skus[family] = merged_data[merged_data['Product_Family'] == family]['SKU'].tolist()
    
    assert len(families) == 6, f"Expected 6 families, got {len(families)}"
    assert len(merged_data) == 100, f"Expected 100 SKUs, got {len(merged_data)}"
    
    print("✅ Data processing test PASSED")
    return merged_data, budget_pivot, families, family_skus


def test_scenario_calculations(merged_data, budget_pivot, families, family_skus):
    """Test all scenario calculations"""
    print("Testing scenario calculations...")
    
    # Create settings
    settings = {
        'default_service_levels': {'A': 0.99, 'B': 0.95, 'C': 0.90},
        'safety_days_range': {'min': 5, 'max': 60},
        'max_iterations': 100,
        'review_period_days': 7
    }
    
    # Create calculator
    calc = InventoryCalculator(settings)
    
    # Test As-Is scenario
    print("  Testing As-Is scenario...")
    as_is = calc.calculate_as_is_scenario(merged_data, budget_pivot, families, family_skus)
    assert 'sku_projections' in as_is, "Missing sku_projections in As-Is"
    assert 'family_projections' in as_is, "Missing family_projections in As-Is"
    assert 'alerts' in as_is, "Missing alerts in As-Is"
    assert 'budget_deviations' in as_is, "Missing budget_deviations in As-Is"
    assert 'service_level_hints' in as_is, "Missing service_level_hints in As-Is"
    assert len(as_is['sku_projections']) == 100, f"Expected 100 SKU projections, got {len(as_is['sku_projections'])}"
    assert len(as_is['family_projections']) == 6, f"Expected 6 family projections, got {len(as_is['family_projections'])}"
    # Sanity-check the methodology-based fields on a sample SKU
    sample_sku = next(iter(as_is['sku_projections'].values()))
    assert sample_sku['safety_stock'] >= 0, "Safety stock should be non-negative"
    assert 0 <= sample_sku['expected_service_level'] <= 1, "Expected service level should be a probability"
    assert sample_sku['reorder_point'] >= sample_sku['safety_stock'], "Reorder point should be >= safety stock"
    assert sample_sku['xyz'] in ('X', 'Y', 'Z'), "XYZ classification should be X, Y, or Z"
    assert sample_sku['demand_cv'] >= 0, "Demand coefficient of variation should be non-negative"
    print("    ✅ As-Is scenario PASSED")
    
    # Test Constraint scenario
    print("  Testing Constraint scenario...")
    constraint = calc.calculate_constraint_scenario(merged_data, budget_pivot, families, family_skus, as_is)
    assert 'sku_projections' in constraint, "Missing sku_projections in Constraint"
    assert 'family_projections' in constraint, "Missing family_projections in Constraint"
    assert 'optimized_params' in constraint, "Missing optimized_params in Constraint"
    assert len(constraint['sku_projections']) == 100, f"Expected 100 SKU projections, got {len(constraint['sku_projections'])}"
    assert len(constraint['optimized_params']) == 100, f"Expected 100 optimized params, got {len(constraint['optimized_params'])}"
    print("    ✅ Constraint scenario PASSED")
    
    # Test Optimized scenario
    print("  Testing Optimized scenario...")
    optimized = calc.calculate_optimized_scenario(merged_data, families, family_skus)
    assert 'sku_projections' in optimized, "Missing sku_projections in Optimized"
    assert 'family_projections' in optimized, "Missing family_projections in Optimized"
    assert 'required_budgets' in optimized, "Missing required_budgets in Optimized"
    assert len(optimized['sku_projections']) == 100, f"Expected 100 SKU projections, got {len(optimized['sku_projections'])}"
    assert len(optimized['required_budgets']) == 6, f"Expected 6 required budgets, got {len(optimized['required_budgets'])}"
    print("    ✅ Optimized scenario PASSED")
    
    print("✅ All scenario calculations PASSED")
    return as_is, constraint, optimized


def test_all_scenarios(merged_data, budget_pivot, families, family_skus):
    """Test calculate_all_scenarios method"""
    print("Testing all scenarios calculation...")
    
    settings = {
        'default_service_levels': {'A': 0.99, 'B': 0.95, 'C': 0.90},
        'safety_days_range': {'min': 5, 'max': 60},
        'max_iterations': 100,
        'review_period_days': 7
    }
    
    calc = InventoryCalculator(settings)
    scenarios = calc.calculate_all_scenarios(merged_data, budget_pivot, families, family_skus)
    
    assert 'as_is' in scenarios, "Missing as_is scenario"
    assert 'constraint' in scenarios, "Missing constraint scenario"
    assert 'optimized' in scenarios, "Missing optimized scenario"
    
    # Verify each scenario
    for name, scenario in scenarios.items():
        assert 'sku_projections' in scenario, f"Missing sku_projections in {name}"
        assert 'family_projections' in scenario, f"Missing family_projections in {name}"
        assert len(scenario['sku_projections']) == 100, f"Expected 100 SKUs in {name}"
    
    print("✅ All scenarios calculation PASSED")
    return scenarios


def test_settings():
    """Test settings management"""
    print("Testing settings management...")
    
    # Test default settings
    default_settings = {
        'default_service_levels': {'A': 0.99, 'B': 0.95, 'C': 0.90},
        'safety_days_range': {'min': 5, 'max': 60},
        'max_iterations': 1000,
        'review_period_days': 7
    }
    
    # Test saving and loading
    test_file = "test_settings.json"
    try:
        with open(test_file, 'w') as f:
            json.dump(default_settings, f)
        
        with open(test_file, 'r') as f:
            loaded_settings = json.load(f)
        
        assert loaded_settings == default_settings, "Settings not saved/loaded correctly"
        
        # Clean up
        os.remove(test_file)
        
        print("✅ Settings management PASSED")
    except Exception as e:
        print(f"❌ Settings management FAILED: {e}")
        if os.path.exists(test_file):
            os.remove(test_file)
        raise


def main():
    """Run all tests"""
    print("=" * 60)
    print("INVENTORY OPTIMIZER - TEST SUITE")
    print("=" * 60)
    
    try:
        # Test 1: Data Generation
        data = test_data_generation()
        
        # Test 2: Data Processing
        merged_data, budget_pivot, families, family_skus = test_data_processing(data)
        
        # Test 3: Individual Scenario Calculations
        as_is, constraint, optimized = test_scenario_calculations(
            merged_data, budget_pivot, families, family_skus
        )
        
        # Test 4: All Scenarios Together
        scenarios = test_all_scenarios(
            merged_data, budget_pivot, families, family_skus
        )
        
        # Test 5: Settings Management
        test_settings()
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print("✅ All tests PASSED!")
        print(f"\nTested Components:")
        print(f"  - Data Generation: 100 SKUs, 6 families")
        print(f"  - Data Processing: All sheets merged correctly")
        print(f"  - As-Is Scenario: {len(as_is['sku_projections'])} SKUs, {len(as_is['alerts'])} alerts")
        print(f"  - Constraint Scenario: {len(constraint['sku_projections'])} SKUs, {len(constraint['optimized_params'])} params")
        print(f"  - Optimized Scenario: {len(optimized['sku_projections'])} SKUs, {len(optimized['required_budgets'])} budgets")
        print(f"  - Settings Management: Save/load working")
        print(f"\nApplication is ready for use!")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
