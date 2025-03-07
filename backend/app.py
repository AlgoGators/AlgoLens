from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import os
import io
import contextlib

from system import system_lmao
from quant import quant_stats
from data_munging import replace_nan_and_inf, replace_infinity_with_neg_one

app = Flask(__name__)
CORS(app)

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

        # Prepare to capture stdout.
        output = io.StringIO()
        # Execute the code in a restricted namespace (empty globals)
        with contextlib.redirect_stdout(output):
            exec(code, {})

        result = output.getvalue()
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/quantstats', methods=['POST'])
def algo_scope():
    """
    Calls algo() function from the system to obtain portfolio-level positions
    and provide processed data to front-end.
    
    Returns
    -------
    results : dict
        Jsonified dictionary of processed data filtered by the selected category.
    """
    try:
        # Read the JSON payload from the request.
        req_data = request.get_json()
        # The 'category' parameter should be passed from the client (defaulting to 'portfolio')
        category = req_data.get("category", "portfolio")
        print("Selected category:", category)

        strategy_name = "Mean Reversion"
        benchmark_name = "SPY"

        # Determine the base directory (assumes this file is one level down from the project root)
        #base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        #print("Base directory:", base_dir)

        # Discover the decorated functions from the project.
        #func = discover_decorated_functions(base_dir)
        # Execute the function to get the strategy data
        strategy = system_lmao()
        

        # Filter the strategy data based on the selected category.
        if category == "portfolio":
            portfolio_df = strategy.get("portfolio")
            if portfolio_df is None or "portfolio" not in portfolio_df.columns:
                raise ValueError("Portfolio data not found.")
            # Extract only the 'portfolio' column (as a 1D Series)
            strategy_filtered = portfolio_df["portfolio"]
        else:
            # For categories like 'futures', 'stocks', or 'options'
            strategy_filtered = strategy.get("group_dataframes", {}).get(category)
        
        if strategy_filtered is None:
            raise ValueError(f"No data available for category '{category}'.")

        print(strategy_filtered)

        strategy = strategy_filtered
        # Return as JSON. Convert the Series to a dictionary

        sg_trend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'SG Trend Index.xlsx'))

        # Load and inspect the benchmark data
        benchmark = pd.read_excel(sg_trend_dir, skiprows=6)

        # Clean up column names
        benchmark.columns = [col.strip() for col in benchmark.columns]
        
        # Rename
        benchmark.rename(columns={'PX_LAST': 'close'}, inplace=True)
        benchmark.rename(columns={'date': 'Date'}, inplace=True)
        #print("Benchmark columns:", benchmark.columns)

        # Now set 'Date' as the index
        benchmark['Date'] = pd.to_datetime(benchmark['Date'])
        benchmark.set_index('Date', inplace=True)
        benchmark = benchmark.squeeze()  # Convert to Series if possible

        strategy = strategy.sort_index(ascending=True)
        benchmark = benchmark.sort_index(ascending=True)

        # Align both series on their common dates
        common_dates = strategy.index.intersection(benchmark.index)
        strategy = strategy.loc[common_dates]
        benchmark = benchmark.loc[common_dates]

        # Now call quant_stats with the aligned close data
        results = quant_stats(strategy_name, strategy, benchmark_name, benchmark)

        results = replace_infinity_with_neg_one(results)
        results = replace_nan_and_inf(results)

        #print(results)

        return jsonify(results), 200
    
    except ImportError as e:
        print(f"Error importing user function: {e}")
        return {"error": "Failed to load user function"}, 500
    except Exception as e:
        error_message = {"error": str(e)}
        print("Error in /api/quantstats:", error_message)
        return jsonify(error_message), 500

if __name__ == "__main__":
    try:
        app.run(debug=True, use_reloader=False)

    except KeyboardInterrupt:
        print("\nShutting down server.")
