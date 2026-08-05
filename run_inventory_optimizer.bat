@echo off
chcp 65001 >nul
echo Starting Inventory Optimizer...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if required packages are installed
echo Checking required packages...
python -c "import pandas, numpy, matplotlib, scipy, openpyxl, tkinter, mplcursors" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install pandas numpy matplotlib scipy openpyxl mplcursors
    if errorlevel 1 (
        echo Error: Failed to install packages
        pause
        exit /b 1
    )
)

REM Run the application (opens the GUI directly)
echo Starting Inventory Optimizer Application...
echo Press Ctrl+C to exit
echo.
python run_inventory_optimizer.py

pause
