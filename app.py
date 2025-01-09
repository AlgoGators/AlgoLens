from flask import Flask, jsonify
from flask_cors import CORS
import quantstats as qs
import pandas as pd
import numpy as np

app = Flask(__name__)
CORS(app)

functions_list = [
    'adjusted_sortino', 'avg_loss', 'avg_return', 'avg_win', 'best', 'cagr', 'calmar', 'common_sense_ratio',
    'conditional_value_at_risk', 'consecutive_losses', 'consecutive_wins', 'cvar', 'drawdown_details',
    'expected_return', 'expected_shortfall', 'gain_to_pain_ratio', 'geometric_mean', 'ghpr', 'implied_volatility',
    'information_ratio', 'kelly_criterion', 'kurtosis', 'max_drawdown', 'monthly_returns', 'omega', 'payoff_ratio',
    'profit_factor', 'profit_ratio', 'recovery_factor', 'risk_return_ratio', 'sharpe', 'skew', 'sortino',
    'value_at_risk', 'var', 'volatility', 'win_loss_ratio', 'win_rate'
]

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

@app.route('/api/quantstats', methods=['POST'])
def get_quantstats_metrics():
    try:
        # Static ticker for now (e.g., META)
        ticker = "META"

        # Fetch daily returns for the static ticker
        stock = qs.utils.download_returns(ticker)
        print(f"Downloaded returns for static ticker {ticker}: {stock.head()}")  # Debug log

        results = {}
        for func_name in functions_list:
            try:
                func = getattr(qs.stats, func_name)
                if callable(func):
                    result = func(stock)
                    results[func_name] = make_serializable(result)
                    if isinstance(results[func_name], dict):
                        print(func_name)
            except Exception as e:
                results[func_name] = f"Error in {func_name}: {e}"

        return jsonify(results), 200

    except Exception as e:
        error_message = {"error": str(e)}
        print("Error in /api/quantstats:", error_message)
        return jsonify(error_message), 500


if __name__ == '__main__':
    app.run(port=5000, debug=True)
