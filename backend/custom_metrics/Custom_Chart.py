# Name: Custom Chart
# Description: Base chart
# Created: 2025-03-13 22:09:42.131598

# Available modules and functions:
# - pd (pandas)
# - np (numpy)
# - system() - returns strategy groups data
# - quant_stats(strategy_name, strategy_data, benchmark_name, benchmark_data)

import pandas as pd
import numpy as np

# Get data from system
strategy_groups = system()
portfolio_data = strategy_groups.get("portfolio")

# Process the data
processed_data = pd.to_numeric(portfolio_data, errors='coerce')
processed_data = processed_data.dropna().pct_change().dropna()

# Create chart data structure for Chart.js
dates = processed_data.index.strftime('%Y-%m-%d').tolist()
values = processed_data.values.tolist()

# Define the chart_data object that will be displayed
chart_data = {
    "labels": dates,
    "datasets": [
        {
            "label": "My Custom Portfolio Metric",
            "data": values,
            "borderColor": "#ff5c00",
            "backgroundColor": "#ff5c00",
            "borderWidth": 2,
            "tension": 0,
            "pointRadius": 0,
        }
    ]
}

print(f"Created chart with {len(dates)} data points")
print(f"Date range: {dates[0]} to {dates[-1]}")

def custom_metric(data=None):
    return {
        "success": True,
        "chart_data": chart_data,
        "metric_value": np.mean(values) if values else 0
    }
