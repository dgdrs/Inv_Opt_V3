#!/usr/bin/env python3
"""
Main entry point for Inventory Optimization Application
Run this file to start the application.
"""

import sys
import os

# Add the directory containing the package to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import the main app
from inventory_optimizer.app import main

if __name__ == "__main__":
    main()
