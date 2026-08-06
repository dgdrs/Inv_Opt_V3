#!/usr/bin/env python3
"""
Visualizer Module for Inventory Optimization Application
Handles all plotting and visualization
"""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np

try:
    import mplcursors
    HAS_MPLCURSORS = True
except ImportError:
    HAS_MPLCURSORS = False


class ScenarioVisualizer:
    def __init__(self, settings):
        self.settings = settings
        self.currency = settings.get('currency', '€')
    
    def _make_interactive(self, ax):
        """Add two interactivity layers to a chart, degrading gracefully if
        mplcursors isn't installed:
        1. Hover tooltips on line/point series (via mplcursors), showing the
           series name and exact value under the cursor.
        2. Click-a-legend-entry to toggle that series' visibility on/off --
           useful once a chart has many families/SKUs and it gets crowded.
        """
        if HAS_MPLCURSORS:
            line_artists = list(ax.get_lines())
            if line_artists:
                cursor = mplcursors.cursor(line_artists, hover=True)
                
                @cursor.connect("add")
                def _(sel):
                    label = sel.artist.get_label()
                    if label.startswith('_'):
                        label = ''
                    sel.annotation.set_text(f"{label}\n{sel.target[1]:,.0f}" if label else f"{sel.target[1]:,.0f}")
                    sel.annotation.get_bbox_patch().set_alpha(0.9)
        
        legend = ax.get_legend()
        if legend is None:
            return
        
        legend_handles = getattr(legend, 'legend_handles', None) or getattr(legend, 'legendHandles', [])
        legend_labels = [t.get_text() for t in legend.get_texts()]
        
        # Map each legend label to the actual plotted artist(s) sharing that label
        by_label = {}
        for artist in ax.get_lines():
            by_label.setdefault(artist.get_label(), []).append(artist)
        for container in getattr(ax, 'containers', []):
            lbl = container.get_label()
            by_label.setdefault(lbl, []).extend(list(container))
        
        for leg_handle, label in zip(legend_handles, legend_labels):
            targets = by_label.get(label)
            if not targets:
                continue
            leg_handle.set_picker(8)
            leg_handle._toggle_targets = targets
        
        def on_pick(event):
            handle = event.artist
            targets = getattr(handle, '_toggle_targets', None)
            if not targets:
                return
            visible = not targets[0].get_visible()
            for t in targets:
                t.set_visible(visible)
            handle.set_alpha(1.0 if visible else 0.2)
            event.canvas.draw_idle()
        
        ax.figure.canvas.mpl_connect('pick_event', on_pick)
    
    def plot_scenario(self, frame, scenario, future_months, scenario_name):
        """Plot a single scenario with line chart"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        all_months = ['Current'] + future_months
        
        # Create new figure
        fig = plt.Figure(figsize=(10, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        colors = ['blue', 'green', 'red', 'cyan', 'magenta', 'orange', 'purple', 'brown']
        
        for i, (family, proj) in enumerate(scenario['family_projections'].items()):
            color = colors[i % len(colors)]
            ax.plot(all_months, proj['inventory_value'], 
                   marker='o', label=family, color=color, linewidth=2)
        
        ax.set_title(f"{scenario_name} Scenario: Inventory Value by Product Family", 
                     fontsize=14, fontweight='bold')
        ax.set_xlabel("Month", fontsize=12)
        ax.set_ylabel(f"Inventory Value ({self.currency})", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
    
    def plot_stacked_scenario(self, frame, scenario, future_months, scenario_name):
        """Plot a single scenario with stacked line chart"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        all_months = ['Current'] + future_months
        
        # Create new figure
        fig = plt.Figure(figsize=(10, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        colors = ['blue', 'green', 'red', 'cyan', 'magenta', 'orange', 'purple', 'brown']
        
        # Stacked area plot
        bottom = np.zeros(len(all_months))
        
        for i, (family, proj) in enumerate(scenario['family_projections'].items()):
            color = colors[i % len(colors)]
            values = proj['inventory_value']
            ax.fill_between(all_months, bottom, bottom + values, 
                          label=family, color=color, alpha=0.7)
            bottom += values
            
            # Also plot line on top
            ax.plot(all_months, bottom, color=color, linewidth=2)
        
        ax.set_title(f"{scenario_name} Scenario: Stacked Inventory Value by Family", 
                     fontsize=14, fontweight='bold')
        ax.set_xlabel("Month", fontsize=12)
        ax.set_ylabel(f"Inventory Value ({self.currency})", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
    
    def plot_scenarios_comparison(self, frame, scenarios, families, future_months):
        """Plot all scenarios for comparison"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        all_months = ['Current'] + future_months
        
        # Create new figure
        fig = plt.Figure(figsize=(12, 8), dpi=100)
        ax = fig.add_subplot(111)
        
        colors = ['blue', 'green', 'red', 'cyan', 'magenta', 'orange']
        line_styles = ['-', '--', '-.', ':']
        scenario_names = {'as_is': 'As-Is', 'constraint': 'Constraint', 'optimized': 'Optimized'}
        
        for family_idx, family in enumerate(families):
            color = colors[family_idx % len(colors)]
            
            for scenario_idx, (scenario_type, scenario) in enumerate(scenarios.items()):
                if family in scenario['family_projections']:
                    proj = scenario['family_projections'][family]
                    ax.plot(all_months, proj['inventory_value'], 
                           marker='o' if scenario_idx == 0 else 'x',
                           label=f"{family} - {scenario_names[scenario_type]}",
                           color=color, linewidth=2, linestyle=line_styles[scenario_idx])
        
        ax.set_title("All Scenarios: Inventory Value Comparison by Product Family", 
                     fontsize=14, fontweight='bold')
        ax.set_xlabel("Month", fontsize=12)
        ax.set_ylabel(f"Inventory Value ({self.currency})", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
    
    def plot_all_scenarios_stacked(self, frame, scenarios, families, future_months):
        """Plot all scenarios in a single stacked comparison"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        all_months = ['Current'] + future_months
        
        # Create new figure
        fig = plt.Figure(figsize=(12, 8), dpi=100)
        ax = fig.add_subplot(111)
        
        colors = ['blue', 'green', 'red', 'cyan', 'magenta', 'orange']
        scenario_names = {'as_is': 'As-Is', 'constraint': 'Constraint', 'optimized': 'Optimized'}
        
        # Plot each scenario as a separate stacked area
        for scenario_idx, (scenario_type, scenario) in enumerate(scenarios.items()):
            bottom = np.zeros(len(all_months))
            alpha = 0.3 + (scenario_idx * 0.2)  # Different alpha for each scenario
            
            for family_idx, family in enumerate(families):
                if family in scenario['family_projections']:
                    color = colors[family_idx % len(colors)]
                    values = scenario['family_projections'][family]['inventory_value']
                    
                    # For stacked comparison, we want to see the composition
                    # So we'll plot each family's contribution
                    label = f"{family} - {scenario_names[scenario_type]}" if scenario_idx == 0 else None
                    ax.fill_between(all_months, bottom, bottom + values,
                                  color=color, alpha=alpha, label=label)
                    bottom += values
        
        ax.set_title("All Scenarios: Stacked Inventory Value Comparison", 
                     fontsize=14, fontweight='bold')
        ax.set_xlabel("Month", fontsize=12)
        ax.set_ylabel(f"Inventory Value ({self.currency})", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
    
    def plot_service_levels_comparison(self, frame, scenarios, families):
        """Plot service levels comparison"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        # Create new figure
        fig = plt.Figure(figsize=(12, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        scenario_names = ['As-Is', 'Constraint', 'Optimized']
        
        # Collect service levels
        sl_data = {}
        for scenario_type, scenario in scenarios.items():
            sl_data[scenario_type] = {}
            for family in families:
                if family in scenario['family_projections']:
                    avg_sl = 0
                    count = 0
                    for sku, proj in scenario['sku_projections'].items():
                        if proj['family'] == family:
                            avg_sl += proj.get('expected_service_level', 0)
                            count += 1
                    sl_data[scenario_type][family] = avg_sl / count if count > 0 else 0
        
        # Plot
        x = np.arange(len(families))
        width = 0.25
        
        for i, scenario_type in enumerate(['as_is', 'constraint', 'optimized']):
            if scenario_type in sl_data:
                sl_values = [sl_data[scenario_type].get(family, 0) for family in families]
                ax.bar(x + i * width, sl_values, width, label=scenario_names[i])
        
        ax.set_title("Service Levels Comparison by Product Family", fontsize=14, fontweight='bold')
        ax.set_xlabel("Product Family", fontsize=12)
        ax.set_ylabel("Service Level", fontsize=12)
        ax.set_xticks(x + width)
        ax.set_xticklabels(families, rotation=45, ha='right')
        ax.grid(True, alpha=0.3, axis='y')
        ax.legend()
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
    
    def plot_budget_analysis(self, frame, scenarios, families, budget_data, future_months):
        """Plot budget analysis"""
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()
        
        # Create new figure
        fig = plt.Figure(figsize=(12, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        # Collect budget data
        budget_analysis = {}
        for family in families:
            budget_analysis[family] = {
                'Budget': 0,
                'As_Is': 0,
                'Constraint': 0,
                'Optimized': 0
            }
            
            # Get budget (average)
            if family in budget_data.index:
                for month in future_months:
                    budget_col = f'Budget_{month}'
                    if budget_col in budget_data.columns:
                        budget_analysis[family]['Budget'] += budget_data.loc[family, budget_col]
                budget_analysis[family]['Budget'] /= len(future_months)
            
            # Get scenario values
            for scenario_type in ['as_is', 'constraint', 'optimized']:
                if scenario_type in scenarios and family in scenarios[scenario_type]['family_projections']:
                    proj = scenarios[scenario_type]['family_projections'][family]
                    if len(proj['inventory_value']) > 1:
                        budget_analysis[family][scenario_type.capitalize()] = proj['inventory_value'][-1]
            
            # Get optimized required budget
            if 'optimized' in scenarios and family in scenarios['optimized']['family_projections']:
                proj = scenarios['optimized']['family_projections'][family]
                budget_analysis[family]['Optimized'] = proj.get('required_budget', 0)
        
        # Plot
        x = np.arange(len(families))
        width = 0.2
        
        ax.bar(x - width*1.5, [budget_analysis[f]['Budget'] for f in families], width, 
               label='Budget', color='gray', alpha=0.7)
        ax.bar(x - width*0.5, [budget_analysis[f]['As_Is'] for f in families], width, 
               label='As-Is', color='blue', alpha=0.7)
        ax.bar(x + width*0.5, [budget_analysis[f]['Constraint'] for f in families], width, 
               label='Constraint', color='green', alpha=0.7)
        ax.bar(x + width*1.5, [budget_analysis[f]['Optimized'] for f in families], width, 
               label='Optimized', color='red', alpha=0.7)
        
        ax.set_title("Budget Analysis: Required vs Available", fontsize=14, fontweight='bold')
        ax.set_xlabel("Product Family", fontsize=12)
        ax.set_ylabel(f"Inventory Value ({self.currency})", fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(families, rotation=45, ha='right')
        ax.grid(True, alpha=0.3, axis='y')
        ax.legend()
        self._make_interactive(ax)
        fig.tight_layout()
        
        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas

    def plot_budget_vs_scenarios_timeseries(self, frame, scenarios, families, budget_data, future_months):
        """Comparison-tab chart: for EVERY family, plot the editable Budget
        (the % split of the Total Monthly Budget entered on the Budget tab --
        treated as a MAXIMUM) as a dashed cap line, together with the As-Is,
        Constraint and Optimized inventory-value lines, across the full
        Current + 12-month horizon. One subplot per family, so it's a genuine
        all-scenarios-vs-budget comparison (as opposed to plot_budget_analysis
        above, which only compares a single last-month snapshot per family).
        """
        # Clear previous plot
        for widget in frame.winfo_children():
            widget.destroy()

        families = list(families)
        if not families:
            return None

        all_months = ['Current'] + list(future_months)
        n = len(families)
        ncols = 3 if n > 2 else n
        nrows = math.ceil(n / ncols)

        fig = plt.Figure(figsize=(5.3 * ncols, 3.7 * nrows), dpi=100)

        scenario_names = {'as_is': 'As-Is', 'constraint': 'Constraint', 'optimized': 'Optimized'}
        scenario_colors = {'as_is': 'blue', 'constraint': 'green', 'optimized': 'red'}
        scenario_order = ['as_is', 'constraint', 'optimized']

        axes = []
        for idx, family in enumerate(families):
            ax = fig.add_subplot(nrows, ncols, idx + 1)
            axes.append(ax)

            # Budget (maximum) cap line -- future months only, no "Current" budget
            if budget_data is not None and family in budget_data.index:
                budget_values = [
                    budget_data.loc[family, f'Budget_{m}'] if f'Budget_{m}' in budget_data.columns else np.nan
                    for m in future_months
                ]
                ax.plot(list(future_months), budget_values, color='black', linestyle='--',
                        linewidth=2, marker='s', markersize=4, label='Budget (max)')

            for scenario_type in scenario_order:
                scenario = scenarios.get(scenario_type)
                if not scenario:
                    continue
                if family in scenario.get('family_projections', {}):
                    proj = scenario['family_projections'][family]
                    values = proj['inventory_value']
                    ax.plot(all_months[:len(values)], values, marker='o', markersize=3,
                            linewidth=1.6, color=scenario_colors[scenario_type],
                            label=scenario_names[scenario_type])

            ax.set_title(str(family), fontsize=10, fontweight='bold')
            ax.tick_params(axis='x', labelrotation=60, labelsize=7)
            ax.tick_params(axis='y', labelsize=7)
            ax.grid(True, alpha=0.3)
            if idx == 0:
                ax.legend(fontsize=7, loc='upper left')
            self._make_interactive(ax)

        fig.suptitle(f"Budget (Maximum) vs. All Scenarios, by Product Family ({self.currency})",
                     fontsize=13, fontweight='bold')
        fig.tight_layout(rect=[0, 0, 1, 0.96])

        # Create canvas
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        return canvas
    
    def plot_sku_detail(self, frame, sku, sku_result, future_months, existing_canvas=None):
        """Interactive rolling-inventory chart for a single SKU, used by the
        SKU Inspector tab. Shows the projected inventory line, the safety
        stock threshold, and markers for months where a replenishment order
        was placed -- with hover tooltips and click-legend-to-toggle like the
        other charts (see _make_interactive)."""
        if existing_canvas is not None:
            existing_canvas.get_tk_widget().destroy()
        
        fig = plt.Figure(figsize=(7, 4.6), dpi=100)
        ax = fig.add_subplot(111)
        
        all_months = ['Current'] + list(future_months)
        inventory = sku_result.get('inventory', [])
        safety_stock = sku_result.get('safety_stock', 0)
        reorder_point = sku_result.get('reorder_point', 0)
        
        ax.plot(all_months[:len(inventory)], inventory, marker='o', color='#2b6cb0',
                linewidth=2, label='Projected Inventory')
        ax.axhline(y=safety_stock, color='orange', linestyle='--',
                   label=f'Safety Stock ({safety_stock:,.0f})')
        ax.axhline(y=reorder_point, color='#8e44ad', linestyle=':',
                   label=f'Reorder Point ({reorder_point:,.0f})')
        
        order_months = {o['Month'] for o in sku_result.get('supply_orders', [])}
        order_x, order_y = [], []
        for i, month in enumerate(future_months):
            if month in order_months and (i + 1) < len(inventory):
                order_x.append(month)
                order_y.append(inventory[i + 1])
        if order_x:
            ax.scatter(order_x, order_y, color='green', marker='^', s=110, zorder=5, label='Order placed')
        
        ax.set_title(f"{sku} - Rolling Inventory Projection", fontsize=12, fontweight='bold')
        ax.set_xlabel("Month", fontsize=10)
        ax.set_ylabel("Units", fontsize=10)
        ax.tick_params(axis='x', labelrotation=45)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=8)
        self._make_interactive(ax)
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        return canvas
