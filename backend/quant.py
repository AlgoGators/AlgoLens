import quantstats as qs
import numpy as np
import pandas as pd

from data_munging import make_serializable

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
