from data_access import DataAccess
import pandas as pd

def system_lmao():
    data = DataAccess()

    # Define the symbols by group.
    symbols_by_group = {
        'stocks': ['GF.v.0'],
        'futures': ['RB.v.0', 'CL.v.0'],
        'options': ['YM.v.0']
    }

    # Dictionary to hold a DataFrame for each group.
    group_dataframes = {}

    # Fetch and process data for each group.
    for group, symbols in symbols_by_group.items():
        df = pd.DataFrame(
            data.get_ohlcv_data('2017-06-07', '2024-12-19', symbols),
            columns=['time', 'open', 'high', 'low', 'close', 'volume', 'symbol']
        )
        # Process the dataframe:
        # - Convert 'time' to datetime and rename it to 'Date'
        # - Set the Date as the index and remove timezone information.
        df['time'] = pd.to_datetime(df['time'])
        df.rename(columns={'time': 'Date'}, inplace=True)
        df.set_index('Date', inplace=True)
        df.index = df.index.tz_localize(None)
        group_dataframes[group] = df

    # Create a portfolio-level dataframe.
    # For each group, pivot the data to have each symbol's 'close' as a separate column,
    # then average the columns to get the group's average 'close' series.
    portfolio_series = {}
    for group, df in group_dataframes.items():
        # Pivot so that each symbol is a separate column.
        pivot = df.pivot_table(values='close', index=df.index, columns='symbol')
        # Average across the symbols for equal weighting.
        group_avg = pivot.mean(axis=1).squeeze()
        portfolio_series[group] = group_avg

    # Combine the group series into a single DataFrame.
    portfolio_df = pd.DataFrame(portfolio_series)
    # Create an overall portfolio column that is the equal-weighted average of the groups.
    portfolio_df['portfolio'] = portfolio_df.mean(axis=1)
    
    # Add the overall portfolio as another entry in the group_dataframes dictionary.
    group_dataframes['portfolio'] = portfolio_df['portfolio']

    return group_dataframes
