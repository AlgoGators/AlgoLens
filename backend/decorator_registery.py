import os
import sys
import importlib
import importlib.util
import json
from functools import wraps

CACHED_FUNCTIONS_FILE = "AlgoLens/backend/cached_functions.json"

def load_cached_functions():
    """Load the cached decorated functions from JSON file; create file if missing."""
    if not os.path.exists(CACHED_FUNCTIONS_FILE):
        # Ensure directory exists.
        os.makedirs(os.path.dirname(CACHED_FUNCTIONS_FILE), exist_ok=True)
        with open(CACHED_FUNCTIONS_FILE, "w") as f:
            json.dump({"decorated_functions": []}, f)
        return {"decorated_functions": []}
    else:
        try:
            with open(CACHED_FUNCTIONS_FILE, "r") as f:
                data = json.load(f)
            if "decorated_functions" not in data:
                data["decorated_functions"] = []
            return data
        except json.JSONDecodeError:
            # If file is corrupted, reset it.
            with open(CACHED_FUNCTIONS_FILE, "w") as f:
                json.dump({"decorated_functions": []}, f)
            return {"decorated_functions": []}

def save_cached_functions(data):
    """Save the cached decorated functions to the JSON file."""
    with open(CACHED_FUNCTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def verify_cache_entry(entry):
    """
    Verify that a cache entry (with keys "module" and "function") is still valid:
      - The module file exists.
      - The module can be loaded.
      - The expected function exists and is callable.
    Returns True if the entry is valid, False otherwise.
    """
    module_file = entry.get("module")
    func_name = entry.get("function")
    
    if not os.path.exists(module_file):
        print(f"Cache invalid: Module file '{module_file}' does not exist.")
        return False

    spec = importlib.util.spec_from_file_location("temp_module", module_file)
    if spec is None:
        print(f"Cache invalid: Could not load spec from '{module_file}'.")
        return False

    temp_module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(temp_module)
    except Exception as e:
        print(f"Cache invalid: Error loading module from '{module_file}': {e}")
        return False

    if not hasattr(temp_module, func_name):
        print(f"Cache invalid: Function '{func_name}' not found in module '{module_file}'.")
        return False

    if not callable(getattr(temp_module, func_name)):
        print(f"Cache invalid: Attribute '{func_name}' in module '{module_file}' is not callable.")
        return False

    return True

def discover_decorated_functions(base_dir):
    """
    Discover and import all Python files from a directory recursively.
    Return a dictionary of functions that have been decorated with AlgoLens.
    
    Decorated functions are identified by the attribute `_algo_lens_decorated`.
    
    Parameters:
        base_dir (str): Path to the base directory for discovery.
    
    Returns:
        dict: Mapping from function name to the function object.
    """
    discovered_functions = {}
    
    # Exclude directories you don't want to search.
    excluded_dirs = {'venv', 'node_modules', '__pycache__', '.git', 'backend', 'frontend'}
    
    # Add the base directory to sys.path to allow importing local packages.
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    
    for root, dirs, files in os.walk(base_dir):
        # Exclude specified directories.
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                print(f"Processing file: {file}")
                # Build module path relative to base_dir.
                module_path = os.path.relpath(os.path.join(root, file), start=base_dir)
                module_name, _ = os.path.splitext(module_path.replace(os.sep, "."))
                print(f"Attempting to import module: {module_name}")
                
                try:
                    module = importlib.import_module(module_name)
                    print(f"Module '{module_name}' imported successfully.")
                    
                    # Look for decorated functions in the module.
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        # Check if callable and has our marker attribute.
                        if callable(attr) and getattr(attr, "_algo_lens_decorated", False):
                            print(f"Found decorated function: {attr_name} in module {module_name}")
                            discovered_functions[attr_name] = attr
                            
                except Exception as e:
                    print(f"Error importing {module_name}: {e}")
                    
    return discovered_functions

decorated_functions = {}

def AlgoLens(dev=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            print(f"Executing {func.__name__}...")
            return func(*args, **kwargs)
        # Mark the function as decorated
        wrapper._algo_lens_decorated = True
        return wrapper
    return decorator
