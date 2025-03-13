from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import io
import contextlib

from system import system_lmao
from quant import quant_stats
from data_munging import replace_nan_and_inf, replace_infinity_with_neg_one

app = Flask(__name__)
CORS(app)

import traceback
import logging

logging.basicConfig(level=logging.ERROR)

@app.route('/api/glassfactory', methods=['POST'])
def glass_factory():
    """
    Executes Python code passed in the JSON payload and returns its output.
    Expected JSON format:
      { "code": "print('Hello, World!')" }
    """
    try:
        data = request.get_json()
        if not data or "code" not in data:
            return jsonify({"error": "No code provided"}), 400
        
        code = data["code"]

        # Create a dictionary for local variables
        local_vars = {}
        
        # Create a dictionary with available modules and functions
        global_vars = {
            'pd': pd,
            'np': np,
            'system_lmao': system_lmao,
            'quant_stats': quant_stats,
            # Add any other modules or functions you want to make available
        }

        # Prepare to capture stdout
        output = io.StringIO()
        
        with contextlib.redirect_stdout(output):
            exec(code, global_vars, local_vars)

        result = output.getvalue()
        response_data = {"result": result}
        
        # Check if chart_data was created in the code execution
        if 'chart_data' in local_vars:
            # Add chart data to response
            response_data['chart_data'] = local_vars['chart_data']
            
        return jsonify(response_data)
    except Exception as e:
        logging.error("Error in /api/glassfactory: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/quantstats', methods=['POST'])
def algo_scope():
    """
    Calls system_lmao() to obtain portfolio-level positions and provide processed data to front-end.
    
    Returns
    -------
    results : dict
        Jsonified dictionary of processed data filtered by the selected category.
    """
    try:
        req_data = request.get_json()
        # Get category (default "portfolio")
        category = req_data.get("category", "portfolio")
        # Get the date range filter as [start, end] timestamps (milliseconds)
        date_range = req_data.get("dateRange", None)
        print("Selected category:", category)

        strategy_name = "Mean Reversion"
        benchmark_name = "Index"

        # Get the grouped dataframes from system_lmao
        strategy_groups = system_lmao()

        # Extract the appropriate series based on category.
        if category == "portfolio":
            strategy_filtered = strategy_groups.get("portfolio")
        else:
            group_df = strategy_groups.get(category)
            if group_df is None:
                raise ValueError(f"No data available for category '{category}'.")
            # Pivot to get a series of average closes.
            pivot = group_df.pivot_table(values='close', index=group_df.index, columns='symbol')
            strategy_filtered = pivot.mean(axis=1).squeeze()

        if strategy_filtered is None:
            raise ValueError(f"No data available for category '{category}'.")

        # ----- Apply date range filtering BEFORE processing -----
        # Apply date range filtering BEFORE processing
        if date_range and isinstance(date_range, list) and len(date_range) == 2:
            start = pd.to_datetime(date_range[0], unit='ms')
            end = pd.to_datetime(date_range[1], unit='ms')
            # Filter the raw strategy data
            strategy_filtered = strategy_filtered.loc[(strategy_filtered.index >= start) & (strategy_filtered.index <= end)]


        # Process the strategy series: convert to numeric, drop NAs, and compute percentage change.
        strategy_processed = pd.to_numeric(strategy_filtered, errors='coerce')
        strategy_processed = strategy_processed.dropna().pct_change().dropna()

        # ----- Load benchmark data -----
        sg_trend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'SG Trend Index.xlsx'))
        benchmark = pd.read_excel(sg_trend_dir, skiprows=6)
        benchmark.columns = [col.strip() for col in benchmark.columns]
        benchmark.rename(columns={'PX_LAST': 'close', 'date': 'Date'}, inplace=True)
        benchmark['Date'] = pd.to_datetime(benchmark['Date'])
        benchmark.set_index('Date', inplace=True)
        benchmark = benchmark.squeeze()

        # ----- Apply date range filtering to benchmark as well -----
        if date_range and isinstance(date_range, list) and len(date_range) == 2:
            # Reuse start and end defined above
            benchmark = benchmark.loc[(benchmark.index >= start) & (benchmark.index <= end)]

        # Ensure both series are sorted.
        strategy_processed = strategy_processed.sort_index(ascending=True)
        benchmark = benchmark.sort_index(ascending=True)

        # Align both series on their common dates.
        common_dates = strategy_processed.index.intersection(benchmark.index)
        strategy_processed = strategy_processed.loc[common_dates]
        benchmark = benchmark.loc[common_dates]

        # Run quant_stats calculations.
        results = quant_stats(strategy_name, strategy_processed, benchmark_name, benchmark)
        results = replace_infinity_with_neg_one(results)
        results = replace_nan_and_inf(results)

        return jsonify(results), 200

    except ImportError as e:
        print(f"Error importing user function: {e}")
        return jsonify({"error": "Failed to load user function"}), 500
    except Exception as e:
        logging.error("Error in /api/quantstats: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    try:
        app.run(debug=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nShutting down server.")
