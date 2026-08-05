#!/usr/bin/env python3
"""
Data Generator for Inventory Optimization Application
Creates realistic sample data for 100 SKUs
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np


class SampleDataGenerator:
    def __init__(self):
        self.families = ['Beverages', 'Snacks', 'Dairy', 'Frozen', 'Household', 'Personal_Care']
        self.abc_classes = ['A', 'B', 'C']
        self.num_skus = 100
    
    def generate(self):
        """Generate complete sample data"""
        np.random.seed(42)
        
        # Generate SKUs
        skus = [f"SKU_{i:03d}" for i in range(1, self.num_skus + 1)]
        
        # Assign families
        family_assignments = []
        for i, sku in enumerate(skus):
            family_idx = i % len(self.families)
            family_assignments.append(self.families[family_idx])
        
        # Assign ABC classes (A: 20%, B: 30%, C: 50%)
        abc_assignments = []
        for i in range(self.num_skus):
            rand = np.random.random()
            if rand < 0.2:
                abc_assignments.append('A')
            elif rand < 0.5:
                abc_assignments.append('B')
            else:
                abc_assignments.append('C')
        
        # Generate prices
        prices = []
        for abc in abc_assignments:
            if abc == 'A':
                prices.append(round(np.random.uniform(5, 20), 2))
            elif abc == 'B':
                prices.append(round(np.random.uniform(2, 10), 2))
            else:
                prices.append(round(np.random.uniform(0.5, 5), 2))
        
        # Generate production lead times
        lead_times = []
        for abc in abc_assignments:
            if abc == 'A':
                lead_times.append(np.random.randint(10, 30))
            elif abc == 'B':
                lead_times.append(np.random.randint(15, 45))
            else:
                lead_times.append(np.random.randint(20, 60))
        
        # Generate safety days
        safety_days = []
        for abc in abc_assignments:
            if abc == 'A':
                safety_days.append(np.random.randint(10, 20))
            elif abc == 'B':
                safety_days.append(np.random.randint(15, 25))
            else:
                safety_days.append(np.random.randint(20, 30))
        
        # Generate minimum order quantities
        min_order_qty = []
        for abc in abc_assignments:
            if abc == 'A':
                min_order_qty.append(np.random.randint(500, 2000))
            elif abc == 'B':
                min_order_qty.append(np.random.randint(200, 1000))
            else:
                min_order_qty.append(np.random.randint(50, 500))
        
        # SKU Master Data
        sku_master = pd.DataFrame({
            'SKU': skus,
            'ABC_Classification': abc_assignments,
            'Production_Leadtime_Days': lead_times,
            'Safety_Days_of_Supply': safety_days,
            'Min_Order_Qty': min_order_qty,
            'Price_EUR': prices
        })
        
        # Inventory History (past 12 months + current)
        # Use proper month naming: M-12, M-11, ..., M-01, Current
        past_months = [f'M-{i:02d}' for i in range(12, 0, -1)]
        all_historical_months = past_months + ['Current']
        
        inventory_data = []
        for sku in skus:
            base_inv = np.random.randint(100, 1000)
            trend = np.random.choice([-10, -5, 0, 5, 10])
            seasonality = np.random.choice([0, 50, 100, -50, -100])
            
            for i, month in enumerate(all_historical_months):
                inv = base_inv + trend * i
                if i % 6 < 3:  # First half of year
                    inv += seasonality
                else:
                    inv -= seasonality
                
                inv = max(0, int(inv + np.random.normal(0, 50)))
                
                inventory_data.append({
                    'SKU': sku,
                    'Month': month,
                    'Inventory': inv
                })
        
        inventory_history = pd.DataFrame(inventory_data)
        
        # Demand Plan (next 12 months) - Use M_01, M_02, ..., M_12
        future_months = [f'M_{i:02d}' for i in range(1, 13)]
        demand_data = []
        
        for sku in skus:
            abc = sku_master[sku_master['SKU'] == sku]['ABC_Classification'].iloc[0]
            if abc == 'A':
                base_demand = np.random.randint(500, 2000)
            elif abc == 'B':
                base_demand = np.random.randint(200, 1000)
            else:
                base_demand = np.random.randint(50, 500)
            
            for i, month in enumerate(future_months):
                demand = base_demand + np.random.randint(-100, 100)
                if i % 6 < 3:
                    demand = int(demand * 1.1)
                else:
                    demand = int(demand * 0.9)
                demand = max(1, demand)
                
                demand_data.append({
                    'SKU': sku,
                    'Month': month,
                    'Demand': demand
                })
        
        demand_plan = pd.DataFrame(demand_data)
        
        # Forecast Accuracy (past 12 months)
        accuracy_data = []
        for sku in skus:
            abc = sku_master[sku_master['SKU'] == sku]['ABC_Classification'].iloc[0]
            if abc == 'A':
                base_accuracy = 0.95
            elif abc == 'B':
                base_accuracy = 0.85
            else:
                base_accuracy = 0.75
            
            for month in past_months:  # Exclude current
                accuracy = round(base_accuracy + np.random.normal(0, 0.05), 3)
                accuracy = max(0.5, min(0.99, accuracy))
                
                accuracy_data.append({
                    'SKU': sku,
                    'Month': month,
                    'Accuracy': accuracy
                })
        
        forecast_accuracy = pd.DataFrame(accuracy_data)
        
        # Product Families
        family_data = []
        for sku in skus:
            family_idx = skus.index(sku) % len(self.families)
            family_data.append({
                'SKU': sku,
                'Product_Family': self.families[family_idx]
            })
        
        product_families = pd.DataFrame(family_data)
        
        # Budget Data (monthly budget per family)
        budget_data = []
        for family in self.families:
            for month in future_months:
                family_size = len([s for s in family_assignments if s == family])
                budget = 1000000 * (family_size / self.num_skus) * np.random.uniform(0.8, 1.2)
                budget_data.append({
                    'Product_Family': family,
                    'Month': month,
                    'Budget_EUR': round(budget, 2)
                })
        
        budget = pd.DataFrame(budget_data)
        
        return {
            'SKU_Master': sku_master,
            'Inventory_History': inventory_history,
            'Demand_Plan': demand_plan,
            'Forecast_Accuracy': forecast_accuracy,
            'Product_Families': product_families,
            'Budget': budget
        }
