from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import os
import warnings
import logging

from system import system
from quant import quant_stats
from data_munging import replace_nan_and_inf, replace_infinity_with_neg_one
from glass_factory import (save_code_to_file, 
                           import_custom_metric,
                           get_all_custom_metrics, 
                           load_custom_code, 
                           execute_custom_code)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("custom_metrics.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Suppress specific warnings that occur in QuantStats calculations
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Mean of empty slice")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered in scalar divide")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Degrees of freedom <= 0 for slice")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="divide by zero encountered")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered in multiply")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered in divide")

app = Flask(__name__)
CORS(app)

# Directory to store custom code files
CUSTOM_CODE_DIR = os.path.join(os.getcwd(), "custom_metrics")
os.makedirs(CUSTOM_CODE_DIR, exist_ok=True)
logger.info(f"Custom metrics directory: {CUSTOM_CODE_DIR}")

@app.route('/api/custom-metrics/<filename>', methods=['GET'])
def get_custom_metric(filename):
    """
    Get a specific custom metric by filename.
    """
    code = load_custom_code(filename)
    if not code:
        return jsonify({"error": "Metric not found"}), 404
    
    # Extract metadata from comments
    name = ""
    description = ""
    created_at = ""
    
    for line in code.split('\n')[:5]:
        if line.startswith('# Name:'):
            name = line.replace('# Name:', '').strip()
        elif line.startswith('# Description:'):
            description = line.replace('# Description:', '').strip()
        elif line.startswith('# Created:'):
            created_at = line.replace('# Created:', '').strip()
    
    return jsonify({
        "filename": filename,
        "name": name,
        "description": description,
        "created_at": created_at,
        "code": code
    })

@app.route('/api/run-single-metric', methods=['POST'])
def run_single_metric():
    """
    Run a single custom metric and return the result.
    """
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing filename"}), 400
    
    filename = data["filename"]
    logger.info(f"Running single custom metric: {filename}")
    
    # Load the code
    code = load_custom_code(filename)
    if not code:
        return jsonify({"success": False, "error": "Metric file not found"}), 404
    
    # Prepare input data if available
    input_data = data.get("data")
    if not input_data and "category" in data:
        # If no data but category is specified, get data from system
        try:
            strategy_groups = system()
            category = data["category"]
            
            if category == "portfolio":
                input_data = {"data": strategy_groups.get("portfolio")}
            else:
                group_df = strategy_groups.get(category)
                if group_df is not None:
                    pivot = group_df.pivot_table(values='close', index=group_df.index, columns='symbol')
                    input_data = {"data": pivot.mean(axis=1).squeeze()}
        except Exception as e:
            logger.error(f"Error preparing data for metric: {str(e)}")
    
    # Execute the code
    result = execute_custom_code(code, input_data)
    
    return jsonify(result)

@app.route('/api/run-custom-metrics', methods=['POST'])
def run_custom_metrics():
    """
    Run selected custom metrics on provided data.
    """
    data = request.get_json()
    if not data or "metrics" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    metrics = data["metrics"]
    input_data = data.get("data")
    
    results = {}
    for metric_filename in metrics:
        logger.info(f"Running custom metric: {metric_filename}")
        
        # Try to import the module
        module = import_custom_metric(metric_filename)
        if module is None:
            results[metric_filename] = {"success": False, "error": "Failed to import metric"}
            continue
        
        # Check if the module has a custom_metric function
        if hasattr(module, 'custom_metric') and callable(module.custom_metric):
            try:
                # Call the custom_metric function with the provided data
                metric_result = module.custom_metric(input_data) if input_data else module.custom_metric()
                results[metric_filename] = {
                    "success": True,
                    "metric_value": metric_result
                }
                logger.info(f"Successfully executed custom metric: {metric_filename}")
            except Exception as e:
                results[metric_filename] = {
                    "success": False,
                    "error": f"Error executing custom metric: {str(e)}"
                }
                logger.error(f"Error executing custom metric {metric_filename}: {str(e)}")
        else:
            # If no custom_metric function, try to execute the code directly
            code = load_custom_code(metric_filename)
            if code:
                metric_result = execute_custom_code(code, input_data)
                results[metric_filename] = metric_result
            else:
                results[metric_filename] = {"success": False, "error": "Metric file not found"}
    
    return jsonify(results)

