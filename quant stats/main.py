import quantstats as qs


def get_data(stock):

    # List of functions to call
    functions_list = [
        'adjusted_sortino', 'autocorr_penalty', 'avg_loss', 'avg_return', 'avg_win', 'best', 'cagr', 'calmar',
        'common_sense_ratio', 'comp', 'compare', 'compsum', 'conditional_value_at_risk', 'consecutive_losses',
        'consecutive_wins', 'cpc_index', 'cvar', 'distribution', 'drawdown_details', 'expected_return',
        'expected_shortfall', 'exposure', 'gain_to_pain_ratio', 'geometric_mean', 'ghpr', 'greeks',
        'implied_volatility', 'information_ratio', 'kelly_criterion', 'kurtosis', 'max_drawdown', 'monthly_returns',
        'omega', 'outlier_loss_ratio', 'outlier_win_ratio', 'outliers', 'payoff_ratio', 'pct_rank',
        'probabilistic_adjusted_sortino_ratio', 'probabilistic_ratio', 'probabilistic_sharpe_ratio',
        'probabilistic_sortino_ratio', 'profit_factor', 'profit_ratio', 'r2', 'r_squared', 'rar', 'recovery_factor',
        'remove_outliers', 'risk_of_ruin', 'risk_return_ratio', 'rolling_greeks', 'rolling_sharpe', 'rolling_sortino',
        'rolling_volatility', 'ror', 'serenity_index', 'sharpe', 'skew', 'smart_sharpe', 'smart_sortino', 'sortino',
        'tail_ratio', 'to_drawdown_series', 'treynor_ratio', 'ulcer_index', 'ulcer_performance_index', 'upi',
        'value_at_risk', 'var', 'volatility', 'warn', 'win_loss_ratio', 'win_rate', 'worst'
    ]

    # Dictionary to store results
    results = {}

    # Iterate through the list of functions
    for func_name in functions_list:
        try:
            # Get the function from the quantstats.stats module
            func = getattr(qs.stats, func_name)
            
            # Call the function and store the result
            if callable(func):
                # Some functions might require more arguments; handle them appropriately
                if func_name in ['compare', 'distribution']:
                    pass
                    # Requires a benchmark or other specific input
                    results[func_name] = func(stock, stock)  # Example with the same stock as the benchmark
                elif func_name in ['rolling_sharpe', 'rolling_sortino', 'rolling_volatility']:
                    results[func_name] = func(stock, rolling_period=252)  # Example: rolling period of 252 days
                elif func_name == 'monthly_returns':
                    results[func_name] = func(stock).to_dict()  # Convert DataFrame to dict for serialization
                else:
                    results[func_name] = func(stock)
        except Exception as e:
            # Handle exceptions and store error messages for debugging
            results[func_name] = f"Error: {e}"

    # Display results for verification
    for key, value in results.items():
        print(f"{key}: {value}\n")
    
    return results

# Fetch daily returns for a stock
stock = qs.utils.download_returns('META')

x = get_data(stock)