from flask import Flask, jsonify
from flask_cors import CORS
import quantstats as qs
import pandas as pd
import numpy as np
from quantstats.stats import omega, greeks as qs_greeks

def calculate_extended_metrics(returns, benchmark, rf=0.0, periods=252):
    """
    Calculates additional metrics including delta, gamma, theta, and omega.
    Uses the existing `greeks` function for alpha and beta.
    """
    # Use quantstats' greeks function for alpha and beta
    greeks = qs_greeks(returns, benchmark)

    # Delta: Proportional to beta
    delta = greeks["beta"]

    # Gamma: Sensitivity of delta to changes in benchmark
    gamma = (
        np.cov(returns.diff(), benchmark.diff())[0, 1] / np.var(benchmark.diff())
        if len(returns) > 1
        else np.nan
    )

    # Theta: Sensitivity of returns to time decay (approximation)
    theta = returns.mean() * -1 * periods

    # Omega: Using the provided quantstats function
    omega_ratio = omega(returns, rf=rf, required_return=0.0, periods=periods)

    # Combine results
    metrics = pd.Series(
        {
            "beta": greeks["beta"],
            "alpha": greeks["alpha"],
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "omega": omega_ratio,
        }
    ).fillna(0)

    return metrics

app = Flask(__name__)
CORS(app)

functions_list = [
        'adjusted_sortino', 'autocorr_penalty', 'avg_loss', 'avg_return', 'avg_win', 'best', 'cagr', 'calmar',
        'common_sense_ratio', 'comp', 'compsum', 'conditional_value_at_risk', 'consecutive_losses',
        'consecutive_wins', 'cpc_index', 'cvar', 'distribution', 'drawdown_details', 'expected_return',
        'expected_shortfall', 'exposure', 'gain_to_pain_ratio', 'geometric_mean', 'ghpr', 'greeks',
        'information_ratio', 'kelly_criterion', 'kurtosis', 'max_drawdown', 'monthly_returns',
        'omega', 'outlier_loss_ratio', 'outlier_win_ratio', 'outliers', 'payoff_ratio', 'pct_rank',
        'probabilistic_adjusted_sortino_ratio', 'probabilistic_ratio', 'probabilistic_sharpe_ratio',
        'probabilistic_sortino_ratio', 'profit_factor', 'profit_ratio', 'r_squared', 'rar', 'recovery_factor',
        'risk_of_ruin', 'risk_return_ratio', 'ror', 'serenity_index', 'sharpe', 'skew', 'smart_sharpe', 'smart_sortino', 'sortino',
        'tail_ratio', 'treynor_ratio', 'ulcer_index', 'ulcer_performance_index', 'upi',
        'value_at_risk', 'var', 'volatility', 'win_loss_ratio', 'win_rate', 'worst'
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
        ticker = "META"
        sp500_ticker = "SPY"

        # Fetch stock and S&P 500 data
        stock = qs.utils.download_returns(ticker)
        sp500 = qs.utils.download_returns(sp500_ticker)

        # Align the data to include full S&P 500 history
        full_history = pd.DataFrame({"SP500": sp500, ticker: stock}).fillna(0)

        # Calculate cumulative returns
        full_history["SP500_Cumulative"] = (1 + full_history["SP500"]).cumprod()
        full_history["Stock_Cumulative"] = (1 + full_history[ticker]).cumprod()

        # Calculate percentage change vs. S&P 500
        full_history["Pct_Change_VS_SP500"] = (
            full_history["Stock_Cumulative"] - full_history["SP500_Cumulative"]
        )

        # Rolling Metrics
        rolling_window = 30  # 30-day rolling window
        rolling_sharpe = qs.stats.rolling_sharpe(stock, rolling_window)
        rolling_sortino = qs.stats.rolling_sortino(stock, rolling_window)
        rolling_volatility = stock.rolling(rolling_window).std() * np.sqrt(252)  # Annualized

        # Calculate distributions with serialized dates
        distribution = {
            "daily": {
                "dates": [date.strftime('%Y-%m-%d') for date in stock.index],
                "values": stock.tolist(),
            },
            "weekly": {
                "dates": [date.strftime('%Y-%m-%d') for date in stock.resample("W").mean().index],
                "values": stock.resample("W").mean().tolist(),
            },
            "monthly": {
                "dates": [date.strftime('%Y-%m-%d') for date in stock.resample("M").mean().index],
                "values": stock.resample("M").mean().tolist(),
            },
            "quarterly": {
                "dates": [date.strftime('%Y-%m-%d') for date in stock.resample("Q").mean().index],
                "values": stock.resample("Q").mean().tolist(),
            },
            "yearly": {
                "dates": [date.strftime('%Y-%m-%d') for date in stock.resample("A").mean().index],
                "values": stock.resample("A").mean().tolist(),
            },
        }

        # Prepare initial response with charts
        results = {
            "stock_price": make_serializable(full_history["Stock_Cumulative"]),
            "sp500_cumulative": make_serializable(full_history["SP500_Cumulative"]),
            "percentage_change_vs_sp500": make_serializable(
                full_history["Pct_Change_VS_SP500"]
            ),
            "implied_volatility": make_serializable(
                qs.stats.implied_volatility(full_history[ticker])
            ),
            "rolling_sharpe": make_serializable(rolling_sharpe),
            "rolling_sortino": make_serializable(rolling_sortino),
            "rolling_volatility": make_serializable(rolling_volatility),
            "distribution": distribution,
        }

        # Add calculated metrics to the results
        for func_name in functions_list:
            try:
                func = getattr(qs.stats, func_name)

                # Handle functions requiring additional arguments
                if func_name in ["information_ratio", "r_squared", 'treynor_ratio']:
                    result = func(stock, sp500)
                else:
                    result = func(stock)

                results[func_name] = make_serializable(result)

            except Exception as e:
                results[func_name] = f"Error in {func_name}: {e}"

        # Calculate extended metrics (including omega and additional Greeks)
        try:
            extended_metrics = calculate_extended_metrics(stock, sp500)
            results.update(extended_metrics.to_dict())
        except Exception as e:
            results["extended_metrics_error"] = f"Error in calculating extended metrics: {e}"

        return jsonify(results), 200

    except Exception as e:
        error_message = {"error": str(e)}
        print("Error in /api/quantstats:", error_message)
        return jsonify(error_message), 500



if __name__ == '__main__':
    app.run(port=5000, debug=True)
