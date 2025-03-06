from flask import Flask, jsonify, request
from flask_cors import CORS
import quantstats as qs
import pandas as pd
import numpy as np
import os
import math

from .decorator_registery import discover_decorated_functions

app = Flask(__name__)
CORS(app)

def calculate_extended_metrics(returns, benchmark, rf=0.0, periods=252):
    """
    Calculates additional metrics including delta, gamma, theta, and omega.
    Uses the existing `greeks` function for alpha and beta.
    """
    try:
        # Use quantstats' greeks function for alpha and beta
        greeks = qs.stats.greeks(returns, benchmark)
        delta = greeks.get("beta", np.nan)
        alpha = greeks.get("alpha", np.nan)
    except Exception as e:
        print("Error in qs_greeks:", e)
        delta = np.nan
        alpha = np.nan

    # Gamma
    gamma = (
        np.cov(returns.diff(), benchmark.diff())[0, 1] / np.var(benchmark.diff())
        if len(returns) > 1
        else np.nan
    )

    # Theta
    theta = returns.mean() * -1 * periods

    # Omega
    try:
        omega_ratio = qs.stats.omega(returns, rf=rf, required_return=0.0, periods=periods)
    except Exception as e:
        print("Error in omega:", e)
        omega_ratio = np.nan

    # Combine results
    metrics = pd.Series(
        {
            "beta": delta,
            "alpha": alpha,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "omega": omega_ratio,
        }
    ).fillna(0)

    return metrics

# Helper function to convert non-serializable types
def make_serializable(data):
    if isinstance(data, (np.int64, np.int32)):  # Handle NumPy integers
        return int(data)
    elif isinstance(data, (np.float64, np.float32)):  # Handle NumPy floats
        if np.isnan(data):  # Check for NaN
            return None  # Replace NaN with None (JSON null)
        return float(data)
    elif isinstance(data, pd.Series):  # Handle pandas Series
        return {
            str(k): (None if pd.isna(v) else v)
            for k, v in data.to_dict().items()
        }  # Replace NaN with None
    elif isinstance(data, pd.DataFrame):  # Handle pandas DataFrame
        return data.reset_index().apply(
            lambda x: x.map(
                lambda v: None if pd.isna(v) else (str(v) if isinstance(v, pd.Timestamp) else v)
            ),
            axis=1,
        ).to_dict(orient="records")  # Replace NaN with None
    elif isinstance(data, (np.ndarray, list)):  # Handle NumPy arrays and lists
        return [None if pd.isna(v) else v for v in data]
    elif isinstance(data, pd.Timestamp):  # Handle pandas Timestamp
        return str(data)
    else:
        return data  # Return data as is if already serializable

