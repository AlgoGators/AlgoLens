from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import os
import csv
import warnings
import logging
from flask_jwt_extended import JWTManager

from system import system
from quant import quant_stats
from data_access import DataAccess
from data_munging import replace_nan_and_inf, replace_infinity_with_neg_one
from glass_factory import (save_code_to_file, 
                           import_custom_metric,
                           get_all_custom_metrics, 
                           load_custom_code, 
                           execute_custom_code)

from auth import auth_bp

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

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")

jwt = JWTManager(app)

# Directory to store custom code files
CUSTOM_CODE_DIR = os.path.join(os.getcwd(), "custom_metrics")
os.makedirs(CUSTOM_CODE_DIR, exist_ok=True)
logger.info(f"Custom metrics directory: {CUSTOM_CODE_DIR}")

app.register_blueprint(auth_bp, url_prefix="/auth")

@app.route("/metadata", methods=["GET"])
def write_metadata():
    # Query contract metadata from the database using the DataAccess layer
    data = DataAccess()
    metadata_list = data.get_contract_metadata()
    
    app.logger.info(f"Fetched {len(metadata_list)} metadata records.")
    
    # Mapping of model property names to CSV header names
    header_mapping = [
        ("databento_symbol", "Databento Symbol"),
        ("ib_symbol", "IB Symbol"),
        ("name", "Name"),
        ("exchange", "Exchange"),
        ("intraday_initial_margin", "Intraday Initial Margin"),
        ("intraday_maintenance_margin", "Intraday Maintenance Margin"),
        ("overnight_initial_margin", "Overnight Initial Margin"),
        ("overnight_maintenance_margin", "Overnight Maintenance Margin"),
        ("asset_type", "Asset Type"),
        ("sector", "Sector"),
        ("contract_size", "Contract Size"),
        ("units", "Units"),
        ("minimum_price_fluctuation", "Minimum Price Fluctuation"),
        ("tick_size", "Tick Size"),
        ("settlement_type", "Settlement Type"),
        ("trading_hours", "Trading Hours (EST)"),
        ("data_provider", "Data Provider"),
        ("dataset", "Dataset"),
        ("newest_month_additions", "Newest Month Additions"),
        ("contract_months", "Contract Months"),
        ("time_of_expiry", "Time of Expiry")
    ]
    
    # Extract CSV header names
    csv_headers = [header for _, header in header_mapping]
    
    # Determine the project root directory.
    # Since app.py is in root/backend/app.py, the project root is one directory up.
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(backend_dir)
    
    # Build the target folder path for frontend/public
    target_folder = os.path.join(project_root, "frontend", "public")
    os.makedirs(target_folder, exist_ok=True)
    file_path = os.path.join(target_folder, "metadata.csv")
    
    app.logger.info(f"Writing CSV to: {file_path}")
    
    # Write metadata into metadata.csv (leaving the base CSV unchanged)
    try:
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
            writer.writeheader()
            for record in metadata_list:
                # Map the record's keys (from the model) to CSV header names
                csv_row = {csv_header: record.get(model_field, "") for model_field, csv_header in header_mapping}
                writer.writerow(csv_row)
        if os.path.exists(file_path):
            app.logger.info("CSV file written successfully.")
        else:
            app.logger.error("CSV file was not written!")
    except Exception as e:
        app.logger.error(f"Error writing CSV: {e}")
    
    # Return the absolute file path in the response for debugging
    return jsonify({"status": "CSV written successfully", "file": file_path})

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