@app.route('/api/custom-metrics', methods=['GET', 'POST'])
def custom_metrics():
    if request.method == 'GET':
        metrics = get_all_custom_metrics()
        return jsonify(metrics)
    elif request.method == 'POST':
        data = request.get_json()
        if not data or "code" not in data or "name" not in data:
            return jsonify({"error": "Missing required fields"}), 400
        
        code = data["code"]
        name = data["name"]
        description = data.get("description", "")
        
        try:
            filepath = save_code_to_file(code, name, description)
            return jsonify({
                "success": True,
                "message": f"Custom metric saved to {filepath}",
                "filepath": filepath
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

@app.route('/api/glassfactory', methods=['POST'])
def glass_factory():
    """
    Executes Python code passed in the JSON payload and returns its output.
    Expected JSON format:
      { 
        "code": "print('Hello, World!')",
        "save": true,
        "name": "My Custom Metric",
        "description": "Does something cool"
      }
    """
    try:
        data = request.get_json()
        if not data or "code" not in data:
            return jsonify({"error": "No code provided"}), 400
        
        code = data["code"]
        save_metric = data.get("save", False)
        
        # Execute the code
        result = execute_custom_code(code)
        
        # Prepare response
        response_data = {
            "result": result.get("stdout", ""),
            "success": result.get("success", False)
        }
        
        # Add chart data if available
        if "chart_data" in result:
            response_data["chart_data"] = result["chart_data"]
        
        # Add error if any
        if "error" in result:
            response_data["error"] = result["error"]
        
        # Save the code if requested
        if save_metric and "name" in data:
            name = data["name"]
            description = data.get("description", "")
            filepath = save_code_to_file(code, name, description)
            response_data["saved"] = True
            response_data["filepath"] = filepath
            logger.info(f"Saved custom metric from glassfactory: {name}")
            
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"Error in /api/glassfactory: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/quantstats', methods=['POST'])
def algo_scope():
    """
    Calls system() to obtain portfolio-level positions and provide processed data to front-end.
    
    Returns
    -------
    results : dict
        Jsonified dictionary of processed data filtered by the selected category.
    """
    try:
        req_data = request.get_json()
        # Get category (default "portfolio")
        category = req_data.get("category", "portfolio")
        # Get custom metrics to run (if any)
        custom_metrics = req_data.get("customMetrics", [])
        
        logger.info(f"Running quantstats for category: {category}")
        if custom_metrics:
            logger.info(f"With custom metrics: {custom_metrics}")

        strategy_name = "Mean Reversion"
        benchmark_name = "Index"

        # Get the grouped dataframes from system
        strategy_groups = system()

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

        logger.info(f"Strategy data shape before processing: {strategy_filtered.shape}")
        logger.info(f"Date range: {strategy_filtered.index.min()} to {strategy_filtered.index.max()}")

        # Process the strategy series: convert to numeric, drop NAs, and compute percentage change.
        strategy_processed = pd.to_numeric(strategy_filtered, errors='coerce')
        strategy_processed = strategy_processed.dropna().pct_change().dropna()
        
        logger.info(f"Strategy data shape after processing: {strategy_processed.shape}")

        # Check if we have enough data to proceed
        if len(strategy_processed) < 2:
            return jsonify({"error": "Insufficient strategy data for analysis"}), 400

        # ----- Load benchmark data -----
        sg_trend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'SG Trend Index.xlsx'))
        benchmark = pd.read_excel(sg_trend_dir, skiprows=6)
        benchmark.columns = [col.strip() for col in benchmark.columns]
        benchmark.rename(columns={'PX_LAST': 'close', 'date': 'Date'}, inplace=True)
        benchmark['Date'] = pd.to_datetime(benchmark['Date'])
        benchmark.set_index('Date', inplace=True)
        benchmark = benchmark.squeeze()

        # Process benchmark data - no date filtering here either
        benchmark = pd.to_numeric(benchmark, errors='coerce')
        benchmark = benchmark.pct_change().dropna()
        
        logger.info(f"Benchmark data shape after processing: {benchmark.shape}")

        # Check if we have enough benchmark data
        if len(benchmark) < 2:
            return jsonify({"error": "Insufficient benchmark data for analysis"}), 400

        # Ensure both series are sorted.
        strategy_processed = strategy_processed.sort_index(ascending=True)
        benchmark = benchmark.sort_index(ascending=True)

        # Align both series on their common dates.
        common_dates = strategy_processed.index.intersection(benchmark.index)
        logger.info(f"Number of common dates: {len(common_dates)}")
        
        # Check if we have enough common dates
        if len(common_dates) < 2:
            return jsonify({"error": "Insufficient overlapping data between strategy and benchmark"}), 400
            
        strategy_processed = strategy_processed.loc[common_dates]
        benchmark = benchmark.loc[common_dates]
        
        logger.info(f"Final data shapes - Strategy: {strategy_processed.shape}, Benchmark: {benchmark.shape}")

        # Run quant_stats calculations with warning suppression
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            results = quant_stats(strategy_name, strategy_processed, benchmark_name, benchmark)
            
        # Post-process results to handle any remaining NaN or infinity values
        results = replace_infinity_with_neg_one(results)
        results = replace_nan_and_inf(results)
        
        # Run custom metrics if requested
        if custom_metrics:
            logger.info(f"Running {len(custom_metrics)} custom metrics")
            custom_results = {}
            data_for_metrics = {
                "strategy": strategy_processed,
                "benchmark": benchmark,
                "strategy_name": strategy_name,
                "benchmark_name": benchmark_name
            }
            
            for metric_filename in custom_metrics:
                logger.info(f"Running custom metric: {metric_filename}")
                code = load_custom_code(metric_filename)
                if code:
                    metric_result = execute_custom_code(code, data_for_metrics)
                    
                    # Extract the metric name from filename
                    metric_name = os.path.splitext(metric_filename)[0]
                    
                    # Add metric value to results if available
                    if metric_result.get("success", False):
                        if "metric_value" in metric_result:
                            results[f"custom_{metric_name}"] = metric_result["metric_value"]
                            logger.info(f"Added custom metric value for {metric_name}")
                        
                        # Add chart data if available
                        if "chart_data" in metric_result:
                            if "charts" not in results:
                                results["charts"] = {}
                            results["charts"][metric_name] = metric_result["chart_data"]
                            logger.info(f"Added custom chart for {metric_name}")
                    else:
                        # Log error
                        error_msg = metric_result.get("error", "Unknown error")
                        logger.error(f"Error running custom metric {metric_name}: {error_msg}")
                        
                        # Add error information to results
                        if "charts" not in results:
                            results["charts"] = {}
                        results["charts"][f"error_{metric_name}"] = {"error": error_msg}
                else:
                    logger.error(f"Custom metric file not found: {metric_filename}")

        return jsonify(results), 200

    except ImportError as e:
        logger.error(f"Error importing user function: {str(e)}")
        return jsonify({"error": "Failed to load user function"}), 500
    except Exception as e:
        logger.error(f"Error in /api/quantstats: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    logger.info("Starting Flask application")
    try:
        app.run(debug=True, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Shutting down server.")