def quant_stats(strategy_name : str, strategy : pd.Series, benchmark_name : str, benchmark : pd.Series) -> dict:
    """Utilizes the quantstats library and other processing to return the results dictionary

    Parameters
    ----------
    strategy_name : str
        The name of the over-arching strategy behind the positions obtained from the system
    strategy : pd.Series
        The positions of the strategy
    benchmark_name : str
        The name of the benchmark used to find performance metrics
    benchmark : pd.Series
        The positions of the benchmark
        

    Returns
    -------
    dict
        The processed data
    """
    strategy = strategy.pct_change().dropna()
    benchmark = benchmark.pct_change().dropna()
    
    # Align the data to include full benchmark history
    full_history = pd.DataFrame({benchmark_name: benchmark, strategy_name: strategy})
    full_history = full_history.loc[strategy.index].dropna()
    
    strategy = full_history[strategy_name]
    benchmark = full_history[benchmark_name]

    # Calculate cumulative returns
    full_history[benchmark_name+"_Cumulative"] = (1 + full_history[benchmark_name]).cumprod()
    full_history["Stock_Cumulative"] = (1 + full_history[strategy_name]).cumprod()

    # Calculate percentage change vs. S&P 500
    full_history["Pct_Change_VS_"+benchmark_name] = (
        full_history["Stock_Cumulative"] - full_history[benchmark_name+"_Cumulative"]
    )

    # Rolling Metrics
    rolling_window = 30  # 30-day rolling window
    rolling_sharpe = qs.stats.rolling_sharpe(strategy, rolling_window)
    rolling_sortino = qs.stats.rolling_sortino(strategy, rolling_window)
    rolling_volatility = strategy.rolling(rolling_window).std() * np.sqrt(252)  # Annualized

    # Calculate distributions with serialized dates
    distribution = {
        "daily": {
            "dates": [date.strftime('%Y-%m-%d') for date in strategy.index],
            "values": strategy.tolist(),
        },
        "weekly": {
            "dates": [date.strftime('%Y-%m-%d') for date in strategy.resample("W").mean().index],
            "values": strategy.resample("W").mean().tolist(),
        },
        "monthly": {
            "dates": [date.strftime('%Y-%m-%d') for date in strategy.resample("ME").mean().index],
            "values": strategy.resample("ME").mean().tolist(),
        },
        "quarterly": {
            "dates": [date.strftime('%Y-%m-%d') for date in strategy.resample("QE").mean().index],
            "values": strategy.resample("QE").mean().tolist(),
        },
        "yearly": {
            "dates": [date.strftime('%Y-%m-%d') for date in strategy.resample("YE").mean().index],
            "values": strategy.resample("YE").mean().tolist(),
        },
    }
    # Prepare initial response with charts
    results = {
        "stock_price": make_serializable(full_history["Stock_Cumulative"]),
        benchmark_name+"_cumulative": make_serializable(full_history[benchmark_name+"_Cumulative"]),
        "percentage_change_vs_"+benchmark_name: make_serializable(
            full_history["Pct_Change_VS_"+benchmark_name]
        ),
        "implied_volatility": make_serializable(
            qs.stats.implied_volatility(full_history[strategy_name])
        ),
        "rolling_sharpe": make_serializable(rolling_sharpe),
        "rolling_sortino": make_serializable(rolling_sortino),
        "rolling_volatility": make_serializable(rolling_volatility),
        "distribution": distribution,
    }
    functions_list = [
        "adjusted_sortino", "avg_loss", "avg_return", "avg_win", "best", "cagr", "calmar",
        "common_sense_ratio", "comp", "conditional_value_at_risk", "consecutive_losses",
        "consecutive_wins", "cpc_index", "cvar", "expected_return",
        "expected_shortfall", "exposure", "gain_to_pain_ratio", "geometric_mean", "ghpr", "greeks",
        "information_ratio", "kelly_criterion", "kurtosis", "max_drawdown", "omega",
        "outlier_loss_ratio", "outlier_win_ratio", "outliers", "payoff_ratio",
        "probabilistic_adjusted_sortino_ratio", "probabilistic_ratio", "probabilistic_sharpe_ratio",
        "risk_of_ruin", "risk_return_ratio", "ror", "serenity_index", "sharpe", "skew", "smart_sharpe",
        "smart_sortino", "sortino", "tail_ratio", "ulcer_index", "ulcer_performance_index", "upi",
        "value_at_risk", "var", "volatility", "win_loss_ratio", "win_rate", "worst",
    ]
    
    # Add calculated metrics to the results
    for func_name in functions_list:
        try:
            func = getattr(qs.stats, func_name)

            # Handle functions requiring additional arguments
            if func_name in ["information_ratio", "r_squared"]:
                result = func(strategy, benchmark)
            else:
                result = func(strategy)

            results[func_name] = make_serializable(result)

        except Exception as e:
            results[func_name] = f"Error in {func_name}: {e}"

    # Calculate extended metrics (including omega and additional Greeks)
    extended_metrics = calculate_extended_metrics(strategy, benchmark)

    results.update(extended_metrics.to_dict())

    return results

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
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        print("Base directory:", base_dir)

        # Discover the decorated functions from the project.
        func = discover_decorated_functions(base_dir)
        # Execute the function to get the strategy data
        strategy = func()

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

def replace_infinity_with_neg_one(obj):
    """
    Recursively walks through a data structure (dict, list, float, etc.)
    and replaces any infinite value with -1.
    """
    if isinstance(obj, dict):
        # Recurse for each key-value pair in a dictionary
        return {
            key: replace_infinity_with_neg_one(value) 
            for key, value in obj.items()
        }

    elif isinstance(obj, list):
        # Recurse for each element in a list
        return [
            replace_infinity_with_neg_one(item) 
            for item in obj
        ]

    elif isinstance(obj, (float, np.float64)):
        # Check if the float is infinite
        if math.isinf(obj):
            return -1
        return obj

    # For anything else (int, string, etc.), just return as is
    return obj

def replace_nan_and_inf(obj):
    """
    Recursively replace NaN and Inf values in a nested structure
    (dict, list, float, etc.) with None.
    """
    if isinstance(obj, dict):
        return {k: replace_nan_and_inf(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_nan_and_inf(item) for item in obj]
    elif isinstance(obj, float) or isinstance(obj, np.floating):
        # Check for NaN or Inf
        if math.isnan(obj) or math.isinf(obj):
            return None  # or any other placeholder like -1
        return float(obj)
    else:
        # Return the object if it’s not a dict, list, or float
        return obj

if __name__ == "__main__":
    try:
        app.run(debug=True, use_reloader=False)

    except KeyboardInterrupt:
        print("\nShutting down server.")
