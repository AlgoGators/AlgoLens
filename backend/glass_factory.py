import os
import sys
import io
import traceback
import json
import importlib.util
import logging
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Directory to store custom code files
CUSTOM_CODE_DIR = os.path.join(os.getcwd(), "custom_metrics")
os.makedirs(CUSTOM_CODE_DIR, exist_ok=True)

def save_code_to_file(code, name, description=""):
    """
    Save Python code to a file in the custom metrics directory.
    
    Parameters:
    -----------
    code : str
        The Python code to save
    name : str
        The name to give the metric
    description : str
        Optional description of what the metric does
    
    Returns:
    --------
    str
        The path to the saved file
    """
    try:
        # Clean the name to make it suitable for a filename
        clean_name = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in name)
        
        # Add timestamp to ensure uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{clean_name}_{timestamp}.py"
        filepath = os.path.join(CUSTOM_CODE_DIR, filename)
        
        # Add header with metadata
        header = f"""# Name: {name}
# Description: {description}
# Created: {datetime.now()}

"""
        # Write the code to the file
        with open(filepath, 'w') as f:
            f.write(header + code)
        
        logger.info(f"Saved custom metric to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Error saving code to file: {str(e)}")
        raise

def get_all_custom_metrics():
    """
    Get a list of all custom metrics in the custom metrics directory.
    
    Returns:
    --------
    list
        A list of dictionaries containing information about each metric
    """
    metrics = []
    try:
        for filename in os.listdir(CUSTOM_CODE_DIR):
            if filename.endswith('.py'):
                filepath = os.path.join(CUSTOM_CODE_DIR, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                
                # Extract metadata from header comments
                name = filename.replace('.py', '')
                description = ""
                created_at = ""
                
                for line in content.split('\n')[:5]:  # Look in first 5 lines
                    if line.startswith('# Name:'):
                        name = line.replace('# Name:', '').strip()
                    elif line.startswith('# Description:'):
                        description = line.replace('# Description:', '').strip()
                    elif line.startswith('# Created:'):
                        created_at = line.replace('# Created:', '').strip()
                
                metrics.append({
                    'filename': filename,
                    'name': name,
                    'description': description,
                    'created_at': created_at
                })
    except Exception as e:
        logger.error(f"Error getting custom metrics: {str(e)}")
    
    return metrics

def load_custom_code(filename):
    """
    Load custom code from a file in the custom metrics directory.
    
    Parameters:
    -----------
    filename : str
        The filename of the custom code
    
    Returns:
    --------
    str
        The code from the file, or None if the file doesn't exist
    """
    filepath = os.path.join(CUSTOM_CODE_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return f.read()
    return None

def import_custom_metric(filename):
    """
    Import a custom metric module from a file.
    
    Parameters:
    -----------
    filename : str
        The filename of the custom metric
    
    Returns:
    --------
    module
        The imported module, or None if import failed
    """
    try:
        filepath = os.path.join(CUSTOM_CODE_DIR, filename)
        
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return None
        
        # Generate a unique module name
        module_name = f"custom_metric_{uuid.uuid4().hex}"
        
        # Import the module from the file
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        return module
    except Exception as e:
        logger.error(f"Error importing custom metric {filename}: {str(e)}")
        return None

def execute_custom_code(code, input_data=None):
    """
    Execute custom Python code and return the result.
    
    Parameters:
    -----------
    code : str
        The Python code to execute
    input_data : dict, optional
        Input data to make available to the code
    
    Returns:
    --------
    dict
        A dictionary containing the execution results
    """
    # Create a string buffer to capture stdout
    stdout_buffer = io.StringIO()
    
    # Store the original stdout
    original_stdout = sys.stdout
    
    # Prepare the result dictionary
    result = {
        "success": False,
        "stdout": "",
        "error": None
    }
    
    try:
        # Redirect stdout to our buffer
        sys.stdout = stdout_buffer
        
        # Create a local namespace
        local_namespace = {
            "input_data": input_data,
            "pd": __import__("pandas"),
            "np": __import__("numpy"),
            "result": result
        }
        
        # Add system function if it's defined in the global scope
        try:
            from system import system
            local_namespace["system"] = system
        except ImportError:
            pass
        
        # Add quant_stats function if it's defined in the global scope
        try:
            from quant import quant_stats
            local_namespace["quant_stats"] = quant_stats
        except ImportError:
            pass
        
        # Execute the code
        exec(code, local_namespace)
        
        # Capture stdout
        result["stdout"] = stdout_buffer.getvalue()
        
        # Check if there's a custom_metric function defined
        if "custom_metric" in local_namespace and callable(local_namespace["custom_metric"]):
            # Call the custom_metric function with input_data if provided
            metric_result = local_namespace["custom_metric"](input_data) if input_data else local_namespace["custom_metric"]()
            
            # Merge the metric result with our result dictionary
            if isinstance(metric_result, dict):
                for key, value in metric_result.items():
                    result[key] = value
        
        # Check if chart_data is defined in the namespace
        if "chart_data" in local_namespace:
            result["chart_data"] = local_namespace["chart_data"]
        
        result["success"] = True
        
    except Exception as e:
        # Get the exception details
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["traceback"] = traceback.format_exc()
        
    finally:
        # Restore the original stdout
        sys.stdout = original_stdout
    
    return result