import quantstats as qs
import pandas as pd
import numpy as np

from backend.data_access import DataAccess

from decorator_registery import AlgoLens

@AlgoLens()
def run_system():
    data = DataAccess()

    ohclv_6M_df = pd.DataFrame(data.get_ohlcv_data('2017-06-07', '2024-12-19', ['ZN.c.0']), 
                                columns=['time', 'open', 'high', 'low', 'close', 'volume', 'symbol'])
    
    return ohclv_6M_df