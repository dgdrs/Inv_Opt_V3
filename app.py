#!/usr/bin/env python3
"""
Main Application for Inventory Optimization
"""

import os
import json
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np

try:
    from .data_generator import SampleDataGenerator
    from .calculator import InventoryCalculator
    from .visualizer import ScenarioVisualizer
except ImportError:
    # Fallback for direct execution
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from data_generator import SampleDataGenerator
    from calculator import InventoryCalculator
    from visualizer import ScenarioVisualizer


BUDGET_MONTHS = [f"M_{i:02d}" for i in range(1, 13)]


class InventoryOptimizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Inventory Optimizer - Consumer Goods Supply Chain")
        self.root.geometry("1600x1200")
        
        # Initialize components
        self.settings = self.load_settings()
        self.data_generator = SampleDataGenerator()
        self.calculator = InventoryCalculator(self.settings)
        self.visualizer = ScenarioVisualizer(self.settings)

        # Budget settings: Total Monthly Budget (€) + % split per Product
        # Family, editable/savable via the "Budget" tab (budget_settings.json).
        # This is the single source of truth for self.budget_data below, which
        # every scenario treats as a MAXIMUM: As-Is reports deviations against
        # it, and the Constraint scenario optimizes safety days to stay
        # within it. Populated for real once data is loaded (see process_data
        # / _sync_budget_tab_with_families).
        self.budget_settings = self.load_budget_settings()
        
        # Data storage
        self.input_file = None
        self.data = {}
        self.processed_data = None
        self.budget_data = None
        self.scenarios = {}
        self.families = []
        self.family_skus = {}
        self.all_skus = []
        
        # Background-calculation state
        self._progress_queue = queue.Queue()
        self._calc_running = False
        
        # SKU Inspector state
        self.inspector_sku_var = tk.StringVar()
        self.inspector_fields = {}
        self.inspector_computed_vars = {}
        self.inspector_canvas = None

        # Budget tab state
        self.budget_month_vars = {}
        self.budget_family_split_vars = {}
        self.budget_split_sum_var = None
        self.budget_split_sum_label = None
        self.budget_split_inner = None
        self.budget_preview_tree = None
        
        # Create GUI
        self.create_widgets()
        
        # Load sample data on startup
        self.load_sample_data()
    
    def load_settings(self):
        """Load settings from JSON file"""
        settings_file = "inventory_settings.json"
        default_settings = {
            "default_service_levels": {
                "A": 0.99,
                "B": 0.95,
                "C": 0.90
            },
            "safety_days_range": {
                "min": 5,
                "max": 60
            },
            "optimization_tolerance": 0.01,
            "max_iterations": 1000,
            "currency": "€",
            "projection_months": 12,
            "historical_months": 12,
            "review_period_days": 7,
            "xyz_thresholds": {
                "x_max": 0.5,
                "y_max": 1.0
            },
            "xyz_safety_multiplier": {
                "X": 1.0,
                "Y": 1.15,
                "Z": 1.3
            }
        }
        
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Backfill any new keys that weren't present in an older settings file
                    for key, value in default_settings.items():
                        loaded.setdefault(key, value)
                    return loaded
        except Exception as e:
            print(f"Error loading settings: {e}")
        
        return default_settings
    
    def save_settings(self):
        """Save settings to JSON file"""
        settings_file = "inventory_settings.json"
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Success", "Settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    # ------------------------------------------------------------------
    # Budget settings persistence (Total Monthly Budget + Family % split)
    # ------------------------------------------------------------------

    def load_budget_settings(self):
        """Load previously saved Budget-tab settings (Total Monthly Budget +
        Family % split) from budget_settings.json, if it exists. Returns None
        if there's nothing saved yet -- callers then fall back to deriving
        defaults from whatever data file gets loaded."""
        budget_file = "budget_settings.json"
        try:
            if os.path.exists(budget_file):
                with open(budget_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading budget settings: {e}")
        return None

    def save_budget_settings(self):
        """Persist the current Total Monthly Budget + Family % split to
        budget_settings.json so it survives an app restart or a fresh data
        load."""
        budget_file = "budget_settings.json"
        try:
            with open(budget_file, 'w', encoding='utf-8') as f:
                json.dump(self.budget_settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save budget settings: {e}")
    
    def create_widgets(self):
        """Create all GUI elements"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=5)
        ttk.Label(header_frame, text="Inventory Optimization for Consumer Goods", 
                 font=('Helvetica', 16, 'bold')).pack(side=tk.LEFT)
        ttk.Label(header_frame, text=f"Currency: {self.settings['currency']}", 
                 font=('Helvetica', 12)).pack(side=tk.RIGHT)
        
        # Input frame
        input_frame = ttk.LabelFrame(main_frame, text="Input Data", padding="10")
        input_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(input_frame, text="Excel File:").grid(row=0, column=0, sticky=tk.W)
        self.file_path_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.file_path_var, width=60).grid(row=0, column=1, padx=5)
        self.browse_button = ttk.Button(input_frame, text="Browse", command=self.load_file)
        self.browse_button.grid(row=0, column=2)
        self.sample_button = ttk.Button(input_frame, text="Load Sample Data", command=self.load_sample_data)
        self.sample_button.grid(row=0, column=3, padx=5)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="10")
        settings_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(settings_frame, text="Service Level A:").grid(row=0, column=0, sticky=tk.W)
        self.sl_a_var = tk.DoubleVar(value=self.settings['default_service_levels']['A'])
        ttk.Entry(settings_frame, textvariable=self.sl_a_var, width=10).grid(row=0, column=1, sticky=tk.W)
        
        ttk.Label(settings_frame, text="Service Level B:").grid(row=0, column=2, sticky=tk.W)
        self.sl_b_var = tk.DoubleVar(value=self.settings['default_service_levels']['B'])
        ttk.Entry(settings_frame, textvariable=self.sl_b_var, width=10).grid(row=0, column=3, sticky=tk.W)
        
        ttk.Label(settings_frame, text="Service Level C:").grid(row=0, column=4, sticky=tk.W)
        self.sl_c_var = tk.DoubleVar(value=self.settings['default_service_levels']['C'])
        ttk.Entry(settings_frame, textvariable=self.sl_c_var, width=10).grid(row=0, column=5, sticky=tk.W)
        
        ttk.Label(settings_frame, text="Review Period (days):").grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        self.review_period_var = tk.IntVar(value=self.settings.get('review_period_days', 7))
        ttk.Entry(settings_frame, textvariable=self.review_period_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
        ttk.Label(
            settings_frame,
            text="(time between replenishment decisions, default 1 week - added to lead time as the safety-stock risk horizon)"
        ).grid(row=1, column=2, columnspan=4, sticky=tk.W, pady=(5, 0))
        
        ttk.Button(settings_frame, text="Save Settings", command=self.save_current_settings).grid(row=2, column=0, columnspan=6, pady=5)
        
        # Calculate button
        calc_frame = ttk.Frame(main_frame)
        calc_frame.pack(fill=tk.X, pady=5)
        self.calc_button = ttk.Button(calc_frame, text="Calculate All Scenarios", command=self.calculate_all_scenarios,
                                       style="Accent.TButton")
        self.calc_button.pack(side=tk.LEFT, padx=5)
        self.recalc_button = ttk.Button(calc_frame, text="Recalculate", command=self.recalculate,
                                         style="Accent.TButton")
        self.recalc_button.pack(side=tk.LEFT, padx=5)
        self.export_button = ttk.Button(calc_frame, text="Export Results", command=self.export_results)
        self.export_button.pack(side=tk.LEFT, padx=5)
        
        # Progress bar (determinate -- driven by the calculator's progress_callback)
        self.progress_bar = ttk.Progressbar(calc_frame, orient=tk.HORIZONTAL, length=300, mode='determinate', maximum=100)
        self.progress_bar.pack(side=tk.LEFT, padx=15)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN).pack(fill=tk.X, pady=5)
        
        # Notebook for scenarios
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Tabs
        self.tab_budget = ttk.Frame(self.notebook)
        self.tab_as_is = ttk.Frame(self.notebook)
        self.tab_constraint = ttk.Frame(self.notebook)
        self.tab_optimized = ttk.Frame(self.notebook)
        self.tab_comparison = ttk.Frame(self.notebook)
        self.tab_inspector = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_budget, text="Budget")
        self.notebook.add(self.tab_as_is, text="As-Is Scenario")
        self.notebook.add(self.tab_constraint, text="Constraint Scenario")
        self.notebook.add(self.tab_optimized, text="Optimized Scenario")
        self.notebook.add(self.tab_comparison, text="Comparison")
        self.notebook.add(self.tab_inspector, text="SKU Inspector")
        
        # Setup tabs
        self.setup_budget_tab()
        self.setup_as_is_tab()
        self.setup_constraint_tab()
        self.setup_optimized_tab()
        self.setup_comparison_tab()
        self.setup_sku_inspector_tab()
        
        # Configure styles
        self.configure_styles()
    
    def configure_styles(self):
        """Configure GUI styles"""
        style = ttk.Style()
        style.configure("Accent.TButton", foreground="white", background="#4a7abc", 
                       font=('Helvetica', 10, 'bold'))
        style.map("Accent.TButton", background=[("active", "#3a5a8f")])
    
    def save_current_settings(self):
        """Save current GUI settings"""
        self.settings['default_service_levels']['A'] = self.sl_a_var.get()
        self.settings['default_service_levels']['B'] = self.sl_b_var.get()
        self.settings['default_service_levels']['C'] = self.sl_c_var.get()
        self.settings['review_period_days'] = self.review_period_var.get()
        self.save_settings()
        
        # Update calculator with new settings
        self.calculator = InventoryCalculator(self.settings)

    # ------------------------------------------------------------------
    # Budget tab: Total Monthly Budget (€) + % split per Product Family
    # ------------------------------------------------------------------

    def setup_budget_tab(self):
        """Budget tab: edit the Total Monthly Budget and how it's split (%)
        across Product Families. This is the single source of truth for
        self.budget_data, which every scenario treats as a MAXIMUM -- the
        As-Is scenario reports deviations against it, and the Constraint
        scenario optimizes safety days to stay within it. Family rows are
        (re)built once data is loaded (see _sync_budget_tab_with_families),
        since the family list isn't known yet at widget-creation time."""
        container = ttk.Frame(self.tab_budget, padding="10")
        container.pack(fill=tk.BOTH, expand=True)

        intro = ttk.Label(
            container,
            text=("Set the Total Monthly Budget and how it is split (%) across Product Families. "
                  "This budget is treated as a MAXIMUM: the As-Is scenario reports deviations against "
                  "it, and the Constraint scenario optimizes safety days to stay within it. "
                  "Click 'Apply & Save Budget' to persist your changes, then the main 'Recalculate' "
                  "button to flow them into all three scenarios."),
            wraplength=1400, justify=tk.LEFT
        )
        intro.pack(fill=tk.X, pady=(0, 10))

        body = ttk.Frame(container)
        body.pack(fill=tk.BOTH, expand=True)

        # --- Total monthly budget (editable) ---
        total_frame = ttk.LabelFrame(body, text="Total Monthly Budget (€)", padding="10")
        total_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        for r, month in enumerate(BUDGET_MONTHS):
            ttk.Label(total_frame, text=month + ":").grid(row=r, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value="0")
            ttk.Entry(total_frame, textvariable=var, width=14).grid(row=r, column=1, sticky=tk.W, pady=2, padx=5)
            self.budget_month_vars[month] = var

        # --- Family % split (editable) ---
        split_frame = ttk.LabelFrame(body, text="Family Split (%)", padding="10")
        split_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        self.budget_split_inner = ttk.Frame(split_frame)
        self.budget_split_inner.pack(fill=tk.BOTH, expand=True)

        self.budget_split_sum_var = tk.StringVar(value="Sum: -")
        self.budget_split_sum_label = ttk.Label(split_frame, textvariable=self.budget_split_sum_var,
                                                 font=('Helvetica', 9, 'italic'))
        self.budget_split_sum_label.pack(pady=(8, 0), anchor=tk.W)

        btn_frame = ttk.Frame(split_frame)
        btn_frame.pack(pady=(12, 0), anchor=tk.W)
        ttk.Button(btn_frame, text="Apply & Save Budget", command=self.apply_budget_settings,
                   style="Accent.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="Reset from Data", command=self.reset_budget_from_data).pack(side=tk.LEFT, padx=3)

        # --- Resulting per-family/month budget (read-only preview) ---
        preview_frame = ttk.LabelFrame(body, text="Resulting Budget per Family / Month (preview)", padding="10")
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ["Family"] + BUDGET_MONTHS
        tree_container = ttk.Frame(preview_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        self.budget_preview_tree = ttk.Treeview(tree_container, columns=columns, show='headings', height=10)
        for col in columns:
            self.budget_preview_tree.heading(col, text=col)
            width = 120 if col == "Family" else 78
            anchor = tk.W if col == "Family" else tk.E
            self.budget_preview_tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.budget_preview_tree.yview)
        hsb = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.budget_preview_tree.xview)
        self.budget_preview_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.budget_preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        hsb.pack(fill=tk.X)

    def _update_budget_split_sum(self):
        """Live-updates the 'Sum: X%' readout next to the Family Split
        fields, and colors it green/red depending on how close it is to the
        required 100%."""
        total = 0.0
        for var in self.budget_family_split_vars.values():
            try:
                total += float(var.get())
            except ValueError:
                pass
        if self.budget_split_sum_var is not None:
            self.budget_split_sum_var.set(f"Sum: {total:.1f}%  (target 100%)")
        if self.budget_split_sum_label is not None:
            color = "#1a7f37" if abs(total - 100) < 0.5 else "#b3261e"
            self.budget_split_sum_label.configure(foreground=color)

    def _derive_budget_defaults_from_raw(self, budget_df):
        """Build a monthly_total_eur / family_split_pct dict from a raw
        (un-pivoted) Budget dataframe (columns: Product_Family, Month,
        Budget_EUR) -- i.e. whatever came in on the loaded Excel file's own
        Budget tab. Used to seed sensible defaults the first time, or when
        'Reset from Data' is clicked. Falls back to an equal split across the
        currently loaded families if no budget data is available."""
        monthly_total = {m: 0.0 for m in BUDGET_MONTHS}
        family_split = {}

        if budget_df is not None and not budget_df.empty and 'Budget_EUR' in budget_df.columns:
            totals_by_month = budget_df.groupby('Month')['Budget_EUR'].sum()
            for m in BUDGET_MONTHS:
                monthly_total[m] = float(totals_by_month.get(m, 0.0))

            grand_total = float(budget_df['Budget_EUR'].sum())
            by_family = budget_df.groupby('Product_Family')['Budget_EUR'].sum()
            for family in self.families:
                family = str(family)
                if grand_total > 0:
                    family_split[family] = float(by_family.get(family, 0.0)) / grand_total * 100.0
                else:
                    family_split[family] = 100.0 / max(len(self.families), 1)
        else:
            equal_share = 100.0 / max(len(self.families), 1)
            for family in self.families:
                family_split[str(family)] = equal_share

        # Normalize splits to sum exactly 100 (guards against float drift /
        # families with zero historical budget)
        total_pct = sum(family_split.values())
        if total_pct > 0:
            family_split = {k: v * 100.0 / total_pct for k, v in family_split.items()}

        return {'monthly_total_eur': monthly_total, 'family_split_pct': family_split}

    def _recompute_budget_data_from_settings(self):
        """Recompute self.budget_data (the pivoted Family x Budget_M_xx
        DataFrame every scenario reads) from self.budget_settings' Total
        Monthly Budget + Family % split."""
        rows = []
        for family in self.families:
            family = str(family)
            split = self.budget_settings['family_split_pct'].get(family, 0.0)
            for m in BUDGET_MONTHS:
                total = self.budget_settings['monthly_total_eur'].get(m, 0.0)
                rows.append({'Product_Family': family, 'Month': m, 'Budget_EUR': total * split / 100.0})

        if not rows:
            return
        budget_long = pd.DataFrame(rows)
        self.budget_data = budget_long.pivot(
            index='Product_Family', columns='Month', values='Budget_EUR'
        ).add_prefix('Budget_')

    def _sync_budget_tab_with_families(self):
        """(Re)build the Family Split (%) rows to match the currently loaded
        families, and populate the Budget tab either from a previously saved
        budget_settings.json (if its family set still matches) or -- the
        first time, or after loading a file with a different family set --
        from the loaded data's own Budget tab as sensible defaults. Always
        ends by recomputing self.budget_data so scenarios immediately use
        whatever is showing on the Budget tab."""
        if not hasattr(self, 'budget_month_vars') or not self.budget_month_vars:
            return

        settings_families = set(self.budget_settings['family_split_pct'].keys()) if self.budget_settings else set()
        current_families = set(str(f) for f in self.families)

        if self.budget_settings is None or settings_families != current_families:
            self.budget_settings = self._derive_budget_defaults_from_raw(self.data.get('Budget'))

        # Populate Total Monthly Budget fields
        for month in BUDGET_MONTHS:
            val = self.budget_settings['monthly_total_eur'].get(month, 0.0)
            self.budget_month_vars[month].set(f"{val:.2f}")

        # Rebuild Family Split rows
        for widget in self.budget_split_inner.winfo_children():
            widget.destroy()
        self.budget_family_split_vars = {}
        for r, family in enumerate(self.families):
            family = str(family)
            ttk.Label(self.budget_split_inner, text=family + ":").grid(row=r, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=f"{self.budget_settings['family_split_pct'].get(family, 0.0):.1f}")
            entry = ttk.Entry(self.budget_split_inner, textvariable=var, width=10)
            entry.grid(row=r, column=1, sticky=tk.W, pady=2, padx=5)
            entry.bind('<KeyRelease>', lambda e: self._update_budget_split_sum())
            self.budget_family_split_vars[family] = var

        self._update_budget_split_sum()
        self._recompute_budget_data_from_settings()
        self.refresh_budget_preview()

    def refresh_budget_preview(self):
        """Refresh the read-only 'Resulting Budget per Family / Month'
        preview table from self.budget_data."""
        if self.budget_preview_tree is None:
            return
        for item in self.budget_preview_tree.get_children():
            self.budget_preview_tree.delete(item)
        if self.budget_data is None:
            return
        for family in self.families:
            family = str(family)
            if family not in self.budget_data.index:
                continue
            values = []
            for m in BUDGET_MONTHS:
                col = f'Budget_{m}'
                values.append(f"{self.budget_data.loc[family, col]:,.0f}" if col in self.budget_data.columns else "-")
            self.budget_preview_tree.insert('', tk.END, values=[family] + values)

    def apply_budget_settings(self):
        """Validate and persist the edited Total Monthly Budget + Family
        Split fields, recompute self.budget_data (the MAXIMUM every scenario
        reads), and save to budget_settings.json so it survives a restart /
        a fresh data load."""
        try:
            monthly_total = {m: float(self.budget_month_vars[m].get()) for m in BUDGET_MONTHS}
            if any(v < 0 for v in monthly_total.values()):
                raise ValueError("values must be zero or positive")
        except ValueError as e:
            messagebox.showerror("Invalid input", f"Please check the Total Monthly Budget values: {e}")
            return

        try:
            family_split = {f: float(v.get()) for f, v in self.budget_family_split_vars.items()}
            if any(v < 0 for v in family_split.values()):
                raise ValueError("values must be zero or positive")
        except ValueError as e:
            messagebox.showerror("Invalid input", f"Please check the Family Split values: {e}")
            return

        total_pct = sum(family_split.values())
        if abs(total_pct - 100.0) > 0.5:
            proceed = messagebox.askyesno(
                "Splits don't sum to 100%",
                f"Family split percentages sum to {total_pct:.1f}%, not 100%.\n\n"
                f"Auto-normalize proportionally to 100% and continue?"
            )
            if not proceed:
                return
            if total_pct > 0:
                family_split = {f: v * 100.0 / total_pct for f, v in family_split.items()}
            else:
                equal = 100.0 / max(len(family_split), 1)
                family_split = {f: equal for f in family_split}

        self.budget_settings = {'monthly_total_eur': monthly_total, 'family_split_pct': family_split}
        self.save_budget_settings()
        self._recompute_budget_data_from_settings()
        self.refresh_budget_preview()

        # Reflect (possibly normalized) split values back into the entry fields
        for f, var in self.budget_family_split_vars.items():
            var.set(f"{family_split.get(f, 0):.1f}")
        self._update_budget_split_sum()

        self.status_var.set(
            "Budget applied and saved to budget_settings.json. Click 'Recalculate' to flow it into all scenarios."
        )
        messagebox.showinfo(
            "Budget saved",
            "Budget saved. Click the main 'Recalculate' button to re-run all scenarios against the new budget."
        )

    def reset_budget_from_data(self):
        """Discard any saved budget_settings.json values and recompute the
        Total Monthly Budget / Family Split fields fresh from the currently
        loaded data file's own Budget tab. Not saved until 'Apply & Save
        Budget' is clicked afterwards."""
        if self.processed_data is None:
            return
        self.budget_settings = self._derive_budget_defaults_from_raw(self.data.get('Budget'))
        self._sync_budget_tab_with_families()
        self.status_var.set("Budget fields reset from loaded data (not yet saved -- click 'Apply & Save Budget' to persist).")
    
    def load_file(self):
        """Load Excel file with multiple tabs"""
        file_path = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[("Excel Files", "*.xlsx;*.xls"), ("All Files", "*.*")]
        )
        
        if file_path:
            self.input_file = file_path
            self.file_path_var.set(file_path)
            self.status_var.set(f"Loading: {os.path.basename(file_path)}")
            self.root.update()
            
            try:
                self.load_excel_data(file_path)
                self.status_var.set(f"Loaded: {os.path.basename(file_path)}")
                messagebox.showinfo("Success", "Data loaded successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load data: {str(e)}")
                self.status_var.set("Error loading data")
    
    def load_excel_data(self, file_path):
        """Load data from Excel file with multiple tabs"""
        excel_file = pd.ExcelFile(file_path)
        
        # Load each tab
        self.data = {}
        for sheet_name in excel_file.sheet_names:
            self.data[sheet_name] = pd.read_excel(file_path, sheet_name=sheet_name)
        
        # Validate required data
        required_tabs = [
            'SKU_Master', 'Inventory_History', 'Demand_Plan', 
            'Forecast_Accuracy', 'Product_Families', 'Budget'
        ]
        
        missing_tabs = [tab for tab in required_tabs if tab not in self.data]
        if missing_tabs:
            raise ValueError(f"Missing required tabs: {', '.join(missing_tabs)}")
        
        # Process and merge data
        self.process_data()
    
    def process_data(self):
        """Process and merge data from different tabs"""
        # Merge all data into a single dataframe
        sku_master = self.data['SKU_Master']
        inventory_history = self.data['Inventory_History']
        demand_plan = self.data['Demand_Plan']
        forecast_accuracy = self.data['Forecast_Accuracy']
        product_families = self.data['Product_Families']
        budget_data = self.data['Budget']
        
        # Merge on SKU
        merged_data = sku_master.copy()
        
        # Add inventory history (pivot to get past months)
        inventory_pivot = inventory_history.pivot(
            index='SKU', columns='Month', values='Inventory'
        ).add_prefix('Inv_')
        merged_data = pd.merge(merged_data, inventory_pivot, on='SKU', how='left')
        
        # Add current inventory
        current_inv = inventory_history[inventory_history['Month'] == 'Current']
        if not current_inv.empty:
            current_inv = current_inv[['SKU', 'Inventory']].rename(columns={'Inventory': 'Current_Inventory'})
            merged_data = pd.merge(merged_data, current_inv, on='SKU', how='left')
        
        # Add demand plan
        demand_pivot = demand_plan.pivot(
            index='SKU', columns='Month', values='Demand'
        ).add_prefix('Demand_')
        merged_data = pd.merge(merged_data, demand_pivot, on='SKU', how='left')
        
        # Add forecast accuracy
        forecast_pivot = forecast_accuracy.pivot(
            index='SKU', columns='Month', values='Accuracy'
        ).add_prefix('FA_')
        merged_data = pd.merge(merged_data, forecast_pivot, on='SKU', how='left')
        
        # Add product family info
        family_data = product_families[['SKU', 'Product_Family']]
        merged_data = pd.merge(merged_data, family_data, on='SKU', how='left')
        
        # Store processed data
        self.processed_data = merged_data
        self.budget_data = budget_data.pivot(
            index='Product_Family', columns='Month', values='Budget_EUR'
        ).add_prefix('Budget_')
        
        # Extract unique families and their SKUs
        self.families = merged_data['Product_Family'].unique()
        self.family_skus = {}
        for family in self.families:
            self.family_skus[family] = merged_data[merged_data['Product_Family'] == family]['SKU'].tolist()
        
        # Refresh the SKU Inspector's searchable SKU list
        self.all_skus = sorted(merged_data['SKU'].astype(str).tolist())
        if hasattr(self, 'inspector_sku_combo'):
            self.inspector_sku_combo['values'] = self.all_skus
            if self.all_skus and not self.inspector_sku_var.get():
                self.inspector_sku_var.set(self.all_skus[0])
                self.load_sku_into_inspector()

        # Refresh the Budget tab (Total Monthly Budget / Family Split rows)
        # to match the currently loaded families, and recompute
        # self.budget_data from it -- falling back to this file's own Budget
        # tab as defaults the first time, or after loading a file with a
        # different family set. This intentionally OVERWRITES the plain
        # Excel-pivot self.budget_data assignment just above, once the
        # Budget tab has something to say about it.
        self._sync_budget_tab_with_families()
    
    def load_sample_data(self):
        """Create and load realistic sample data for 100 SKUs"""
        self.status_var.set("Creating sample data...")
        self.root.update()
        
        try:
            # Create sample data
            sample_data = self.data_generator.generate()
            
            # Save to temporary file
            temp_file = "sample_inventory_data.xlsx"
            with pd.ExcelWriter(temp_file, engine='openpyxl') as writer:
                for sheet_name, df in sample_data.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Load the sample data
            self.load_excel_data(temp_file)
            self.input_file = temp_file
            self.file_path_var.set(temp_file)
            self.status_var.set(f"Sample data loaded: {temp_file}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create sample data: {str(e)}")
            self.status_var.set("Error creating sample data")
    
    def calculate_all_scenarios(self):
        """Calculate all three scenarios on a background thread, so the GUI
        stays responsive, with a determinate progress bar driven by the
        calculator's progress_callback. The scipy optimization in the
        Constraint scenario alone can take 20-50+ seconds for a real catalog;
        previously this froze the whole window with no feedback."""
        if self.processed_data is None:
            messagebox.showerror("Error", "No data loaded! Please load data first.")
            return
        
        if self._calc_running:
            return  # a calculation is already in progress
        
        self._calc_running = True
        self._set_busy_state(True)
        self.progress_bar['value'] = 0
        self.status_var.set("Calculating scenarios...")
        
        # Snapshot the inputs the worker thread will read, so nothing else
        # (e.g. loading a new file) can mutate them out from under it
        data_snapshot = self.processed_data
        budget_snapshot = self.budget_data
        families_snapshot = self.families
        family_skus_snapshot = self.family_skus
        calculator = self.calculator
        
        def report_progress(fraction, message):
            self._progress_queue.put(('progress', fraction, message))
        
        def worker():
            try:
                scenarios = calculator.calculate_all_scenarios(
                    data_snapshot, budget_snapshot, families_snapshot, family_skus_snapshot,
                    progress_callback=report_progress
                )
                self._progress_queue.put(('done', scenarios, None))
            except Exception as e:
                import traceback
                self._progress_queue.put(('error', str(e), traceback.format_exc()))
        
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_progress_queue)
    
    def _set_busy_state(self, busy):
        """Disable/enable the buttons and data-loading controls that would
        race with a background calculation if clicked mid-run."""
        state = tk.DISABLED if busy else tk.NORMAL
        for widget in (self.calc_button, self.recalc_button, self.export_button,
                       self.browse_button, self.sample_button):
            widget['state'] = state
    
    def _poll_progress_queue(self):
        """Runs on the main thread via root.after(); drains progress/result
        messages posted by the background calculation thread. Tkinter widgets
        must only be touched from the main thread, which is why the worker
        thread never updates them directly -- it just posts to the queue."""
        try:
            while True:
                kind, payload, extra = self._progress_queue.get_nowait()
                
                if kind == 'progress':
                    fraction = payload
                    self.progress_bar['value'] = fraction * 100
                    self.status_var.set(extra)
                
                elif kind == 'done':
                    self.scenarios = payload
                    future_months = self.scenarios.get('as_is', {}).get('future_months', [])
                    self.update_all_visualizations(future_months)
                    self.progress_bar['value'] = 100
                    self.status_var.set("All scenarios calculated successfully!")
                    self._calc_running = False
                    self._set_busy_state(False)
                    messagebox.showinfo("Success", "All scenarios calculated successfully!")
                    return  # stop polling
                
                elif kind == 'error':
                    print(extra)  # full traceback to the console/log
                    self.status_var.set("Error calculating scenarios")
                    self._calc_running = False
                    self._set_busy_state(False)
                    messagebox.showerror("Error", f"Failed to calculate scenarios: {payload}")
                    return  # stop polling
        except queue.Empty:
            pass
        
        if self._calc_running:
            self.root.after(100, self._poll_progress_queue)
    
    def recalculate(self):
        """Recalculate with current settings"""
        self.calculate_all_scenarios()
    
    def update_all_visualizations(self, future_months):
        """Update all visualizations with current scenario data"""
        self.update_as_is_tab(future_months)
        self.update_constraint_tab(future_months)
        self.update_optimized_tab(future_months)
        self.update_comparison_tab(future_months)
    
    def setup_as_is_tab(self):
        """Setup the As-Is scenario tab"""
        # Summary frame
        summary_frame = ttk.LabelFrame(self.tab_as_is, text="Summary", padding="10")
        summary_frame.pack(fill=tk.X, pady=5)
        
        self.as_is_summary_text = tk.Text(summary_frame, height=10, wrap=tk.WORD)
        self.as_is_summary_text.pack(fill=tk.BOTH, expand=True)
        
        # Visualization frame
        viz_frame = ttk.LabelFrame(self.tab_as_is, text="Inventory Projection", padding="10")
        viz_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.as_is_plot_frame = ttk.Frame(viz_frame)
        self.as_is_plot_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add stacked line diagram frame
        stacked_frame = ttk.LabelFrame(self.tab_as_is, text="Stacked Inventory by Family", padding="10")
        stacked_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.as_is_stacked_frame = ttk.Frame(stacked_frame)
        self.as_is_stacked_frame.pack(fill=tk.BOTH, expand=True)
    
    def setup_constraint_tab(self):
        """Setup the Constraint scenario tab"""
        # Summary frame
        summary_frame = ttk.LabelFrame(self.tab_constraint, text="Summary", padding="10")
        summary_frame.pack(fill=tk.X, pady=5)
        
        self.constraint_summary_text = tk.Text(summary_frame, height=10, wrap=tk.WORD)
        self.constraint_summary_text.pack(fill=tk.BOTH, expand=True)
        
        # Visualization frame
        viz_frame = ttk.LabelFrame(self.tab_constraint, text="Optimized Inventory", padding="10")
        viz_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.constraint_plot_frame = ttk.Frame(viz_frame)
        self.constraint_plot_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add stacked line diagram frame
        stacked_frame = ttk.LabelFrame(self.tab_constraint, text="Stacked Inventory by Family", padding="10")
        stacked_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.constraint_stacked_frame = ttk.Frame(stacked_frame)
        self.constraint_stacked_frame.pack(fill=tk.BOTH, expand=True)
    
    def setup_optimized_tab(self):
        """Setup the Optimized scenario tab"""
        # Summary frame
        summary_frame = ttk.LabelFrame(self.tab_optimized, text="Summary", padding="10")
        summary_frame.pack(fill=tk.X, pady=5)
        
        self.optimized_summary_text = tk.Text(summary_frame, height=10, wrap=tk.WORD)
        self.optimized_summary_text.pack(fill=tk.BOTH, expand=True)
        
        # Visualization frame
        viz_frame = ttk.LabelFrame(self.tab_optimized, text="Required Inventory", padding="10")
        viz_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.optimized_plot_frame = ttk.Frame(viz_frame)
        self.optimized_plot_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add stacked line diagram frame
        stacked_frame = ttk.LabelFrame(self.tab_optimized, text="Stacked Inventory by Family", padding="10")
        stacked_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.optimized_stacked_frame = ttk.Frame(stacked_frame)
        self.optimized_stacked_frame.pack(fill=tk.BOTH, expand=True)
    
    def setup_comparison_tab(self):
        """Setup the comparison tab"""
        # Scenarios comparison plot
        scenarios_frame = ttk.LabelFrame(self.tab_comparison, text="Scenarios Comparison", padding="10")
        scenarios_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.scenarios_plot_frame = ttk.Frame(scenarios_frame)
        self.scenarios_plot_frame.pack(fill=tk.BOTH, expand=True)
        
        # Service levels comparison
        sl_frame = ttk.LabelFrame(self.tab_comparison, text="Service Levels Comparison", padding="10")
        sl_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.sl_plot_frame = ttk.Frame(sl_frame)
        self.sl_plot_frame.pack(fill=tk.BOTH, expand=True)
        
        # Budget comparison
        budget_frame = ttk.LabelFrame(self.tab_comparison, text="Budget Analysis", padding="10")
        budget_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.budget_plot_frame = ttk.Frame(budget_frame)
        self.budget_plot_frame.pack(fill=tk.BOTH, expand=True)

        # Budget (maximum) vs. ALL scenarios, over time, per family
        budget_ts_frame = ttk.LabelFrame(
            self.tab_comparison, text="Budget (Maximum) vs. All Scenarios Over Time, by Family", padding="10"
        )
        budget_ts_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.budget_vs_scenarios_frame = ttk.Frame(budget_ts_frame)
        self.budget_vs_scenarios_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add stacked comparison
        stacked_comp_frame = ttk.LabelFrame(self.tab_comparison, text="Stacked Comparison All Scenarios", padding="10")
        stacked_comp_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.stacked_comp_frame = ttk.Frame(stacked_comp_frame)
        self.stacked_comp_frame.pack(fill=tk.BOTH, expand=True)
    
    def update_as_is_tab(self, future_months):
        """Update As-Is tab with data"""
        if 'as_is' not in self.scenarios:
            return
        
        scenario = self.scenarios['as_is']
        
        # Update summary text
        self.as_is_summary_text.delete(1.0, tk.END)
        
        summary = "=== As-Is Scenario Summary ===\n\n"
        summary += f"Total SKUs: {len(scenario['sku_projections'])}\n"
        summary += f"Product Families: {len(scenario['family_projections'])}\n"
        summary += f"Future Months: {len(future_months)}\n\n"
        
        # Alerts
        summary += f"Alerts: {len(scenario['alerts'])}\n"
        for alert in scenario['alerts'][:10]:
            summary += f"  - {alert['Type']}: {alert['SKU']} ({alert['Family']}) in {alert['Month']}: {alert['Message']}\n"
        if len(scenario['alerts']) > 10:
            summary += f"  ... and {len(scenario['alerts']) - 10} more alerts\n\n"
        
        # Service level hints
        summary += f"Service Level Adjustments Needed: {len(scenario['service_level_hints'])}\n"
        for hint in scenario['service_level_hints'][:5]:
            summary += f"  - {hint['SKU']}: Current SL={hint['Current_SL']:.2f}, Target={hint['Target_SL']:.2f} - {hint['Suggestion']}\n"
        if len(scenario['service_level_hints']) > 5:
            summary += f"  ... and {len(scenario['service_level_hints']) - 5} more hints\n\n"
        
        # Budget deviations
        summary += "Budget Deviations:\n"
        for family, months in scenario['budget_deviations'].items():
            for month, dev in months.items():
                if abs(dev['Deviation_Pct']) > 10:
                    summary += f"  - {family} in {month}: {self.settings['currency']}{dev['Actual']:,.0f} vs Budget {self.settings['currency']}{dev['Budget']:,.0f} ({dev['Deviation_Pct']:+.1f}%)\n"
        
        self.as_is_summary_text.insert(tk.END, summary)
        
        # Update plots
        self.visualizer.plot_scenario(self.as_is_plot_frame, scenario, future_months, 'As-Is')
        self.visualizer.plot_stacked_scenario(self.as_is_stacked_frame, scenario, future_months, 'As-Is')
    
    def update_constraint_tab(self, future_months):
        """Update Constraint tab with data"""
        if 'constraint' not in self.scenarios:
            return
        
        scenario = self.scenarios['constraint']
        
        # Update summary text
        self.constraint_summary_text.delete(1.0, tk.END)
        
        summary = "=== Constraint Scenario Summary ===\n\n"
        summary += f"Optimization completed for {len(scenario['family_projections'])} families\n"
        summary += (
            "Budget is treated as a hard MAXIMUM, enforced for every month individually. "
            "Safety days are optimized on a ROLLING basis (recomputed fresh each month). "
            "If even minimum safety days can't fit the budget in a given month, supply is "
            "rationed (cycle stock itself is cut) and the achievable service level drops "
            "accordingly -- flagged below as 'Supply LIMITED'.\n"
        )
        summary += "\nPer-Family Results:\n"
        
        for family, proj in scenario['family_projections'].items():
            achievable = proj.get('achievable_service_level')
            limited = proj.get('supply_limited', False)
            achievable_str = f"{achievable:.1%}" if achievable is not None else "n/a"
            flag = "  \u26a0 Supply LIMITED (budget too tight even at minimum safety days)" if limited else ""
            summary += f"\n{family}: achievable service level ~{achievable_str}{flag}\n"
            family_skus_list = proj['skus']
            for sku in family_skus_list[:5]:
                if sku in scenario.get('optimized_params', {}):
                    params = scenario['optimized_params'][sku]
                    avg_days = params['safety_days']
                    schedule = params.get('safety_days_by_month', [])
                    rng = f" (rolling {min(schedule):.0f}-{max(schedule):.0f})" if schedule else ""
                    sku_flag = " [rationed]" if params.get('supply_limited') else ""
                    summary += f"  - {sku}: Safety Days ~{avg_days:.1f}{rng}{sku_flag}\n"
            if len(family_skus_list) > 5:
                summary += f"  ... and {len(family_skus_list) - 5} more SKUs\n"
        
        self.constraint_summary_text.insert(tk.END, summary)
        
        # Update plots
        if 'as_is' in self.scenarios:
            self.visualizer.plot_scenario(self.constraint_plot_frame, scenario, future_months, 'Constraint')
            self.visualizer.plot_stacked_scenario(self.constraint_stacked_frame, scenario, future_months, 'Constraint')
    
    def update_optimized_tab(self, future_months):
        """Update Optimized tab with data"""
        if 'optimized' not in self.scenarios:
            return
        
        scenario = self.scenarios['optimized']
        
        # Update summary text
        self.optimized_summary_text.delete(1.0, tk.END)
        
        summary = "=== Optimized Scenario Summary ===\n\n"
        summary += f"Required budgets to reach target service levels:\n\n"
        
        for family, proj in scenario['family_projections'].items():
            required_budget = proj.get('required_budget', 0)
            summary += f"{family}: {self.settings['currency']}{required_budget:,.0f}\n"
        
        summary += "\nRequired Safety Days:\n"
        for sku, proj in scenario['sku_projections'].items():
            required_days = proj.get('required_safety_days', 0)
            summary += f"{sku} ({proj['family']}): {required_days:.1f} days\n"
        
        self.optimized_summary_text.insert(tk.END, summary)
        
        # Update plots
        self.visualizer.plot_scenario(self.optimized_plot_frame, scenario, future_months, 'Optimized')
        self.visualizer.plot_stacked_scenario(self.optimized_stacked_frame, scenario, future_months, 'Optimized')
    
    def update_comparison_tab(self, future_months):
        """Update comparison tab with all scenarios"""
        if len(self.scenarios) < 3:
            return
        
        # Update scenarios comparison plot
        self.visualizer.plot_scenarios_comparison(
            self.scenarios_plot_frame, 
            self.scenarios, 
            self.families, 
            future_months
        )
        
        # Update service levels comparison
        self.visualizer.plot_service_levels_comparison(
            self.sl_plot_frame, 
            self.scenarios, 
            self.families
        )
        
        # Update budget analysis
        self.visualizer.plot_budget_analysis(
            self.budget_plot_frame, 
            self.scenarios, 
            self.families, 
            self.budget_data, 
            future_months
        )

        # Budget (maximum) vs. ALL scenarios, over time, per family -- this is
        # the "compare the optimal budget against As-Is/Constraint, across all
        # scenarios" view, on the Comparison tab (not on the Optimized
        # scenario's own tab).
        self.visualizer.plot_budget_vs_scenarios_timeseries(
            self.budget_vs_scenarios_frame,
            self.scenarios,
            self.families,
            self.budget_data,
            future_months
        )
        
        # Update stacked comparison
        self.visualizer.plot_all_scenarios_stacked(
            self.stacked_comp_frame, 
            self.scenarios, 
            self.families, 
            future_months
        )
    
    def setup_sku_inspector_tab(self):
        """Search/select a single SKU, view and edit its master data, and see
        the As-Is methodology numbers (safety stock, reorder point, XYZ class,
        achieved service level) plus its rolling 12-month projection recompute
        INSTANTLY -- without waiting for a full Calculate All Scenarios run.
        Uses InventoryCalculator.calculate_sku_as_is() directly, the same
        per-SKU engine the full As-Is scenario uses internally."""
        container = ttk.Frame(self.tab_inspector, padding="10")
        container.pack(fill=tk.BOTH, expand=True)
        
        # --- Search row ---
        search_frame = ttk.Frame(container)
        search_frame.pack(fill=tk.X, pady=5)
        ttk.Label(search_frame, text="SKU:", font=('Helvetica', 11, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        self.inspector_sku_combo = ttk.Combobox(search_frame, textvariable=self.inspector_sku_var,
                                                 width=20, values=self.all_skus)
        self.inspector_sku_combo.pack(side=tk.LEFT)
        self.inspector_sku_combo.bind('<<ComboboxSelected>>', self.load_sku_into_inspector)
        self.inspector_sku_combo.bind('<Return>', self.load_sku_into_inspector)
        self.inspector_sku_combo.bind('<KeyRelease>', self._filter_inspector_sku_list)
        ttk.Label(search_frame, text="(type to search, Enter or select to load)",
                  foreground="#666666").pack(side=tk.LEFT, padx=10)
        
        body = ttk.Frame(container)
        body.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # --- Editable master data ---
        edit_frame = ttk.LabelFrame(body, text="Master Data (editable)", padding="10")
        edit_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        field_specs = [
            ('ABC_Classification', 'ABC Classification', 'combo', ['A', 'B', 'C']),
            ('Production_Leadtime_Days', 'Lead Time (days)', 'entry', None),
            ('Safety_Days_of_Supply', 'Safety Days of Supply', 'entry', None),
            ('Min_Order_Qty', 'Min Order Qty (MOQ)', 'entry', None),
            ('Price_EUR', 'Price (EUR)', 'entry', None),
            ('Current_Inventory', 'Current Inventory', 'entry', None),
        ]
        for r, (col, label, kind, options) in enumerate(field_specs):
            ttk.Label(edit_frame, text=label + ":").grid(row=r, column=0, sticky=tk.W, pady=3)
            var = tk.StringVar()
            if kind == 'combo':
                widget = ttk.Combobox(edit_frame, textvariable=var, values=options, width=15, state='readonly')
            else:
                widget = ttk.Entry(edit_frame, textvariable=var, width=17)
            widget.grid(row=r, column=1, sticky=tk.W, pady=3, padx=5)
            self.inspector_fields[col] = var
        
        btn_frame = ttk.Frame(edit_frame)
        btn_frame.grid(row=len(field_specs), column=0, columnspan=2, pady=(10, 5))
        ttk.Button(btn_frame, text="Apply & Recalc This SKU", command=self.apply_sku_changes,
                   style="Accent.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="Reset", command=self.load_sku_into_inspector).pack(side=tk.LEFT, padx=3)
        
        ttk.Label(
            edit_frame,
            text=("Updates the numbers here instantly.\nClick the main Recalculate button\n"
                  "to also reflect this in the budget-\noptimized Constraint/Optimized\nscenarios."),
            foreground="#555555", justify=tk.LEFT
        ).grid(row=len(field_specs) + 1, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
        
        # --- Computed / diagnostic read-out ---
        computed_frame = ttk.LabelFrame(body, text="As-Is Methodology (computed)", padding="10")
        computed_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        computed_specs = [
            ('family', 'Product Family'),
            ('xyz', 'XYZ Class (demand CV)'),
            ('avg_demand', 'Avg Monthly Demand'),
            ('safety_stock', 'Safety Stock (current policy)'),
            ('required_safety_days', 'Required Safety Days (target)'),
            ('reorder_point', 'Reorder Point'),
            ('service_level', 'Achieved / Target CSL'),
        ]
        for r, (key, label) in enumerate(computed_specs):
            ttk.Label(computed_frame, text=label + ":").grid(row=r, column=0, sticky=tk.W, pady=3)
            var = tk.StringVar(value="-")
            ttk.Label(computed_frame, textvariable=var, font=('Helvetica', 10, 'bold')).grid(
                row=r, column=1, sticky=tk.W, pady=3, padx=5)
            self.inspector_computed_vars[key] = var
        
        self.inspector_alerts_var = tk.StringVar(value="-")
        ttk.Label(computed_frame, text="Alerts (this SKU):").grid(
            row=len(computed_specs), column=0, sticky=tk.NW, pady=3)
        ttk.Label(computed_frame, textvariable=self.inspector_alerts_var, wraplength=200,
                  justify=tk.LEFT).grid(row=len(computed_specs), column=1, sticky=tk.W, pady=3, padx=5)
        
        # --- Mini interactive chart ---
        chart_frame = ttk.LabelFrame(body, text="12-Month Rolling Projection", padding="10")
        chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inspector_chart_frame = ttk.Frame(chart_frame)
        self.inspector_chart_frame.pack(fill=tk.BOTH, expand=True)
        
        if self.all_skus:
            self.inspector_sku_var.set(self.all_skus[0])
            self.load_sku_into_inspector()
    
    def _filter_inspector_sku_list(self, event=None):
        """Search-as-you-type filtering for the SKU combobox."""
        if event is not None and event.keysym in ('Return', 'Up', 'Down'):
            return
        typed = self.inspector_sku_var.get().strip().upper()
        if not typed:
            self.inspector_sku_combo['values'] = self.all_skus
            return
        filtered = [s for s in self.all_skus if typed in s.upper()]
        self.inspector_sku_combo['values'] = filtered
    
    def load_sku_into_inspector(self, event=None):
        """Load the selected SKU's current master data + computed metrics
        into the Inspector tab (also used by the Reset button)."""
        if self.processed_data is None:
            return
        sku = self.inspector_sku_var.get().strip()
        if not sku:
            return
        matches = self.processed_data[self.processed_data['SKU'].astype(str) == sku]
        if matches.empty:
            return
        row = matches.iloc[0]
        
        self.inspector_fields['ABC_Classification'].set(str(row.get('ABC_Classification', 'C')))
        self.inspector_fields['Production_Leadtime_Days'].set(str(row.get('Production_Leadtime_Days', 0)))
        self.inspector_fields['Safety_Days_of_Supply'].set(str(row.get('Safety_Days_of_Supply', 0)))
        self.inspector_fields['Min_Order_Qty'].set(str(row.get('Min_Order_Qty', 0)))
        self.inspector_fields['Price_EUR'].set(str(row.get('Price_EUR', 0)))
        self.inspector_fields['Current_Inventory'].set(str(row.get('Current_Inventory', 0)))
        
        self._refresh_inspector_computed(row)
    
    def apply_sku_changes(self):
        """Write the edited fields back into processed_data for this SKU and
        instantly recompute its As-Is projection -- no full scenario rerun,
        so this is near-instant even though Calculate All Scenarios can take
        20-50+ seconds. Constraint/Optimized still need a full Recalculate,
        since those re-optimize jointly across the whole family's budget."""
        if self.processed_data is None:
            return
        sku = self.inspector_sku_var.get().strip()
        if not sku:
            return
        mask = self.processed_data['SKU'].astype(str) == sku
        if not mask.any():
            messagebox.showerror("Error", f"SKU '{sku}' not found.")
            return
        
        try:
            abc = self.inspector_fields['ABC_Classification'].get().strip().upper()
            if abc not in ('A', 'B', 'C'):
                raise ValueError("ABC Classification must be A, B, or C")
            lead_time = float(self.inspector_fields['Production_Leadtime_Days'].get())
            safety_days = float(self.inspector_fields['Safety_Days_of_Supply'].get())
            moq = float(self.inspector_fields['Min_Order_Qty'].get())
            price = float(self.inspector_fields['Price_EUR'].get())
            current_inv = float(self.inspector_fields['Current_Inventory'].get())
            if min(lead_time, safety_days, moq, price, current_inv) < 0:
                raise ValueError("values must be zero or positive")
        except ValueError as e:
            messagebox.showerror("Invalid input", f"Please check the values entered: {e}")
            return
        
        self.processed_data.loc[mask, 'ABC_Classification'] = abc
        self.processed_data.loc[mask, 'Production_Leadtime_Days'] = lead_time
        self.processed_data.loc[mask, 'Safety_Days_of_Supply'] = safety_days
        self.processed_data.loc[mask, 'Min_Order_Qty'] = moq
        self.processed_data.loc[mask, 'Price_EUR'] = price
        self.processed_data.loc[mask, 'Current_Inventory'] = current_inv
        
        row = self.processed_data[mask].iloc[0]
        self._refresh_inspector_computed(row)
        self.status_var.set(
            f"Applied changes to {sku}. Click Recalculate to reflect this in the Constraint/Optimized scenarios too."
        )
    
    def _refresh_inspector_computed(self, row):
        """Recompute the selected SKU's As-Is methodology numbers and refresh
        both the read-out labels and the mini chart."""
        demand_columns = [c for c in self.processed_data.columns if c.startswith('Demand_')]
        future_months = sorted(
            [c.replace('Demand_', '') for c in demand_columns],
            key=lambda x: int(x.replace('M_', ''))
        )
        monthly_demand = [row.get(f'Demand_{m}', 0) for m in future_months]
        fa_columns = [c for c in self.processed_data.columns if c.startswith('FA_')]
        fa_values = [row.get(c, 0) for c in fa_columns if row.get(c, 0) > 0]
        avg_fa = np.mean(fa_values) if fa_values else 0.9
        abc = row.get('ABC_Classification', 'C')
        target_sl = self.settings['default_service_levels'].get(abc, 0.95)
        sku = str(row['SKU'])
        
        result = self.calculator.calculate_sku_as_is(
            sku, row.get('Product_Family', ''), row.get('Price_EUR', 0), abc,
            row.get('Production_Leadtime_Days', 0), row.get('Safety_Days_of_Supply', 0),
            row.get('Min_Order_Qty', 0), row.get('Current_Inventory', 0),
            monthly_demand, future_months, avg_fa, target_sl
        )
        
        avg_demand = np.mean(monthly_demand) if monthly_demand else 0
        daily_demand = avg_demand / 30 if avg_demand else 0
        required_days = (result['required_safety_stock'] / daily_demand) if daily_demand > 0 else 0
        
        self.inspector_computed_vars['family'].set(str(row.get('Product_Family', '-')))
        self.inspector_computed_vars['xyz'].set(f"{result['xyz']} (CV={result['demand_cv']:.2f})")
        self.inspector_computed_vars['avg_demand'].set(f"{avg_demand:,.0f} units/mo")
        self.inspector_computed_vars['safety_stock'].set(f"{result['safety_stock']:,.0f} units")
        self.inspector_computed_vars['required_safety_days'].set(f"{required_days:.1f} days")
        self.inspector_computed_vars['reorder_point'].set(f"{result['reorder_point']:,.0f} units")
        self.inspector_computed_vars['service_level'].set(
            f"{result['expected_service_level']:.1%} / {result['target_service_level']:.0%}"
        )
        
        if result['alerts']:
            lines = [f"{a['Month']}: {a['Type']}" for a in result['alerts'][:6]]
            if len(result['alerts']) > 6:
                lines.append(f"... +{len(result['alerts']) - 6} more")
            self.inspector_alerts_var.set("\n".join(lines))
        else:
            self.inspector_alerts_var.set("None")
        
        self.inspector_canvas = self.visualizer.plot_sku_detail(
            self.inspector_chart_frame, sku, result, future_months, self.inspector_canvas
        )
    
    def export_results(self):
        """Export all results to Excel"""
        if len(self.scenarios) < 3:
            messagebox.showerror("Error", "Not all scenarios calculated yet!")
            return
        
        try:
            file_path = filedialog.asksaveasfilename(
                title="Save Results",
                defaultextension=".xlsx",
                filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")]
            )
            
            if not file_path:
                return
            
            self.status_var.set("Exporting results...")
            self.root.update()
            
            future_months = self.scenarios.get('as_is', {}).get('future_months', [])
            all_months = ['Current'] + future_months
            
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # Export each scenario
                for scenario_type, scenario in self.scenarios.items():
                    # SKU-level data
                    sku_data = []
                    for sku, proj in scenario['sku_projections'].items():
                        row = {
                            'Scenario': scenario_type,
                            'SKU': sku,
                            'Family': proj['family'],
                            'ABC': proj['abc'],
                            'XYZ': proj.get('xyz', ''),
                            'Demand_CV': proj.get('demand_cv', ''),
                            'Price_EUR': proj['price'],
                            'Min_Order_Qty': proj.get('min_order_qty', 0),
                            'Lead_Time_Days': proj.get('lead_time', 0),
                            'Safety_Days': proj.get('safety_days', 0)
                        }
                        
                        # Add inventory data
                        for i, month in enumerate(all_months):
                            if i < len(proj['inventory']):
                                row[f'Inv_{month}'] = proj['inventory'][i]
                                row[f'Inv_Value_{month}'] = proj['inventory_value'][i]
                        
                        # Add demand data
                        for i, month in enumerate(future_months):
                            if i < len(proj.get('demand', [])):
                                row[f'Demand_{month}'] = proj['demand'][i]
                        
                        # Add other metrics
                        row['Safety_Stock'] = proj.get('safety_stock', 0)
                        row['Reorder_Point'] = proj.get('reorder_point', 0)
                        row['Expected_SL'] = proj.get('expected_service_level', 0)
                        row['Target_SL'] = proj.get('target_service_level', 0)
                        
                        if scenario_type == 'optimized':
                            row['Required_Safety_Days'] = proj.get('required_safety_days', 0)

                        if scenario_type == 'constraint':
                            row['Supply_Limited'] = proj.get('supply_limited', False)
                            schedule = proj.get('safety_days_by_month')
                            if schedule:
                                for i, month in enumerate(future_months):
                                    if i < len(schedule):
                                        row[f'Safety_Days_{month}'] = schedule[i]
                            fill_schedule = proj.get('fill_ratio_by_month')
                            if fill_schedule:
                                for i, month in enumerate(future_months):
                                    if i < len(fill_schedule):
                                        row[f'Fill_Ratio_{month}'] = fill_schedule[i]
                        
                        sku_data.append(row)
                    
                    sku_df = pd.DataFrame(sku_data)
                    sku_df.to_excel(writer, sheet_name=f"{scenario_type}_SKUs", index=False)
                    
                    # Family-level data
                    family_data = []
                    for family, proj in scenario['family_projections'].items():
                        row = {
                            'Scenario': scenario_type,
                            'Family': family,
                            'Num_SKUs': len(proj['skus'])
                        }
                        
                        for i, month in enumerate(all_months):
                            if i < len(proj['inventory']):
                                row[f'Inv_{month}'] = proj['inventory'][i]
                                row[f'Inv_Value_{month}'] = proj['inventory_value'][i]
                        
                        if scenario_type == 'optimized':
                            row['Required_Budget'] = proj.get('required_budget', 0)

                        if scenario_type == 'constraint':
                            row['Achievable_Service_Level'] = proj.get('achievable_service_level')
                            row['Supply_Limited'] = proj.get('supply_limited', False)
                        
                        family_data.append(row)
                    
                    family_df = pd.DataFrame(family_data)
                    family_df.to_excel(writer, sheet_name=f"{scenario_type}_Families", index=False)
                    
                    # Alerts and hints (for As-Is)
                    if scenario_type == 'as_is':
                        alerts_df = pd.DataFrame(scenario.get('alerts', []))
                        if not alerts_df.empty:
                            alerts_df.to_excel(writer, sheet_name="Alerts", index=False)
                        
                        hints_df = pd.DataFrame(scenario.get('service_level_hints', []))
                        if not hints_df.empty:
                            hints_df.to_excel(writer, sheet_name="Service_Level_Hints", index=False)
                        
                        budget_dev_df = []
                        for family, months in scenario.get('budget_deviations', {}).items():
                            for month, dev in months.items():
                                budget_dev_df.append({
                                    'Family': family,
                                    'Month': month,
                                    'Actual': dev['Actual'],
                                    'Budget': dev['Budget'],
                                    'Deviation': dev['Deviation'],
                                    'Deviation_Pct': dev['Deviation_Pct']
                                })
                        if budget_dev_df:
                            pd.DataFrame(budget_dev_df).to_excel(writer, sheet_name="Budget_Deviations", index=False)
                    
                    # Optimized parameters (for Constraint)
                    if scenario_type == 'constraint' and 'optimized_params' in scenario:
                        params_data = []
                        for sku, params in scenario['optimized_params'].items():
                            entry = {
                                'SKU': sku,
                                'Family': params['family'],
                                'Avg_Optimized_Safety_Days': params['safety_days'],
                                'Supply_Limited': params.get('supply_limited', False)
                            }
                            schedule = params.get('safety_days_by_month', [])
                            for i, month in enumerate(future_months):
                                if i < len(schedule):
                                    entry[f'Safety_Days_{month}'] = schedule[i]
                            params_data.append(entry)
                        if params_data:
                            pd.DataFrame(params_data).to_excel(writer, sheet_name="Optimized_Params", index=False)
                    
                    # Required budgets (for Optimized)
                    if scenario_type == 'optimized' and 'required_budgets' in scenario:
                        budgets_data = []
                        for family, budgets in scenario['required_budgets'].items():
                            for budget in budgets:
                                budgets_data.append({
                                    'Family': family,
                                    'Required_Budget': budget
                                })
                        if budgets_data:
                            pd.DataFrame(budgets_data).to_excel(writer, sheet_name="Required_Budgets", index=False)

                # Export the Budget-tab settings (Total Monthly Budget + Family Split)
                if self.budget_settings:
                    budget_settings_rows = []
                    for m in BUDGET_MONTHS:
                        budget_settings_rows.append({
                            'Month': m,
                            'Total_Budget_EUR': self.budget_settings['monthly_total_eur'].get(m, 0)
                        })
                    pd.DataFrame(budget_settings_rows).to_excel(writer, sheet_name="Budget_Total_By_Month", index=False)

                    split_rows = [
                        {'Family': f, 'Split_Pct': pct}
                        for f, pct in self.budget_settings['family_split_pct'].items()
                    ]
                    pd.DataFrame(split_rows).to_excel(writer, sheet_name="Budget_Family_Split", index=False)
                
                # Export settings
                settings_df = pd.DataFrame([self.settings])
                settings_df.to_excel(writer, sheet_name="Settings", index=False)
            
            self.status_var.set(f"Results exported to: {file_path}")
            messagebox.showinfo("Success", f"Results exported successfully to:\n{file_path}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export results: {str(e)}")
            self.status_var.set("Error exporting results")
            import traceback
            traceback.print_exc()


def main():
    root = tk.Tk()
    app = InventoryOptimizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
