import os
import sys
import importlib
import importlib.util
import inspect
from functools import wraps

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
                    
                    # Print file contents of the imported module
                    if hasattr(module, '__file__') and module.__file__:
                        try:
                            with open(module.__file__, 'r') as f:
                                contents = f.read()
                                print(f"Contents of {module.__file__}:")
                                print(contents)
                        except Exception as file_error:
                            print(f"Error reading file {module.__file__}: {file_error}")
                    else:
                        print("Module does not have a __file__ attribute.")
                    
                    # Use inspect to get all functions defined in the module.
                    functions = inspect.getmembers(module, inspect.isfunction)
                    print(functions)
                    for func_name, func in functions:
                        is_decorated = getattr(func, "_algo_lens_decorated", False)
                        print(f"Found function: {func_name} (decorated: {is_decorated})")
                        if is_decorated:
                            return func
                            
                except Exception as e:
                    print(f"Error importing {module_name}: {e}")
                    
    return discovered_functions

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

