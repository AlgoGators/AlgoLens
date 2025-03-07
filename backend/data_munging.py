import numpy as np
import quantstats as qs
import pandas as pd
import math

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
    